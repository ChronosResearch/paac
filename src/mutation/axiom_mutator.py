"""
src/mutation/axiom_mutator.py
------------------------------
Mutation operators for safety axioms.

Each operator takes an Axiom and returns a list of MutatedAxiom objects.
Operators:
  - negate        : wrap condition in not(...)
  - weaken_op     : replace strict comparisons with weaker ones (>= -> >, == -> >=)
  - strengthen_op : replace comparisons with stricter ones (>= -> >, > -> >=)
  - shift_const   : shift integer constants by ±1, ±5, ±10
  - vacuous       : replace condition with true (detects vacuous axioms)
  - noop          : identity — baseline sanity check
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from src.axioms.axiom_parser import Axiom


class MutationKind(str, Enum):
    NEGATE = "negate"
    WEAKEN_OP = "weaken_op"
    STRENGTHEN_OP = "strengthen_op"
    SHIFT_CONST = "shift_const"
    VACUOUS = "vacuous"
    NOOP = "noop"


@dataclass
class MutatedAxiom:
    original: Axiom
    mutant: Axiom
    kind: MutationKind
    description: str
    # Expected direction: "fail_more" (negate/strengthen) or "fail_less" (weaken/vacuous)
    expected_direction: str = "unknown"


# Operator replacement tables
# Weaken: make the condition easier to satisfy (accept more programs)
_WEAKEN_OPS: dict[str, str] = {
    ">=": ">",
    "<=": "<",
    ">": ">=",
    "<": "<=",
    "==": ">=",
    "!=": "==",
}

# Strengthen: make the condition harder to satisfy (reject more programs)
_STRENGTHEN_OPS: dict[str, str] = {
    ">=": ">",
    "<=": "<",
    ">": "==",
    "<": "==",
}

# Regex to find integer literals in conditions (not part of identifiers)
_INT_RE = re.compile(r"(?<![a-zA-Z_])(-?\d+)(?![a-zA-Z_])")

# Regex to find comparison operators (longest first to avoid partial matches)
_OP_RE = re.compile(r"(>=|<=|==|!=|>(?!=)|<(?!=))")


def _replace_first_op(condition: str, table: dict[str, str]) -> str | None:
    """Replace the first matching operator in condition using table. Returns None if no match."""
    for mo in _OP_RE.finditer(condition):
        op = mo.group(1)
        if op in table:
            return condition[: mo.start()] + table[op] + condition[mo.end() :]
    return None


def _shift_first_const(condition: str, delta: int) -> str | None:
    """Shift the first integer literal in condition by delta. Returns None if no literal."""
    mo = _INT_RE.search(condition)
    if mo is None:
        return None
    original_val = int(mo.group(1))
    new_val = original_val + delta
    return condition[: mo.start()] + str(new_val) + condition[mo.end() :]


def _make_mutant(original: Axiom, new_condition: str, suffix: str) -> Axiom:
    return Axiom(
        id=f"{original.id}__{suffix}",
        description=f"[MUTANT:{suffix}] {original.description}",
        condition=new_condition,
        target_functions=list(original.target_functions),
    )


def generate_mutations(axiom: Axiom) -> list[MutatedAxiom]:
    """Generate all mutations for a single axiom."""
    mutations: list[MutatedAxiom] = []
    cond = axiom.condition

    # NOOP — baseline
    mutations.append(
        MutatedAxiom(
            original=axiom,
            mutant=_make_mutant(axiom, cond, "noop"),
            kind=MutationKind.NOOP,
            description="Identity — no change to condition.",
            expected_direction="same",
        )
    )

    # VACUOUS — replace with true
    mutations.append(
        MutatedAxiom(
            original=axiom,
            mutant=_make_mutant(axiom, "true", "vacuous"),
            kind=MutationKind.VACUOUS,
            description="Replace condition with true (detects vacuous axioms).",
            expected_direction="fail_less",
        )
    )

    # NEGATE — wrap in not(...)
    negated = f"not ({cond})"
    mutations.append(
        MutatedAxiom(
            original=axiom,
            mutant=_make_mutant(axiom, negated, "negate"),
            kind=MutationKind.NEGATE,
            description=f"Negate condition: not ({cond})",
            expected_direction="fail_more",
        )
    )

    # WEAKEN_OP — replace first comparison with weaker one
    weakened = _replace_first_op(cond, _WEAKEN_OPS)
    if weakened and weakened != cond:
        mutations.append(
            MutatedAxiom(
                original=axiom,
                mutant=_make_mutant(axiom, weakened, "weaken_op"),
                kind=MutationKind.WEAKEN_OP,
                description=f"Weaken operator: '{cond}' -> '{weakened}'",
                expected_direction="fail_less",
            )
        )

    # STRENGTHEN_OP — replace first comparison with stricter one
    strengthened = _replace_first_op(cond, _STRENGTHEN_OPS)
    if strengthened and strengthened != cond:
        mutations.append(
            MutatedAxiom(
                original=axiom,
                mutant=_make_mutant(axiom, strengthened, "strengthen_op"),
                kind=MutationKind.STRENGTHEN_OP,
                description=f"Strengthen operator: '{cond}' -> '{strengthened}'",
                expected_direction="fail_more",
            )
        )

    # SHIFT_CONST — shift integer constants
    for delta, label in [
        (-1, "shift_m1"),
        (+1, "shift_p1"),
        (-5, "shift_m5"),
        (+5, "shift_p5"),
    ]:
        shifted = _shift_first_const(cond, delta)
        if shifted and shifted != cond:
            direction = "fail_less" if delta < 0 else "fail_more"
            mutations.append(
                MutatedAxiom(
                    original=axiom,
                    mutant=_make_mutant(axiom, shifted, label),
                    kind=MutationKind.SHIFT_CONST,
                    description=f"Shift constant by {delta:+d}: '{cond}' -> '{shifted}'",
                    expected_direction=direction,
                )
            )

    return mutations
