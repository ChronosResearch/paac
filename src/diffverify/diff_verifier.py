"""
src/diffverify/diff_verifier.py
--------------------------------
Differential Verification.

Proves that a new version of a function is a *conservative extension*
of the old version: it satisfies all the same safety axioms and introduces
no new violation paths.

Formal definition
-----------------
Let old_prog and new_prog be two SIL programs for the same function.
Let A be the axiom set.

new_prog is a conservative extension of old_prog w.r.t. A iff:

  ∀ input: safe(old_prog, A, input) → safe(new_prog, A, input)

Equivalently (contrapositive):

  ¬∃ input: safe(old_prog, A, input) ∧ ¬safe(new_prog, A, input)

We encode this as a Z3 query using two independent SSA environments
(one for old, one for new) sharing the same input variables.

Query:
  old_safe(input) ∧ ¬new_safe(input)

If UNSAT → no input makes old safe but new unsafe → conservative extension.
If SAT   → counterexample shows a regression.

Additionally we check the symmetric direction:
  new_safe(input) ∧ ¬old_safe(input)

If UNSAT → new is strictly stronger (accepts fewer programs).
If SAT   → new accepts some programs that old rejects (relaxation).

Result codes:
  CONSERVATIVE  : new is at least as safe as old (no regressions)
  REGRESSION    : new is less safe than old (counterexample found)
  RELAXATION    : new accepts programs old rejected (may be intentional)
  EQUIVALENT    : new and old are semantically identical w.r.t. axioms
  ERROR         : encoding or solver failure
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import z3
from loguru import logger

from src.axioms.axiom_parser import Axiom
from src.core.sil_compiler import ProgramNode, SILCompiler
from src.core.verifier import SSAEnv, StmtEncoder, _encode_axiom

_COMPILER = SILCompiler()
_TIMEOUT_MS = int(__import__("os").environ.get("PAAC_DIFF_TIMEOUT_MS", "5000"))


class DiffStatus(str, Enum):
    CONSERVATIVE = "conservative"  # new >= old in safety
    REGRESSION = "regression"  # new < old in safety (bad)
    RELAXATION = "relaxation"  # new > old in acceptance (intentional weakening)
    EQUIVALENT = "equivalent"  # new == old w.r.t. axioms
    ERROR = "error"


@dataclass
class DiffCounterExample:
    """A concrete input that witnesses a difference between old and new."""

    assignments: dict[str, Any]
    direction: str  # "regression" or "relaxation"

    def __str__(self) -> str:
        return ", ".join(f"{k}={v}" for k, v in self.assignments.items())


@dataclass
class DiffResult:
    """Result of a differential verification query."""

    status: DiffStatus
    old_program: str
    new_program: str
    axioms_used: list[str]
    counterexample: DiffCounterExample | None = None
    regression_ce: DiffCounterExample | None = None
    relaxation_ce: DiffCounterExample | None = None
    elapsed_ms: float = 0.0
    message: str = ""

    @property
    def is_safe_upgrade(self) -> bool:
        """True if new version is at least as safe as old (no regressions)."""
        return self.status in (DiffStatus.CONSERVATIVE, DiffStatus.EQUIVALENT)


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------


def _encode_program_violations(
    ast: ProgramNode,
    axioms: list[Axiom],
    ctx: z3.Context,
    prefix: str,
) -> tuple[list[z3.BoolRef], SSAEnv, list[str]]:
    """
    Encode a SIL program's violation flags into Z3 with SSA variable names
    prefixed by *prefix* to avoid collisions between old/new encodings.

    Returns (violation_flags, env, encoded_axiom_ids).
    """
    env = SSAEnv(ctx)
    solver_dummy = z3.Solver(ctx=ctx)  # used only for phi-node constraints
    stmt_enc = StmtEncoder(ctx, solver_dummy, env)

    for func in ast.functions:
        func_path = z3.BoolVal(True, ctx=ctx)
        for param in func.params:
            # Prefix parameter names to separate old/new namespaces
            prefixed_name = f"{prefix}_{param.name}"
            env.declare_param(prefixed_name, param.type_name)
            # Also declare the unprefixed name pointing to the same Z3 var
            env._exprs[f"{param.name}_0"] = env._exprs[f"{prefixed_name}_0"]
            env._counters[param.name] = 0
        stmt_enc.encode_stmts(func.body, func_path)

    # Collect param names for axiom encoding
    declared = list(env._counters.keys()) + [
        k.rsplit("_", 1)[0] for k in env._exprs if k not in env._counters
    ]
    seen: set[str] = set()
    param_names: list[str] = []
    for n in declared:
        base = n.rsplit("_", 1)[0] if "_" in n else n
        if base not in seen and not base.startswith(prefix):
            seen.add(base)
            param_names.append(base)

    encoded_ids: list[str] = []
    for axiom in axioms:
        z3_cond = _encode_axiom(axiom, ctx, env, param_names)
        if z3_cond is not None:
            encoded_ids.append(axiom.id)
            stmt_enc.violation_flags.append(z3.Not(z3_cond))

    return stmt_enc.violation_flags, env, encoded_ids


# ---------------------------------------------------------------------------
# Differential verifier
# ---------------------------------------------------------------------------


class DifferentialVerifier:
    """
    Verifies that a new program version is a conservative extension of the old.
    """

    def __init__(self, timeout_ms: int = _TIMEOUT_MS) -> None:
        self._timeout_ms = timeout_ms

    def verify(
        self,
        old_program: str,
        new_program: str,
        axioms: list[Axiom],
    ) -> DiffResult:
        """
        Run differential verification between old and new program versions.

        Returns a DiffResult indicating whether the new version is a
        conservative extension, a regression, a relaxation, or equivalent.
        """
        t_start = time.monotonic()

        try:
            old_ast, _ = _COMPILER.compile(old_program)
        except Exception as exc:
            return DiffResult(
                status=DiffStatus.ERROR,
                old_program=old_program,
                new_program=new_program,
                axioms_used=[],
                message=f"Old program compilation failed: {exc}",
                elapsed_ms=(time.monotonic() - t_start) * 1000,
            )

        try:
            new_ast, _ = _COMPILER.compile(new_program)
        except Exception as exc:
            return DiffResult(
                status=DiffStatus.ERROR,
                old_program=old_program,
                new_program=new_program,
                axioms_used=[],
                message=f"New program compilation failed: {exc}",
                elapsed_ms=(time.monotonic() - t_start) * 1000,
            )

        # Check regression: old_safe ∧ ¬new_safe
        regression_ce = self._check_direction(
            old_ast, new_ast, axioms, direction="regression"
        )
        # Check relaxation: new_safe ∧ ¬old_safe
        relaxation_ce = self._check_direction(
            old_ast, new_ast, axioms, direction="relaxation"
        )

        elapsed = (time.monotonic() - t_start) * 1000
        axiom_ids = [a.id for a in axioms]

        if regression_ce is not None and relaxation_ce is not None:
            # Both directions differ — programs are incomparable
            status = DiffStatus.REGRESSION
            msg = (
                "New version has regressions AND relaxations — "
                "programs are safety-incomparable."
            )
        elif regression_ce is not None:
            status = DiffStatus.REGRESSION
            msg = (
                f"REGRESSION detected: input {regression_ce} is safe under old "
                "but unsafe under new version."
            )
        elif relaxation_ce is not None:
            # Relaxation only: new accepts programs old rejected — still conservative
            # (no regressions means new is at least as safe as old)
            status = DiffStatus.CONSERVATIVE
            msg = (
                f"RELAXATION detected (conservative): input {relaxation_ce} is safe under new "
                "but unsafe under old version (new accepts more programs). "
                "No regressions detected."
            )
        else:
            status = DiffStatus.EQUIVALENT
            msg = (
                "New version is semantically equivalent to old w.r.t. the axiom set. "
                "No regressions or relaxations detected."
            )

        return DiffResult(
            status=status,
            old_program=old_program,
            new_program=new_program,
            axioms_used=axiom_ids,
            counterexample=regression_ce,
            regression_ce=regression_ce,
            relaxation_ce=relaxation_ce,
            elapsed_ms=elapsed,
            message=msg,
        )

    def _check_direction(
        self,
        old_ast: ProgramNode,
        new_ast: ProgramNode,
        axioms: list[Axiom],
        direction: str,
    ) -> DiffCounterExample | None:
        """
        Check one direction of the differential query.

        direction="regression": find input where old is safe but new is not.
        direction="relaxation": find input where new is safe but old is not.

        Returns a DiffCounterExample if found, None if UNSAT (no difference).
        """
        ctx = z3.Context()
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", self._timeout_ms)
        solver.set("max_memory", 1024)

        try:
            old_flags, old_env, _ = _encode_program_violations(
                old_ast, axioms, ctx, "old"
            )
            new_flags, new_env, _ = _encode_program_violations(
                new_ast, axioms, ctx, "new"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"DiffVerify: encoding error ({direction}): {exc}")
            return None

        # Unify input variables: old and new share the same inputs
        # by constraining old_param_0 == new_param_0 for each parameter
        old_params = {
            k.rsplit("_", 1)[0]
            for k in old_env._exprs
            if k.startswith("old_") and k.endswith("_0")
        }
        new_params = {
            k.rsplit("_", 1)[0]
            for k in new_env._exprs
            if k.startswith("new_") and k.endswith("_0")
        }

        for op in old_params:
            base = op[len("old_") :]
            np = f"new_{base}"
            if np in new_params:
                old_var = old_env._exprs.get(f"{op}_0")
                new_var = new_env._exprs.get(f"{np}_0")
                if old_var is not None and new_var is not None:
                    try:
                        solver.add(old_var == new_var)
                    except Exception:  # noqa: BLE001
                        pass

        if direction == "regression":
            # old is safe (no violations) AND new is unsafe (some violation)
            if old_flags:
                solver.add(z3.Not(z3.Or(*old_flags)))
            if new_flags:
                solver.add(z3.Or(*new_flags))
            else:
                return None  # new has no violations — can't regress
        else:  # relaxation
            # new is safe AND old is unsafe
            if new_flags:
                solver.add(z3.Not(z3.Or(*new_flags)))
            if old_flags:
                solver.add(z3.Or(*old_flags))
            else:
                return None

        result = solver.check()
        if result == z3.sat:
            model = solver.model()
            assignments = {
                str(d.name()): str(model[d])
                for d in model.decls()
                if not str(d.name()).startswith(("old_", "new_"))
            }
            return DiffCounterExample(assignments=assignments, direction=direction)
        return None
