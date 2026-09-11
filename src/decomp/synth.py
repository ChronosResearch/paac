# Copyright 2026 Shashank Kumar
# SPDX-License-Identifier: Apache-2.0
# This file is part of the PAAC (Provably Aligned Core) project.
"""
src/decomp/synth.py
-------------------
Decomposition witness synthesis driver.

Two stages, deliberately separated so that neither can flatter the other.

**Stage 1, propose (Z3).** Solve a schema's arithmetic characterisation for hole
values. UNSAT over the declared hole ranges is a bounded guarantee for that
schema. This stage knows nothing about PAAC's implementation; it only knows the
arithmetic the schema declares.

**Stage 2, confirm (the real system).** Take the proposed modifications and run
them through the actual `BoundedModelChecker` and the actual `SILRuntime`. A
candidate counts as a witness only if:

  * every modification is individually ACCEPTED by the real verifier, using the
    real axiom set from `config/axioms.yaml`, and
  * executing the composed program from its entry point reaches a state that
    violates the axiom.

If stage 1 says SAT and stage 2 disagrees, the result is reported as SPURIOUS.
This is the part that makes the exercise falsifiable: an error in a schema's
hand-written arithmetic can waste a query, but it cannot produce a finding,
because the finding is established by the system under test rather than by the
model of it.

Both stages are deterministic and reproducible. There is no sampling, no seed
and no tuning, so there is nothing to bias and nothing to re-tune on rerun.
"""

from __future__ import annotations

from dataclasses import dataclass

import z3
from loguru import logger

from src.axioms.axiom_parser import Axiom, AxiomParser
from src.core.exceptions import PAACError
from src.core.sil_compiler import SILCompiler, SILError
from src.core.sil_runtime import SILRuntime, SILRuntimeError
from src.core.verifier import BoundedModelChecker

from .schema import SCHEMAS, Schema, SchemaOutcome, Witness

DEFAULT_TIMEOUT_MS = 10_000


@dataclass
class StepCheck:
    """Whether one modification was accepted by the real verifier."""

    func_name: str
    accepted: bool
    detail: str


@dataclass
class Confirmation:
    """Result of running a candidate through the real system."""

    all_steps_accepted: bool
    steps: list[StepCheck]
    runtime_violated: bool
    runtime_detail: str

    @property
    def confirmed(self) -> bool:
        """A witness requires both halves. Either alone is not an attack.

        All steps accepted but no runtime violation means the sequence is
        harmless. A runtime violation with a step already rejected means PAAC
        caught it, which is the system working.
        """
        return self.all_steps_accepted and self.runtime_violated


@dataclass
class Result:
    """Outcome of one schema, with everything needed to reproduce it."""

    schema_id: str
    title: str
    outcome: SchemaOutcome
    witness: Witness | None = None
    confirmation: Confirmation | None = None
    boundary: str = ""
    note: str = ""
    hole_range: tuple[int, int] = (0, 0)

    def summary(self) -> str:
        head = f"Schema {self.schema_id} ({self.title}): {self.outcome.value.upper()}"
        if self.outcome is SchemaOutcome.WITNESS and self.witness:
            return f"{head}\n  holes: {self.witness.holes}\n  {self.witness.expected_violation}"
        if self.note:
            return f"{head}\n  {self.note}"
        return head


def load_axioms(path: str = "config/axioms.yaml") -> list[Axiom]:
    with open(path, encoding="utf-8") as fh:
        return AxiomParser.parse(fh.read())


def _applicable(axioms: list[Axiom], func_name: str) -> list[Axiom]:
    """Mirror the monitor's target_functions filter."""
    return [
        a
        for a in axioms
        if "*" in a.target_functions or func_name in a.target_functions
    ]


# ---------------------------------------------------------------------------
# Stage 1: propose
# ---------------------------------------------------------------------------


def synthesise(
    schema: Schema,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> tuple[SchemaOutcome, Witness | None, str]:
    """Ask Z3 for hole values satisfying *schema*'s decomposition condition.

    Returns (outcome, candidate, note). The candidate is unconfirmed.
    """
    if not schema.expressible:
        return SchemaOutcome.NOT_EXPRESSIBLE, None, schema.inexpressible_reason

    solver = z3.Solver()
    solver.set("timeout", timeout_ms)

    low, high = schema.hole_range
    holes = {name: z3.Int(name) for name in schema.hole_names}
    for var in holes.values():
        # Bounded so that UNSAT is a statement about a finite, stated space
        # rather than an unbounded claim the solver cannot actually discharge.
        solver.add(var >= low, var <= high)
    for constraint in schema.constraints(holes):
        solver.add(constraint)

    status = solver.check()

    if status == z3.unsat:
        return (
            SchemaOutcome.NO_WITNESS,
            None,
            f"No decomposition exists within schema {schema.id} for holes in "
            f"[{low}, {high}]. This is a bounded result for this schema only.",
        )
    if status == z3.unknown:
        return (
            SchemaOutcome.UNKNOWN,
            None,
            f"Solver returned unknown for schema {schema.id} at "
            f"timeout={timeout_ms}ms. Not rounded to a guarantee.",
        )

    model = solver.model()
    values = {name: model[var].as_long() for name, var in holes.items()}
    return SchemaOutcome.WITNESS, schema.build(values), ""


# ---------------------------------------------------------------------------
# Stage 2: confirm against the real system
# ---------------------------------------------------------------------------


def _split_functions(code: str) -> list[tuple[str, str]]:
    """Split SIL source into (function name, source text) pairs.

    Brace counting rather than the real parser, because the parser yields an AST
    and what is needed here is the original text, so the runtime sees exactly
    what was submitted. SIL has no strings, no comments, and no braces outside
    blocks, so counting is unambiguous for this input.
    """
    out: list[tuple[str, str]] = []
    idx = 0
    while True:
        start = code.find("func ", idx)
        if start == -1:
            return out
        paren = code.find("(", start)
        brace = code.find("{", start)
        if paren == -1 or brace == -1:
            return out

        name = code[start + len("func ") : paren].strip()

        depth = 0
        end = len(code) - 1
        for pos in range(brace, len(code)):
            if code[pos] == "{":
                depth += 1
            elif code[pos] == "}":
                depth -= 1
                if depth == 0:
                    end = pos
                    break
        out.append((name, code[start : end + 1]))
        idx = end + 1


def _instrument_with_axiom(code: str, condition: str) -> str:
    """Insert the axiom as a runtime assertion before the function's return.

    This is how the axiom becomes observable at runtime. PAAC's axioms are
    checked by the solver at verification time; SIL programs carry no runtime
    contract, so executing a violating program produces a wrong value silently
    rather than an error.

    Stated plainly because it matters for how the result should be read: the
    instrumented copy is used ONLY as the runtime oracle. The verifier is always
    given the uninstrumented code, exactly as the agent submitted it. The assert
    is the axiom expressed as an executable check, not an addition to the
    submission, and it is inserted after the program has already been accepted.
    """
    marker = "    return"
    idx = code.find(marker)
    if idx == -1:
        return code
    return code[:idx] + f"    assert {condition};\n" + code[idx:]


def confirm_witness(
    witness: Witness,
    axioms: list[Axiom] | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> Confirmation:
    """Run a candidate through the real verifier and the real runtime."""
    axioms = axioms if axioms is not None else load_axioms()
    checker = BoundedModelChecker()
    compiler = SILCompiler()

    axiom = next((a for a in axioms if a.id == witness.axiom_id), None)
    if axiom is None:
        raise PAACError(f"Witness names unknown axiom {witness.axiom_id!r}.")

    # --- Half one: is every modification individually accepted? --------------
    steps: list[StepCheck] = []
    for mod in witness.modifications:
        try:
            ast, _ = compiler.compile(mod.code)
        except SILError as exc:
            steps.append(StepCheck(mod.func_name, False, f"did not compile: {exc}"))
            continue

        applicable = _applicable(axioms, mod.func_name)
        try:
            safe, counterexample = checker.verify(
                ast, applicable, timeout_ms=timeout_ms, pre_cond=mod.pre_cond
            )
        except PAACError as exc:
            steps.append(StepCheck(mod.func_name, False, f"verifier refused: {exc}"))
            continue

        steps.append(
            StepCheck(
                mod.func_name,
                safe,
                "accepted"
                if safe
                else f"rejected, counterexample: {counterexample}",
            )
        )

    all_accepted = bool(steps) and all(s.accepted for s in steps)

    # --- Half two: does the composed program violate the axiom at runtime? ---
    # The axiom is inserted into every function it targets, so the violation is
    # detected wherever it occurs in the call chain rather than only at the
    # entry point. Reachability through the entry point is the property being
    # demonstrated: it shows the composed program can be driven into a
    # violating state by a caller PAAC accepted.
    # Rebuild the program the way CodeMonitor._live_registry ends up holding it:
    # keyed by function name, later definitions replacing earlier ones.
    #
    # This has to work per function *definition*, not per modification, because
    # a modification may carry several functions. A caller must co-submit its
    # callee, since the SIL compiler rejects calls to undefined functions, so
    # naive concatenation yields "Duplicate function". Keeping the latest
    # definition of each name is also what makes schema C observable: the entire
    # attack is that a later modification silently replaces the version an
    # earlier one was verified against.
    latest: dict[str, str] = {}
    order: list[str] = []
    for mod in witness.modifications:
        text = mod.code.strip()
        for name, body in _split_functions(text) or [(mod.func_name, text)]:
            instrumented = (
                _instrument_with_axiom(body, axiom.condition)
                if ("*" in axiom.target_functions or name in axiom.target_functions)
                else body
            )
            if name not in latest:
                order.append(name)
            latest[name] = instrumented
    program_text = "\n\n".join(latest[name] for name in order) + "\n"

    try:
        composed_ast, _ = compiler.compile(program_text)
    except SILError as exc:
        return Confirmation(
            all_accepted, steps, False, f"instrumented program did not compile: {exc}"
        )

    runtime = SILRuntime(composed_ast)
    try:
        value = runtime.execute(witness.entry, list(witness.entry_args))
    except SILRuntimeError as exc:
        if "Assertion failed" in str(exc):
            return Confirmation(
                all_accepted,
                steps,
                True,
                f"axiom {axiom.id} ({axiom.condition}) violated at runtime while "
                f"executing {witness.entry}({', '.join(map(str, witness.entry_args))})",
            )
        return Confirmation(all_accepted, steps, False, f"runtime error: {exc}")

    return Confirmation(
        all_accepted,
        steps,
        False,
        f"{witness.entry} returned {value} without violating {axiom.id}",
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def synthesise_all(
    schemas: list[Schema] | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    axioms: list[Axiom] | None = None,
) -> list[Result]:
    """Run every schema and confirm every candidate. Reproducible end to end."""
    schemas = schemas if schemas is not None else SCHEMAS
    axioms = axioms if axioms is not None else load_axioms()
    results: list[Result] = []

    for schema in schemas:
        outcome, candidate, note = synthesise(schema, timeout_ms=timeout_ms)
        result = Result(
            schema_id=schema.id,
            title=schema.title,
            outcome=outcome,
            witness=candidate,
            boundary=schema.boundary,
            note=note,
            hole_range=schema.hole_range,
        )

        if candidate is not None:
            confirmation = confirm_witness(candidate, axioms, timeout_ms=timeout_ms)
            result.confirmation = confirmation

            if confirmation.confirmed:
                pass  # WITNESS, as proposed.
            elif confirmation.runtime_violated:
                # The composition really is unsafe and PAAC refused a step. That
                # is the system working, and it is reported as such rather than
                # being lumped in with a bad schema.
                rejected = [s for s in confirmation.steps if not s.accepted]
                result.outcome = SchemaOutcome.DEFENDED
                result.note = (
                    "The composition violates the axiom, and PAAC rejected "
                    + ", ".join(f"{s.func_name} ({s.detail})" for s in rejected)
                    + ". The attack is real; this configuration stops it."
                )
            else:
                result.outcome = SchemaOutcome.SPURIOUS
                result.note = (
                    "Z3 proposed a candidate whose composition does not "
                    f"actually violate the axiom, so the schema's arithmetic is "
                    f"wrong. Runtime: {confirmation.runtime_detail}"
                )

        logger.info(result.summary())
        results.append(result)

    return results
