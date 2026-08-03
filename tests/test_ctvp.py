"""tests/test_ctvp.py — Feature 4: Cross-Trace Semantic Verification (CTVP)"""

from src.core.ctvp import (
    CTVPEngine,
    _algebraic_simplify,
    _increase_loop_bound,
    _rename_vars,
    _split_conjunctive_asserts,
)
from src.core.sil_compiler import SILCompiler

COMPILER = SILCompiler()


# ---------------------------------------------------------------------------
# Variant generators
# ---------------------------------------------------------------------------


def test_rename_vars_produces_valid_ast():
    """Variable renaming must produce a compilable-equivalent AST."""
    ast, _ = COMPILER.compile("func f(x: int) -> int { y = x + 1; return y; }")
    renamed = _rename_vars(ast)
    # v0 should replace y (x is a param, kept as-is).
    assert renamed.functions[0].name == "f"


def test_algebraic_simplify_removes_identity():
    """x + 0 should be simplified to x."""
    from src.core.sil_compiler import (
        AssignmentStmtNode,
        BinaryExprNode,
        FuncDefNode,
        IdentifierNode,
        LiteralNode,
        ParamNode,
        ProgramNode,
        ReturnStmtNode,
    )

    ast = ProgramNode(
        functions=[
            FuncDefNode(
                name="f",
                params=[ParamNode("x", "int")],
                return_type="int",
                body=[
                    AssignmentStmtNode(
                        "y",
                        BinaryExprNode(IdentifierNode("x"), "+", LiteralNode(0, "int")),
                    ),
                    ReturnStmtNode(IdentifierNode("y")),
                ],
            )
        ]
    )
    simplified = _algebraic_simplify(ast)
    assign = simplified.functions[0].body[0]
    # After simplification, y = x (not x + 0).
    assert isinstance(assign, AssignmentStmtNode)
    assert isinstance(assign.value, IdentifierNode)
    assert assign.value.name == "x"


def test_increase_loop_bound():
    """Loop bound should increase by 1."""
    ast, _ = COMPILER.compile(
        "func f(n: int) -> int { i = 0; while (i < n) bound 5 { i = i + 1; } return i; }"
    )
    bumped = _increase_loop_bound(ast, delta=1)
    from src.core.sil_compiler import WhileStmtNode

    while_stmt = next(
        s for s in bumped.functions[0].body if isinstance(s, WhileStmtNode)
    )
    assert while_stmt.bound == 6


def test_split_conjunctive_asserts():
    """assert (a and b) should split into assert a; assert b."""
    from src.core.sil_compiler import (
        AssertStmtNode,
        BinaryExprNode,
        FuncDefNode,
        IdentifierNode,
        LiteralNode,
        ParamNode,
        ProgramNode,
        ReturnStmtNode,
    )

    ast = ProgramNode(
        functions=[
            FuncDefNode(
                name="f",
                params=[ParamNode("x", "int"), ParamNode("y", "int")],
                return_type="int",
                body=[
                    AssertStmtNode(
                        BinaryExprNode(
                            BinaryExprNode(
                                IdentifierNode("x"), ">=", LiteralNode(0, "int")
                            ),
                            "and",
                            BinaryExprNode(
                                IdentifierNode("y"), ">=", LiteralNode(0, "int")
                            ),
                        )
                    ),
                    ReturnStmtNode(IdentifierNode("x")),
                ],
            )
        ]
    )
    split = _split_conjunctive_asserts(ast)
    asserts = [s for s in split.functions[0].body if isinstance(s, AssertStmtNode)]
    assert len(asserts) == 2


# ---------------------------------------------------------------------------
# CTVP engine
# ---------------------------------------------------------------------------


def test_safe_program_consistent():
    """A safe program should produce consistent results across all variants."""
    ast, _ = COMPILER.compile("func f(x: int) -> int { assert x == x; return x; }")
    engine = CTVPEngine(timeout_ms=5000)
    result = engine.verify(ast, [])
    assert result.consistency_score == 1.0
    assert result.backdoor_detected is False
    assert result.accepted is True


def test_trivially_safe_no_asserts():
    """Program with no assertions — all variants agree on UNSAT."""
    ast, _ = COMPILER.compile("func f(x: int) -> int { return x; }")
    engine = CTVPEngine()
    result = engine.verify(ast, [])
    assert result.consistency_score == 1.0
    assert result.accepted is True


def test_variant_results_populated():
    """All variants must produce a VariantResult entry."""
    ast, _ = COMPILER.compile("func f(x: int) -> int { return x; }")
    engine = CTVPEngine()
    result = engine.verify(ast, [])
    assert len(result.variant_results) == len(CTVPEngine.VARIANTS)
    for vr in result.variant_results:
        assert vr.variant_name
        assert isinstance(vr.safe, bool)


def test_consistency_score_range():
    """Consistency score must be in [0, 1]."""
    ast, _ = COMPILER.compile("func f(x: int) -> int { return x; }")
    engine = CTVPEngine()
    result = engine.verify(ast, [])
    assert 0.0 <= result.consistency_score <= 1.0


def test_message_populated():
    """Result message must be non-empty."""
    ast, _ = COMPILER.compile("func f(x: int) -> int { return x; }")
    engine = CTVPEngine()
    result = engine.verify(ast, [])
    assert len(result.message) > 0


def test_loop_program_consistent():
    """A loop program should be consistent across variants."""
    ast, _ = COMPILER.compile(
        "func f(n: int) -> int { i = 0; while (i < n) bound 5 { i = i + 1; } return i; }"
    )
    engine = CTVPEngine()
    result = engine.verify(ast, [])
    assert result.backdoor_detected is False


def test_algebraic_identity_program_consistent():
    """Program using x+0 should be consistent with simplified variant."""
    ast, _ = COMPILER.compile(
        "func f(x: int) -> int { y = x + 0; assert y == x; return y; }"
    )
    engine = CTVPEngine()
    result = engine.verify(ast, [])
    assert result.consistency_score == 1.0
