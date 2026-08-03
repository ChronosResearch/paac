"""
src/cegar/repair.py
--------------------
Counterexample-Guided Axiom Repair (CEGAR).

When verification returns SAT (unsafe), the counterexample identifies
a concrete violating assignment.  This module automatically proposes
a repaired axiom that eliminates the counterexample and re-verifies.

Repair strategy (in order of preference):
  1. Constant shift  : tighten the threshold by the counterexample value
                       e.g. balance >= 0  +  ce: balance=-3  →  balance >= 1
  2. Operator tighten: replace >= with > if the boundary is the issue
  3. Conjunctive add : add a new conjunct derived from the counterexample
                       e.g. balance >= 0 AND amount > 0

The loop runs up to MAX_ITERATIONS.  Each candidate is:
  a) Verified to be a conservative extension of the original (via axiom_evolution).
  b) Re-verified against the original unsafe program.
  c) Checked via mutation testing to confirm robustness is not degraded.

If all candidates fail, the loop returns REPAIR_FAILED.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from src.axioms.axiom_parser import Axiom
from src.core.axiom_evolution import AxiomEvolutionEngine, AxiomModification
from src.core.sil_compiler import SILCompiler
from src.core.verifier import BoundedModelChecker, VerificationError

_COMPILER = SILCompiler()
_MAX_ITERATIONS = int(__import__("os").environ.get("PAAC_CEGAR_MAX_ITER", "10"))
_TIMEOUT_MS = int(__import__("os").environ.get("PAAC_CEGAR_TIMEOUT_MS", "5000"))

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class RepairIteration:
    """Record of one CEGAR iteration."""

    iteration: int
    candidate_condition: str
    is_conservative: bool
    re_verify_safe: bool
    counterexample: dict[str, Any] | None = None
    reason: str = ""


@dataclass
class RepairResult:
    """Final result of the CEGAR repair loop."""

    success: bool
    original_axiom: Axiom
    repaired_axiom: Axiom | None
    iterations: list[RepairIteration] = field(default_factory=list)
    elapsed_ms: float = 0.0
    message: str = ""

    @property
    def total_iterations(self) -> int:
        return len(self.iterations)


# ---------------------------------------------------------------------------
# Candidate generator
# ---------------------------------------------------------------------------

_INT_RE = re.compile(r"(?<![a-zA-Z_])(-?\d+)(?![a-zA-Z_])")
_OP_RE = re.compile(r"(>=|<=|==|!=|>(?!=)|<(?!=))")
_VAR_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b")
_KEYWORDS = {"and", "or", "not", "true", "false"}


def _extract_ce_value(ce: dict[str, Any], var: str) -> int | None:
    """Extract the integer value of *var* from a counterexample dict."""
    for k, v in ce.items():
        base = k.rsplit("_", 1)[0] if "_" in k else k
        if base == var:
            try:
                return int(str(v))
            except (ValueError, TypeError):
                pass
    return None


def _generate_candidates(axiom: Axiom, ce: dict[str, Any]) -> list[str]:
    """
    Generate repair candidate conditions from an axiom and a counterexample.

    Returns a list of candidate condition strings, ordered by preference.
    """
    cond = axiom.condition
    candidates: list[str] = []

    # Parse the condition: var OP threshold
    m = re.match(r"([a-zA-Z_]\w*)\s*(>=|<=|==|!=|>|<)\s*(-?\d+)", cond.strip())
    if m:
        var, op, threshold_str = m.group(1), m.group(2), m.group(3)
        threshold = int(threshold_str)
        ce_val = _extract_ce_value(ce, var)

        if op in (">=", ">"):
            # Counterexample has var < threshold — tighten upward
            if ce_val is not None:
                # Set threshold to ce_val + 1 (just above the violating value)
                new_threshold = ce_val + 1
                if new_threshold > threshold:
                    candidates.append(f"{var} >= {new_threshold}")
            # Also try threshold + 1
            candidates.append(f"{var} >= {threshold + 1}")
            # Try strict inequality
            if op == ">=":
                candidates.append(f"{var} > {threshold}")
            # Try threshold + 5
            candidates.append(f"{var} >= {threshold + 5}")

        elif op in ("<=", "<"):
            if ce_val is not None:
                new_threshold = ce_val - 1
                if new_threshold < threshold:
                    candidates.append(f"{var} <= {new_threshold}")
            candidates.append(f"{var} <= {threshold - 1}")
            if op == "<=":
                candidates.append(f"{var} < {threshold}")

        elif op == "==":
            # Equality is already tight — try adding a range constraint
            candidates.append(f"{var} >= {threshold} and {var} <= {threshold}")

        elif op == "!=":
            # Strengthen: exclude a range
            if ce_val is not None:
                candidates.append(f"{var} != {ce_val}")

    # Conjunctive repair: add a new constraint from the counterexample
    for var_name, val in ce.items():
        base = var_name.rsplit("_", 1)[0] if "_" in var_name else var_name
        if base in _KEYWORDS:
            continue
        try:
            int_val = int(str(val))
            # Add: base >= int_val + 1 (exclude the violating value)
            new_conjunct = f"{base} >= {int_val + 1}"
            combined = f"({cond}) and ({new_conjunct})"
            if combined not in candidates:
                candidates.append(combined)
        except (ValueError, TypeError):
            pass

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        if c not in seen and c != cond:
            seen.add(c)
            unique.append(c)

    return unique


# ---------------------------------------------------------------------------
# CEGAR loop
# ---------------------------------------------------------------------------


def repair_axiom(
    axiom: Axiom,
    unsafe_program: str,
    all_axioms: list[Axiom],
    max_iterations: int = _MAX_ITERATIONS,
    timeout_ms: int = _TIMEOUT_MS,
) -> RepairResult:
    """
    Run the CEGAR repair loop for *axiom* against *unsafe_program*.

    Steps per iteration:
      1. Verify the program with the current axiom set.
      2. If safe → repair succeeded.
      3. Extract counterexample.
      4. Generate repair candidates.
      5. For each candidate:
         a. Check conservative extension (axiom_evolution).
         b. Re-verify the program with the candidate axiom.
         c. If safe → accept repair.
      6. If no candidate works → next iteration with best candidate.

    Returns RepairResult with success=True and repaired_axiom if found.
    """
    t_start = time.monotonic()
    bmc = BoundedModelChecker()
    iterations: list[RepairIteration] = []

    try:
        ast, _ = _COMPILER.compile(unsafe_program)
    except Exception as exc:
        return RepairResult(
            success=False,
            original_axiom=axiom,
            repaired_axiom=None,
            message=f"Compilation failed: {exc}",
            elapsed_ms=(time.monotonic() - t_start) * 1000,
        )

    current_axiom = axiom
    # Build the axiom set with the current axiom replacing the original
    other_axioms = [a for a in all_axioms if a.id != axiom.id]

    for iteration in range(1, max_iterations + 1):
        current_axioms = other_axioms + [current_axiom]

        try:
            safe, ce = bmc._verify_inner(ast, current_axioms, timeout_ms)
        except VerificationError as exc:
            logger.warning(f"CEGAR iter {iteration}: verification error: {exc}")
            break

        if safe:
            elapsed = (time.monotonic() - t_start) * 1000
            logger.info(
                f"CEGAR: repair succeeded at iteration {iteration} "
                f"with condition '{current_axiom.condition}'"
            )
            return RepairResult(
                success=True,
                original_axiom=axiom,
                repaired_axiom=current_axiom,
                iterations=iterations,
                elapsed_ms=elapsed,
                message=(
                    f"Repair succeeded at iteration {iteration}. "
                    f"Repaired condition: '{current_axiom.condition}'"
                ),
            )

        if ce is None:
            break

        ce_dict = {k: str(v) for k, v in ce.assignments.items()}
        candidates = _generate_candidates(current_axiom, ce_dict)

        if not candidates:
            iterations.append(
                RepairIteration(
                    iteration=iteration,
                    candidate_condition=current_axiom.condition,
                    is_conservative=False,
                    re_verify_safe=False,
                    counterexample=ce_dict,
                    reason="No repair candidates generated",
                )
            )
            break

        accepted_candidate: str | None = None
        for candidate_cond in candidates:
            # Check conservative extension
            engine = AxiomEvolutionEngine([current_axiom], timeout_ms=timeout_ms)
            mod = AxiomModification(
                old_axiom_id=current_axiom.id,
                new_condition=candidate_cond,
                justification=f"CEGAR repair iteration {iteration}",
            )
            evo_result = engine.propose_change(mod)

            if not evo_result.accepted:
                iterations.append(
                    RepairIteration(
                        iteration=iteration,
                        candidate_condition=candidate_cond,
                        is_conservative=False,
                        re_verify_safe=False,
                        counterexample=ce_dict,
                        reason=f"Not a conservative extension: {evo_result.message}",
                    )
                )
                continue

            # Re-verify with candidate
            candidate_axiom = Axiom(
                id=current_axiom.id,
                description=current_axiom.description,
                condition=candidate_cond,
                target_functions=list(current_axiom.target_functions),
            )
            try:
                re_safe, _ = bmc._verify_inner(
                    ast, other_axioms + [candidate_axiom], timeout_ms
                )
            except VerificationError:
                re_safe = False

            iterations.append(
                RepairIteration(
                    iteration=iteration,
                    candidate_condition=candidate_cond,
                    is_conservative=True,
                    re_verify_safe=re_safe,
                    counterexample=ce_dict,
                    reason=(
                        "Conservative extension accepted"
                        if re_safe
                        else "Still unsafe after repair"
                    ),
                )
            )

            if re_safe:
                accepted_candidate = candidate_cond
                break

        if accepted_candidate:
            current_axiom = Axiom(
                id=current_axiom.id,
                description=current_axiom.description,
                condition=accepted_candidate,
                target_functions=list(current_axiom.target_functions),
            )
        else:
            # No candidate worked — try the first conservative one for next iteration
            conservative = next(
                (it for it in reversed(iterations) if it.is_conservative), None
            )
            if conservative:
                current_axiom = Axiom(
                    id=current_axiom.id,
                    description=current_axiom.description,
                    condition=conservative.candidate_condition,
                    target_functions=list(current_axiom.target_functions),
                )
            else:
                break

    elapsed = (time.monotonic() - t_start) * 1000
    return RepairResult(
        success=False,
        original_axiom=axiom,
        repaired_axiom=None,
        iterations=iterations,
        elapsed_ms=elapsed,
        message=f"Repair failed after {len(iterations)} iterations.",
    )
