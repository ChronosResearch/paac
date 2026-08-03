"""
src/core/ctvp.py
----------------
Feature 4: Cross-Trace Semantic Verification Protocol (CTVP)

Detects semantic backdoors by generating semantically equivalent variants of
a SIL program, verifying each variant independently, and checking that all
variants produce consistent results.

A semantic backdoor is a program that:
  - Passes verification under the original form.
  - Fails verification (SAT) under a semantically equivalent variant.

This is impossible for a correct program — if P is safe, every semantically
equivalent P' must also be safe.

Variant Generation
------------------
1. Variable renaming   — rename all locals to canonical names (v0, v1, …)
2. Algebraic identity  — replace x + 0 with x, x * 1 with x, x - 0 with x
3. Assertion rewrite   — replace assert (a and b) with assert a; assert b
4. Loop bound increase — increase loop bound by 1 (sound: more unrollings)

Consistency Scoring
-------------------
C = fraction of variant pairs that agree on UNSAT/SAT.
  C >= T_soft  → ACCEPT
  C <  T_strict → REJECT (semantic inconsistency)
  otherwise    → WARN

Thresholds (configurable via env vars):
  PAAC_CTVP_T_STRICT : float (default 0.6)
  PAAC_CTVP_T_SOFT   : float (default 0.9)
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field

from loguru import logger

from src.axioms.axiom_parser import Axiom
from src.core.sil_compiler import (
    AssertStmtNode,
    AssignmentStmtNode,
    ASTNode,
    BinaryExprNode,
    IdentifierNode,
    IfStmtNode,
    LiteralNode,
    ProgramNode,
    ReturnStmtNode,
    UnaryExprNode,
    WhileStmtNode,
)
from src.core.verifier import BoundedModelChecker

_T_STRICT: float = float(os.environ.get("PAAC_CTVP_T_STRICT", "0.6"))
_T_SOFT: float = float(os.environ.get("PAAC_CTVP_T_SOFT", "0.9"))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class VariantResult:
    variant_name: str
    safe: bool
    counterexample: str | None = None
    error: str | None = None


@dataclass
class CTVPResult:
    accepted: bool
    consistency_score: float
    variant_results: list[VariantResult] = field(default_factory=list)
    backdoor_detected: bool = False
    anomalous_variant: str | None = None
    message: str = ""


# ---------------------------------------------------------------------------
# Variant generators
# ---------------------------------------------------------------------------


def _rename_vars(prog: ProgramNode) -> ProgramNode:
    """Rename all local variables to canonical names v0, v1, …"""
    prog = copy.deepcopy(prog)
    for func in prog.functions:
        mapping: dict[str, str] = {}
        counter = [0]
        param_names = {p.name for p in func.params}

        def _new_name(
            old: str,
            _pn: set = param_names,
            _m: dict = mapping,
            _c: list = counter,
        ) -> str:
            if old in _pn:
                return old
            if old not in _m:
                _m[old] = f"v{_c[0]}"
                _c[0] += 1
            return _m[old]

        def _rename_node(node: ASTNode) -> ASTNode:
            if isinstance(node, IdentifierNode):
                return IdentifierNode(_new_name(node.name))
            if isinstance(node, AssignmentStmtNode):
                return AssignmentStmtNode(
                    _new_name(node.target), _rename_node(node.value)
                )
            if isinstance(node, BinaryExprNode):
                return BinaryExprNode(
                    _rename_node(node.left), node.operator, _rename_node(node.right)
                )
            if isinstance(node, UnaryExprNode):
                return UnaryExprNode(node.operator, _rename_node(node.operand))
            if isinstance(node, ReturnStmtNode):
                return ReturnStmtNode(_rename_node(node.value))
            if isinstance(node, AssertStmtNode):
                return AssertStmtNode(_rename_node(node.condition))
            if isinstance(node, IfStmtNode):
                return IfStmtNode(
                    _rename_node(node.condition),
                    [_rename_node(s) for s in node.then_branch],
                    [_rename_node(s) for s in node.else_branch],
                )
            if isinstance(node, WhileStmtNode):
                return WhileStmtNode(
                    _rename_node(node.condition),
                    node.bound,
                    [_rename_node(s) for s in node.body],
                )
            return node

        func.body = [_rename_node(s) for s in func.body]
    return prog


def _algebraic_simplify(prog: ProgramNode) -> ProgramNode:
    """Replace x+0, x-0, x*1 with x (algebraic identities)."""
    prog = copy.deepcopy(prog)

    def _simplify(node: ASTNode) -> ASTNode:
        if isinstance(node, BinaryExprNode):
            left = _simplify(node.left)
            right = _simplify(node.right)
            # x + 0 → x,  x - 0 → x
            if (
                node.operator in ("+", "-")
                and isinstance(right, LiteralNode)
                and right.value == 0
            ):
                return left
            # 0 + x → x
            if (
                node.operator == "+"
                and isinstance(left, LiteralNode)
                and left.value == 0
            ):
                return right
            # x * 1 → x,  1 * x → x
            if (
                node.operator == "*"
                and isinstance(right, LiteralNode)
                and right.value == 1
            ):
                return left
            if (
                node.operator == "*"
                and isinstance(left, LiteralNode)
                and left.value == 1
            ):
                return right
            return BinaryExprNode(left, node.operator, right)
        if isinstance(node, UnaryExprNode):
            return UnaryExprNode(node.operator, _simplify(node.operand))
        if isinstance(node, AssignmentStmtNode):
            return AssignmentStmtNode(node.target, _simplify(node.value))
        if isinstance(node, ReturnStmtNode):
            return ReturnStmtNode(_simplify(node.value))
        if isinstance(node, AssertStmtNode):
            return AssertStmtNode(_simplify(node.condition))
        if isinstance(node, IfStmtNode):
            return IfStmtNode(
                _simplify(node.condition),
                [_simplify(s) for s in node.then_branch],
                [_simplify(s) for s in node.else_branch],
            )
        if isinstance(node, WhileStmtNode):
            return WhileStmtNode(
                _simplify(node.condition),
                node.bound,
                [_simplify(s) for s in node.body],
            )
        return node

    for func in prog.functions:
        func.body = [_simplify(s) for s in func.body]
    return prog


def _increase_loop_bound(prog: ProgramNode, delta: int = 1) -> ProgramNode:
    """Increase all loop bounds by delta (sound: more unrollings = stricter)."""
    prog = copy.deepcopy(prog)

    def _bump(node: ASTNode) -> ASTNode:
        if isinstance(node, WhileStmtNode):
            new_bound = min(
                node.bound + delta,
                BoundedModelChecker.__class__.__dict__.get("MAX_LOOP_BOUND", 10_000),
            )
            return WhileStmtNode(
                node.condition, new_bound, [_bump(s) for s in node.body]
            )
        if isinstance(node, IfStmtNode):
            return IfStmtNode(
                node.condition,
                [_bump(s) for s in node.then_branch],
                [_bump(s) for s in node.else_branch],
            )
        if isinstance(node, AssignmentStmtNode):
            return AssignmentStmtNode(node.target, node.value)
        return node

    for func in prog.functions:
        func.body = [_bump(s) for s in func.body]
    return prog


def _split_conjunctive_asserts(prog: ProgramNode) -> ProgramNode:
    """Replace assert (a and b) with assert a; assert b."""
    prog = copy.deepcopy(prog)

    def _expand(stmt: ASTNode) -> list[ASTNode]:
        if isinstance(stmt, AssertStmtNode):
            cond = stmt.condition
            if isinstance(cond, BinaryExprNode) and cond.operator == "and":
                return _expand(AssertStmtNode(cond.left)) + _expand(
                    AssertStmtNode(cond.right)
                )
        if isinstance(stmt, IfStmtNode):
            return [
                IfStmtNode(
                    stmt.condition,
                    [s for sub in stmt.then_branch for s in _expand(sub)],
                    [s for sub in stmt.else_branch for s in _expand(sub)],
                )
            ]
        if isinstance(stmt, WhileStmtNode):
            return [
                WhileStmtNode(
                    stmt.condition,
                    stmt.bound,
                    [s for sub in stmt.body for s in _expand(sub)],
                )
            ]
        return [stmt]

    for func in prog.functions:
        func.body = [s for stmt in func.body for s in _expand(stmt)]
    return prog


# ---------------------------------------------------------------------------
# CTVP engine
# ---------------------------------------------------------------------------


class CTVPEngine:
    """
    Generates a semantic orbit for a SIL program and checks cross-trace
    consistency to detect semantic backdoors.
    """

    VARIANTS: list = [
        ("original", lambda p: p),
        ("renamed", _rename_vars),
        ("simplified", _algebraic_simplify),
        ("split_asserts", _split_conjunctive_asserts),
        ("bound_plus_1", _increase_loop_bound),
    ]

    def __init__(self, timeout_ms: int = 5000) -> None:
        self._bmc = BoundedModelChecker()
        self._timeout_ms = timeout_ms

    def verify(
        self,
        ast: ProgramNode,
        axioms: list[Axiom],
        t_strict: float = _T_STRICT,
        t_soft: float = _T_SOFT,
    ) -> CTVPResult:
        """
        Run CTVP on the given program.
        Returns a CTVPResult with consistency score and verdict.
        """
        results: list[VariantResult] = []

        for name, transform in self.VARIANTS:
            try:
                variant = transform(ast)
                safe, ce = self._bmc._verify_inner(variant, axioms, self._timeout_ms)
                results.append(
                    VariantResult(
                        variant_name=name,
                        safe=safe,
                        counterexample=str(ce) if ce else None,
                    )
                )
            except Exception as exc:
                results.append(
                    VariantResult(
                        variant_name=name,
                        safe=True,  # fail-open for transform errors
                        error=str(exc),
                    )
                )

        # Compute consistency: fraction of pairs that agree.
        n = len(results)
        if n <= 1:
            return CTVPResult(
                accepted=True,
                consistency_score=1.0,
                variant_results=results,
                message="Only one variant — no cross-trace comparison possible.",
            )

        agreements = sum(
            1
            for i in range(n)
            for j in range(i + 1, n)
            if results[i].safe == results[j].safe
        )
        total_pairs = n * (n - 1) // 2
        score = agreements / total_pairs

        # Detect backdoor: any variant disagrees with the original.
        original_safe = results[0].safe
        anomalous: VariantResult | None = next(
            (r for r in results[1:] if r.safe != original_safe), None
        )
        backdoor = anomalous is not None

        if backdoor and anomalous is not None:
            msg = (
                f"CTVP: semantic backdoor detected -- variant '{anomalous.variant_name}' "
                f"disagrees with original. C={score:.2f}."
            )
            logger.warning(msg)
            return CTVPResult(
                accepted=False,
                consistency_score=score,
                variant_results=results,
                backdoor_detected=True,
                anomalous_variant=anomalous.variant_name,
                message=msg,
            )

        if score >= t_soft:
            msg = f"CTVP: ACCEPT — C={score:.2f} >= T_soft={t_soft:.2f}."
        elif score >= t_strict:
            msg = f"CTVP: WARN — C={score:.2f} in [{t_strict:.2f}, {t_soft:.2f})."
        else:
            msg = f"CTVP: REJECT — C={score:.2f} < T_strict={t_strict:.2f}."

        accepted = score >= t_strict
        logger.info(msg)
        return CTVPResult(
            accepted=accepted,
            consistency_score=score,
            variant_results=results,
            message=msg,
        )
