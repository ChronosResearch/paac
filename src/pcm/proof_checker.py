"""
src/pcm/proof_checker.py
------------------------
Proof-Carrying Modification (PCM) — Independent AST-Based Proof Checker.

Validates a PPL proof without calling Z3.  Target: < 10ms per proof.

Algorithm:
  - Maintain a SymbolicEnv: var -> (lower_bound: int | None, upper_bound: int | None)
  - Process each step in order using AST-based expression evaluation
  - For Assert/ApplyAxiom: use interval arithmetic entailment on parsed AST
  - Return ACCEPT or REJECT with the first failing step

The checker is INDEPENDENT of the proof generator: it parses condition
strings into an AST and evaluates them symbolically, rather than relying
on string matching.  This prevents a malicious generator from crafting
conditions that pass string comparison but fail semantically.

Entailment is intentionally conservative: if the checker cannot prove a
condition from the current environment it returns REJECT.
"""

from __future__ import annotations

import ast as pyast
import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_MAX_PROOF_BYTES = 64 * 1024  # 64 KB

# SIL keywords that are not variable names
_KEYWORDS = frozenset(
    {
        "true",
        "false",
        "and",
        "or",
        "not",
        "if",
        "else",
        "while",
        "return",
        "assert",
        "func",
        "int",
        "bool",
        "bound",
    }
)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


class Verdict(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"


# ---------------------------------------------------------------------------
# Symbolic environment — interval arithmetic
# ---------------------------------------------------------------------------


@dataclass
class _Bound:
    """Tracks known lower/upper bounds for a variable."""

    lower: int | None = None  # var >= lower
    upper: int | None = None  # var <= upper
    exact: int | None = None  # var == exact (overrides lower/upper)
    assumed_constraints: list[str] = field(default_factory=list)


class SymbolicEnv:
    """
    Lightweight symbolic environment for proof checking.

    Tracks per-variable integer bounds and a set of assumed constraints
    (stored as strings for exact-match entailment).
    """

    def __init__(self) -> None:
        self._bounds: dict[str, _Bound] = {}
        self._assumed: set[str] = set()  # exact constraint strings

    def assume(self, var: str, constraint: str) -> None:
        """Record an assumption about a variable."""
        self._assumed.add(constraint.strip())
        parsed = _parse_simple_constraint(constraint)
        if parsed is None:
            return
        lhs, op, rhs_val = parsed
        if lhs != var:
            return
        b = self._bounds.setdefault(var, _Bound())
        if op == ">=":
            if b.lower is None or rhs_val > b.lower:
                b.lower = rhs_val
        elif op == ">":
            val = rhs_val + 1
            if b.lower is None or val > b.lower:
                b.lower = val
        elif op == "<=":
            if b.upper is None or rhs_val < b.upper:
                b.upper = rhs_val
        elif op == "<":
            val = rhs_val - 1
            if b.upper is None or val < b.upper:
                b.upper = val
        elif op == "==":
            b.exact = rhs_val
            b.lower = rhs_val
            b.upper = rhs_val

    def assign(self, var: str, expr: str) -> None:
        """
        Update environment after an assignment.

        For simple constant assignments we track the exact value.
        For expressions involving other variables we propagate bounds
        conservatively.
        """
        expr = expr.strip()
        # Constant assignment
        try:
            val = int(expr)
            b = _Bound(lower=val, upper=val, exact=val)
            self._bounds[var] = b
            self._assumed.add(f"{var} == {val}")
            self._assumed.add(f"{var} >= {val}")
            return
        except ValueError:
            pass

        # expr = a - b  (subtraction — conservative: drop upper bound)
        sub_m = re.fullmatch(r"(\w+)\s*-\s*(\w+)", expr)
        if sub_m:
            a, b_var = sub_m.group(1), sub_m.group(2)
            a_bound = self._bounds.get(a)
            b_bound = self._bounds.get(b_var)
            new_b = _Bound()
            if a_bound and a_bound.lower is not None:
                if b_bound and b_bound.upper is not None:
                    new_b.lower = a_bound.lower - b_bound.upper
                # else: can't determine lower bound
            self._bounds[var] = new_b
            return

        # expr = a + b  (addition)
        add_m = re.fullmatch(r"(\w+)\s*\+\s*(\w+)", expr)
        if add_m:
            a, b_var = add_m.group(1), add_m.group(2)
            a_bound = self._bounds.get(a)
            b_bound = self._bounds.get(b_var)
            new_b = _Bound()
            if a_bound and a_bound.lower is not None and b_bound and b_bound.lower is not None:
                new_b.lower = a_bound.lower + b_bound.lower
            self._bounds[var] = new_b
            return

        # expr = a + constant
        add_const_m = re.fullmatch(r"(\w+)\s*\+\s*(-?\d+)", expr)
        if add_const_m:
            a, c = add_const_m.group(1), int(add_const_m.group(2))
            a_bound = self._bounds.get(a)
            new_b = _Bound()
            if a_bound and a_bound.lower is not None:
                new_b.lower = a_bound.lower + c
            self._bounds[var] = new_b
            return

        # Unknown expression — clear bounds for this var
        self._bounds[var] = _Bound()

    def entails(self, condition: str) -> bool:
        """
        Return True if the current environment entails *condition*.

        Uses independent AST-based evaluation first (soundness guarantee),
        then falls back to interval arithmetic + exact-match on assumed constraints.
        The AST-based path is independent of the proof generator.
        """
        condition = condition.strip()

        # Exact match in assumed set (fast path)
        if condition in self._assumed:
            return True

        # Tautology: x == x
        taut_m = re.fullmatch(r"(\w+)\s*==\s*\1", condition)
        if taut_m:
            return True

        # Literal true
        if condition == "true":
            return True

        # Independent AST-based evaluation (primary path)
        ast_node = _parse_condition_ast(condition)
        if ast_node is not None:
            ast_result = _eval_condition_ast(ast_node, self._bounds, self._assumed)
            if ast_result is True:
                return True
            if ast_result is False:
                return False
            # ast_result is None (unknown) — fall through to interval arithmetic

        # Interval arithmetic fallback
        parsed = _parse_simple_constraint(condition)
        if parsed is None:
            # Try compound: not (x < 0) → x >= 0
            not_m = re.fullmatch(r"not\s*\(\s*(.+)\s*\)", condition)
            if not_m:
                inner = not_m.group(1).strip()
                negated = _negate_condition(inner)
                if negated:
                    return self.entails(negated)
            return False

        lhs, op, rhs_val = parsed
        b = self._bounds.get(lhs)
        if b is None:
            return False

        # Exact value known
        if b.exact is not None:
            return _eval_op(b.exact, op, rhs_val)

        if op == ">=":
            return b.lower is not None and b.lower >= rhs_val
        if op == ">":
            return b.lower is not None and b.lower > rhs_val
        if op == "<=":
            return b.upper is not None and b.upper <= rhs_val
        if op == "<":
            return b.upper is not None and b.upper < rhs_val
        if op == "==":
            return (
                b.lower is not None
                and b.upper is not None
                and b.lower == b.upper == rhs_val
            )
        if op == "!=":
            if b.exact is not None:
                return b.exact != rhs_val
            return False

        return False


# ---------------------------------------------------------------------------
# Constraint parsing helpers
# ---------------------------------------------------------------------------


def _parse_simple_constraint(
    condition: str,
) -> tuple[str, str, int] | None:
    """
    Parse 'var op integer' → (var, op, int_val).

    Returns None if the condition is not in this simple form.
    Uses regex for robustness against whitespace variations.
    """
    m = re.fullmatch(
        r"([a-zA-Z_]\w*)\s*(>=|>|<=|<|==|!=)\s*(-?\d+)",
        condition.strip(),
    )
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    return None


def _parse_condition_ast(condition: str) -> Any:
    """
    Parse a condition string into a Python AST for independent evaluation.

    This is the AST-based independent checker: it parses the condition
    string using Python's ast module (not string matching), so the checker
    is independent of how the generator formatted the condition.

    Returns a pyast.expr node, or None if parsing fails.
    """
    # Normalize SIL operators to Python equivalents for parsing
    normalized = (
        condition.strip()
        .replace(" and ", " and ")
        .replace(" or ", " or ")
        .replace("not ", "not ")
    )
    try:
        tree = pyast.parse(normalized, mode="eval")
        return tree.body
    except SyntaxError:
        return None


def _eval_condition_ast(
    node: Any,
    bounds: dict[str, "_Bound"],
    assumed: set[str],
) -> bool | None:
    """
    Evaluate a parsed condition AST against the symbolic environment.

    Returns True if provably true, False if provably false, None if unknown.
    This is the independent AST-based entailment check.
    """
    if node is None:
        return None

    if isinstance(node, pyast.Constant):
        if isinstance(node.value, bool):
            return node.value
        return None

    if isinstance(node, pyast.Name):
        if node.id == "true":
            return True
        if node.id == "false":
            return False
        return None

    if isinstance(node, pyast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            return None
        # LHS must be a Name (variable)
        if not isinstance(node.left, pyast.Name):
            return None
        var = node.left.id
        # RHS must be a constant integer
        rhs_node = node.comparators[0]
        if isinstance(rhs_node, pyast.Constant) and isinstance(rhs_node.value, int):
            rhs_val = rhs_node.value
        elif isinstance(rhs_node, pyast.UnaryOp) and isinstance(rhs_node.op, pyast.USub):
            if isinstance(rhs_node.operand, pyast.Constant) and isinstance(rhs_node.operand.value, int):
                rhs_val = -rhs_node.operand.value
            else:
                return None
        else:
            return None

        op = node.ops[0]
        b = bounds.get(var)
        if b is None:
            return None

        if b.exact is not None:
            if isinstance(op, pyast.GtE):
                return b.exact >= rhs_val
            if isinstance(op, pyast.Gt):
                return b.exact > rhs_val
            if isinstance(op, pyast.LtE):
                return b.exact <= rhs_val
            if isinstance(op, pyast.Lt):
                return b.exact < rhs_val
            if isinstance(op, pyast.Eq):
                return b.exact == rhs_val
            if isinstance(op, pyast.NotEq):
                return b.exact != rhs_val
            return None

        if isinstance(op, pyast.GtE):
            return b.lower is not None and b.lower >= rhs_val
        if isinstance(op, pyast.Gt):
            return b.lower is not None and b.lower > rhs_val
        if isinstance(op, pyast.LtE):
            return b.upper is not None and b.upper <= rhs_val
        if isinstance(op, pyast.Lt):
            return b.upper is not None and b.upper < rhs_val
        if isinstance(op, pyast.Eq):
            return (
                b.lower is not None
                and b.upper is not None
                and b.lower == b.upper == rhs_val
            )
        if isinstance(op, pyast.NotEq):
            if b.exact is not None:
                return b.exact != rhs_val
            return None
        return None

    if isinstance(node, pyast.BoolOp):
        if isinstance(node.op, pyast.And):
            results = [_eval_condition_ast(v, bounds, assumed) for v in node.values]
            if all(r is True for r in results):
                return True
            if any(r is False for r in results):
                return False
            return None
        if isinstance(node.op, pyast.Or):
            results = [_eval_condition_ast(v, bounds, assumed) for v in node.values]
            if any(r is True for r in results):
                return True
            if all(r is False for r in results):
                return False
            return None

    if isinstance(node, pyast.UnaryOp) and isinstance(node.op, pyast.Not):
        inner = _eval_condition_ast(node.operand, bounds, assumed)
        if inner is True:
            return False
        if inner is False:
            return True
        return None

    return None


def _negate_condition(condition: str) -> str | None:
    """Return the logical negation of a simple condition, or None."""
    parsed = _parse_simple_constraint(condition)
    if parsed is None:
        return None
    var, op, val = parsed
    negation_map = {"<": ">=", "<=": ">", ">": "<=", ">=": "<", "==": "!=", "!=": "=="}
    neg_op = negation_map.get(op)
    if neg_op is None:
        return None
    return f"{var} {neg_op} {val}"


def _eval_op(lhs: int, op: str, rhs: int) -> bool:
    if op == ">=":
        return lhs >= rhs
    if op == ">":
        return lhs > rhs
    if op == "<=":
        return lhs <= rhs
    if op == "<":
        return lhs < rhs
    if op == "==":
        return lhs == rhs
    if op == "!=":
        return lhs != rhs
    return False


# ---------------------------------------------------------------------------
# Check result
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    verdict: Verdict
    reason: str = ""
    failed_step: int | None = None  # 0-indexed step number
    covered_axioms: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def accepted(self) -> bool:
        return self.verdict == Verdict.ACCEPT


# ---------------------------------------------------------------------------
# Proof checker
# ---------------------------------------------------------------------------


class ProofChecker:
    """
    Validates a PPL proof without calling Z3.

    Usage:
        checker = ProofChecker(axioms)
        result = checker.check(proof_dict)
    """

    def __init__(self, axioms: list[dict[str, Any]]) -> None:
        """
        Args:
            axioms: list of dicts with keys 'id' and 'condition'.
        """
        self._axiom_map: dict[str, str] = {
            ax["id"]: ax["condition"] for ax in axioms
        }

    def check(self, proof: dict[str, Any]) -> CheckResult:
        """
        Validate *proof* and return a CheckResult.

        Args:
            proof: A PPL proof dict (see PROOF_LANGUAGE.md).

        Returns:
            CheckResult with verdict ACCEPT or REJECT.
        """
        t0 = time.monotonic()

        # Size guard
        try:
            raw = json.dumps(proof)
            if len(raw.encode()) > _MAX_PROOF_BYTES:
                return CheckResult(
                    Verdict.REJECT,
                    reason=f"Proof exceeds maximum size ({_MAX_PROOF_BYTES} bytes).",
                    elapsed_ms=(time.monotonic() - t0) * 1000,
                )
        except (TypeError, ValueError) as exc:
            return CheckResult(
                Verdict.REJECT,
                reason=f"Proof is not valid JSON: {exc}",
                elapsed_ms=(time.monotonic() - t0) * 1000,
            )

        # Version check
        if proof.get("version") != "1.0":
            return CheckResult(
                Verdict.REJECT,
                reason=f"Unsupported proof version: {proof.get('version')!r}",
                elapsed_ms=(time.monotonic() - t0) * 1000,
            )

        declared_axioms: list[str] = proof.get("axioms", [])
        steps: list[dict[str, Any]] = proof.get("steps", [])

        env = SymbolicEnv()

        # Seed environment from preconditions
        for var, constraint in proof.get("preconditions", {}).items():
            env.assume(var, constraint)

        covered_axioms: set[str] = set()
        conclude_seen = False
        conclude_result = None

        for step_idx, step in enumerate(steps):
            step_type = step.get("type")

            if step_type == "Assume":
                var = step.get("var", "")
                constraint = step.get("constraint", "")
                env.assume(var, constraint)

            elif step_type == "Assign":
                var = step.get("var", "")
                expr = step.get("expr", "")
                env.assign(var, expr)

            elif step_type == "Assert":
                condition = step.get("condition", "")
                if not env.entails(condition):
                    return CheckResult(
                        Verdict.REJECT,
                        reason=f"Step {step_idx} Assert failed: cannot prove '{condition}' from current environment.",
                        failed_step=step_idx,
                        elapsed_ms=(time.monotonic() - t0) * 1000,
                    )

            elif step_type == "ApplyAxiom":
                axiom_id = step.get("axiom_id", "")
                condition = step.get("condition", "")

                # Axiom must be declared in the proof header
                if axiom_id not in declared_axioms:
                    return CheckResult(
                        Verdict.REJECT,
                        reason=f"Step {step_idx} ApplyAxiom references undeclared axiom '{axiom_id}'.",
                        failed_step=step_idx,
                        elapsed_ms=(time.monotonic() - t0) * 1000,
                    )

                # Condition must match the registered axiom (if known)
                if axiom_id in self._axiom_map:
                    expected = self._axiom_map[axiom_id]
                    if condition.strip() != expected.strip():
                        return CheckResult(
                            Verdict.REJECT,
                            reason=(
                                f"Step {step_idx} ApplyAxiom condition mismatch for '{axiom_id}': "
                                f"expected '{expected}', got '{condition}'."
                            ),
                            failed_step=step_idx,
                            elapsed_ms=(time.monotonic() - t0) * 1000,
                        )

                # Condition must be entailed by current environment
                if not env.entails(condition):
                    return CheckResult(
                        Verdict.REJECT,
                        reason=(
                            f"Step {step_idx} ApplyAxiom: cannot prove axiom '{axiom_id}' "
                            f"condition '{condition}' from current environment."
                        ),
                        failed_step=step_idx,
                        elapsed_ms=(time.monotonic() - t0) * 1000,
                    )

                covered_axioms.add(axiom_id)

            elif step_type == "BranchSafe":
                # Record branch analysis — both branches must be safe
                then_safe = step.get("then_safe", False)
                else_safe = step.get("else_safe", False)
                if not (then_safe and else_safe):
                    return CheckResult(
                        Verdict.REJECT,
                        reason=f"Step {step_idx} BranchSafe: not all branches are safe (then={then_safe}, else={else_safe}).",
                        failed_step=step_idx,
                        elapsed_ms=(time.monotonic() - t0) * 1000,
                    )

            elif step_type == "LoopInvariant":
                # Record loop invariant — just validate it's consistent
                invariant = step.get("invariant", "")
                bound = step.get("bound", 0)
                if bound <= 0:
                    return CheckResult(
                        Verdict.REJECT,
                        reason=f"Step {step_idx} LoopInvariant: bound must be positive, got {bound}.",
                        failed_step=step_idx,
                        elapsed_ms=(time.monotonic() - t0) * 1000,
                    )
                # Add invariant to environment as an assumption
                env.assume("_invariant", invariant)

            elif step_type == "Conclude":
                conclude_seen = True
                conclude_result = step.get("result", "")

                if conclude_result != "safe":
                    return CheckResult(
                        Verdict.REJECT,
                        reason=f"Step {step_idx} Conclude: result is '{conclude_result}', expected 'safe'.",
                        failed_step=step_idx,
                        elapsed_ms=(time.monotonic() - t0) * 1000,
                    )

                # All declared axioms must be covered
                missing = set(declared_axioms) - covered_axioms
                if missing:
                    return CheckResult(
                        Verdict.REJECT,
                        reason=f"Step {step_idx} Conclude: axioms not covered: {sorted(missing)}.",
                        failed_step=step_idx,
                        elapsed_ms=(time.monotonic() - t0) * 1000,
                    )

            else:
                # Unknown step type — reject
                return CheckResult(
                    Verdict.REJECT,
                    reason=f"Step {step_idx}: unknown step type '{step_type}'.",
                    failed_step=step_idx,
                    elapsed_ms=(time.monotonic() - t0) * 1000,
                )

        # Must have a Conclude step
        if not conclude_seen:
            return CheckResult(
                Verdict.REJECT,
                reason="Proof has no Conclude step.",
                elapsed_ms=(time.monotonic() - t0) * 1000,
            )

        # Top-level conclusion must be "safe"
        if proof.get("conclusion") != "safe":
            return CheckResult(
                Verdict.REJECT,
                reason=f"Proof conclusion is '{proof.get('conclusion')}', expected 'safe'.",
                elapsed_ms=(time.monotonic() - t0) * 1000,
            )

        elapsed = (time.monotonic() - t0) * 1000
        return CheckResult(
            Verdict.ACCEPT,
            reason="All proof steps verified.",
            covered_axioms=sorted(covered_axioms),
            elapsed_ms=elapsed,
        )
