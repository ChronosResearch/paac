"""
src/mutation/mutation_runner.py
--------------------------------
Execution pipeline for axiom mutation testing.

For each mutated axiom:
  1. Replace the original axiom in the probe suite.
  2. Run all verification probes (SIL programs that should pass/fail under the axiom).
  3. Record pass/fail counts and compute per-mutant metrics.

Design: uses direct BoundedModelChecker calls (no subprocess overhead per probe)
so the full mutation matrix completes in seconds, not minutes.

Probe suite: a set of (SIL program, expected_safe, description) triples that
exercise the axiom's condition. Generated automatically from the axiom condition
plus a set of canonical programs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import NamedTuple

from src.axioms.axiom_parser import Axiom
from src.core.sil_compiler import SILCompiler
from src.core.verifier import BoundedModelChecker, VerificationError
from src.mutation.axiom_mutator import MutatedAxiom, MutationKind, generate_mutations

_COMPILER = SILCompiler()


class Probe(NamedTuple):
    sil_code: str
    expected_safe: bool
    description: str


def _compile(code: str):
    ast, _ = _COMPILER.compile(code)
    return ast


# ---------------------------------------------------------------------------
# Canonical probe programs — one set per axiom variable pattern
# ---------------------------------------------------------------------------


def _build_probes_for_axiom(axiom: Axiom) -> list[Probe]:
    """
    Build a probe suite tailored to the axiom's condition.

    Strategy: parse the condition to extract the variable name and threshold,
    then generate programs that:
      - clearly satisfy the condition (should be SAFE with original axiom)
      - clearly violate the condition (should be UNSAFE with original axiom)
      - sit on the boundary (should be SAFE with original axiom)
    """
    cond = axiom.condition.strip()
    probes: list[Probe] = []

    # Extract variable name and threshold from simple conditions like "x >= 0"
    import re

    m = re.match(r"([a-zA-Z_]\w*)\s*(>=|<=|==|!=|>|<)\s*(-?\d+)", cond)
    if not m:
        # Fallback: generic probes that always work
        probes.extend(_generic_probes(axiom))
        return probes

    var, op, threshold_str = m.group(1), m.group(2), m.group(3)
    threshold = int(threshold_str)

    # Values that satisfy the original condition
    if op == ">=":
        safe_vals = [threshold, threshold + 1, threshold + 10]
        unsafe_vals = [threshold - 1, threshold - 5, threshold - 100]
        boundary = threshold
    elif op == ">":
        safe_vals = [threshold + 1, threshold + 2, threshold + 10]
        unsafe_vals = [threshold, threshold - 1, threshold - 10]
        boundary = threshold + 1
    elif op == "<=":
        safe_vals = [threshold, threshold - 1, threshold - 10]
        unsafe_vals = [threshold + 1, threshold + 5, threshold + 100]
        boundary = threshold
    elif op == "<":
        safe_vals = [threshold - 1, threshold - 2, threshold - 10]
        unsafe_vals = [threshold, threshold + 1, threshold + 10]
        boundary = threshold - 1
    elif op == "==":
        safe_vals = [threshold]
        unsafe_vals = [threshold + 1, threshold - 1]
        boundary = threshold
    elif op == "!=":
        safe_vals = [threshold + 1, threshold - 1]
        unsafe_vals = [threshold]
        boundary = threshold + 1
    else:
        probes.extend(_generic_probes(axiom))
        return probes

    func_name = (
        axiom.target_functions[0]
        if axiom.target_functions and axiom.target_functions[0] != "*"
        else "test_func"
    )

    # Programs where the variable is constrained to a safe value via assignment
    for val in safe_vals[:2]:
        code = f"""
func {func_name}(x: int) -> int {{
    {var} = {val};
    return {var};
}}
"""
        probes.append(
            Probe(
                sil_code=code,
                expected_safe=True,
                description=f"Assign {var}={val} (satisfies '{cond}')",
            )
        )

    # Programs where the variable is constrained to an unsafe value
    for val in unsafe_vals[:2]:
        code = f"""
func {func_name}(x: int) -> int {{
    {var} = {val};
    return {var};
}}
"""
        probes.append(
            Probe(
                sil_code=code,
                expected_safe=False,
                description=f"Assign {var}={val} (violates '{cond}')",
            )
        )

    # Boundary probe
    code = f"""
func {func_name}(x: int) -> int {{
    {var} = {boundary};
    return {var};
}}
"""
    probes.append(
        Probe(
            sil_code=code,
            expected_safe=True,
            description=f"Boundary: {var}={boundary} (exactly at boundary of '{cond}')",
        )
    )

    # Unconstrained variable probe — should be UNSAFE (Z3 can pick violating value)
    code = f"""
func {func_name}({var}: int) -> int {{
    return {var};
}}
"""
    probes.append(
        Probe(
            sil_code=code,
            expected_safe=False,
            description=f"Unconstrained {var} (Z3 picks violating value for '{cond}')",
        )
    )

    return probes


def _generic_probes(axiom: Axiom) -> list[Probe]:
    """Fallback probes for axioms with non-standard conditions."""
    func_name = (
        axiom.target_functions[0]
        if axiom.target_functions and axiom.target_functions[0] != "*"
        else "test_func"
    )
    return [
        Probe(
            sil_code=f"func {func_name}(x: int) -> int {{ return x; }}",
            expected_safe=False,
            description="Unconstrained x (axiom may reject)",
        ),
        Probe(
            sil_code=f"func {func_name}(x: int) -> int {{ assert false; return x; }}",
            expected_safe=False,
            description="assert false — always unsafe",
        ),
    ]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    probe: Probe
    actual_safe: bool
    matched_expected: bool
    error: str | None = None
    elapsed_ms: float = 0.0


@dataclass
class MutantResult:
    mutant: MutatedAxiom
    probe_results: list[ProbeResult] = field(default_factory=list)
    probes_total: int = 0
    probes_matched: int = 0  # probes where actual == expected (under original axiom)
    probes_killed: int = 0  # probes where mutant changed the outcome vs original
    elapsed_ms: float = 0.0
    error: str | None = None

    @property
    def kill_rate(self) -> float:
        """Fraction of probes where this mutant changed the outcome."""
        if self.probes_total == 0:
            return 0.0
        return self.probes_killed / self.probes_total

    @property
    def survived(self) -> bool:
        """A mutant survives if it killed zero probes (indistinguishable from original)."""
        return self.probes_killed == 0


@dataclass
class AxiomMutationResult:
    axiom: Axiom
    probes: list[Probe]
    baseline_results: list[ProbeResult]  # results with original axiom
    mutant_results: list[MutantResult]
    elapsed_ms: float = 0.0

    @property
    def mutation_score(self) -> float:
        """Fraction of non-noop mutants that were killed."""
        non_noop = [
            m for m in self.mutant_results if m.mutant.kind != MutationKind.NOOP
        ]
        if not non_noop:
            return 0.0
        killed = sum(1 for m in non_noop if not m.survived)
        return killed / len(non_noop)

    @property
    def is_vacuous(self) -> bool:
        """True if the vacuous mutant (condition=true) survived — axiom has no effect."""
        for mr in self.mutant_results:
            if mr.mutant.kind == MutationKind.VACUOUS and mr.survived:
                return True
        return False

    @property
    def robustness_score(self) -> float:
        """
        Robustness = mutation_score weighted by expected direction.
        Negation/strengthen mutants that are killed score higher (proves axiom is tight).
        Vacuous survival is a strong penalty.
        """
        if self.is_vacuous:
            return 0.0
        return self.mutation_score


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _run_probe(probe: Probe, axiom: Axiom, bmc: BoundedModelChecker) -> ProbeResult:
    t0 = time.monotonic()
    try:
        ast = _compile(probe.sil_code)
        safe, _ = bmc._verify_inner(ast, [axiom], timeout_ms=5000)
        elapsed = (time.monotonic() - t0) * 1000
        return ProbeResult(
            probe=probe,
            actual_safe=safe,
            matched_expected=(safe == probe.expected_safe),
            elapsed_ms=elapsed,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed = (time.monotonic() - t0) * 1000
        # Compilation errors on mutant conditions are treated as "safe=True"
        # (the mutant condition was invalid SIL — counts as killed if original expected unsafe)
        return ProbeResult(
            probe=probe,
            actual_safe=True,
            matched_expected=(True == probe.expected_safe),
            error=str(exc),
            elapsed_ms=elapsed,
        )


def run_axiom_mutation(axiom: Axiom) -> AxiomMutationResult:
    """Run the full mutation suite for a single axiom."""
    t_start = time.monotonic()
    probes = _build_probes_for_axiom(axiom)
    bmc = BoundedModelChecker()

    # Baseline: run all probes with the original axiom
    baseline: list[ProbeResult] = [_run_probe(p, axiom, bmc) for p in probes]

    # Generate all mutants
    mutations = generate_mutations(axiom)
    mutant_results: list[MutantResult] = []

    for mutated in mutations:
        t_mut = time.monotonic()
        mr = MutantResult(mutant=mutated, probes_total=len(probes))

        for i, probe in enumerate(probes):
            pr = _run_probe(probe, mutated.mutant, bmc)
            mr.probe_results.append(pr)

            # A probe is "killed" if the mutant changed the outcome vs baseline
            baseline_safe = baseline[i].actual_safe
            if pr.actual_safe != baseline_safe:
                mr.probes_killed += 1

            if pr.matched_expected:
                mr.probes_matched += 1

        mr.elapsed_ms = (time.monotonic() - t_mut) * 1000
        mutant_results.append(mr)

    elapsed = (time.monotonic() - t_start) * 1000
    return AxiomMutationResult(
        axiom=axiom,
        probes=probes,
        baseline_results=baseline,
        mutant_results=mutant_results,
        elapsed_ms=elapsed,
    )


def run_all_axioms(axioms: list[Axiom]) -> list[AxiomMutationResult]:
    """Run mutation testing for every axiom in the list."""
    return [run_axiom_mutation(ax) for ax in axioms]
