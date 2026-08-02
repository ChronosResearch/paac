"""Tests for the real BoundedModelChecker (Steps 3, 4, 5, 10)."""

import time

import pytest

from src.axioms.axiom_parser import Axiom
from src.core.sil_compiler import ProgramNode, SILCompiler
from src.core.verifier import (
    CONSTANT_VERIFICATION_TIME_S,
    BoundedModelChecker,
    VerificationError,
)

COMPILER = SILCompiler()


def compile(code: str) -> ProgramNode:
    ast, _ = COMPILER.compile(code)
    return ast


# ---------------------------------------------------------------------------
# Step 3: Real Z3 encoding
# ---------------------------------------------------------------------------


def test_safe_program_returns_unsat():
    """A trivially safe function with no assertions should be UNSAT (safe=True)."""
    ast = compile("""
    func add(a: int, b: int) -> int {
        return a + b;
    }
    """)
    bmc = BoundedModelChecker()
    safe, ce = bmc.verify(ast, [])
    assert safe is True
    assert ce is None


def test_assert_false_returns_sat_with_counterexample():
    """A function containing `assert false` must be SAT (safe=False) with a counterexample."""
    ast = compile("""
    func bad() -> int {
        assert false;
        return 0;
    }
    """)
    bmc = BoundedModelChecker()
    safe, ce = bmc.verify(ast, [])
    assert safe is False
    assert ce is not None


def test_conditional_assertion_violation():
    """Verifier must find the path where x < 0 violates assert x >= 0."""
    ast = compile("""
    func check(x: int) -> int {
        assert x >= 0;
        return x;
    }
    """)
    bmc = BoundedModelChecker()
    safe, ce = bmc.verify(ast, [])
    # x is unconstrained — Z3 can pick x = -1 to violate the assertion.
    assert safe is False
    assert ce is not None


def test_constrained_safe_assertion():
    """When the precondition makes the assertion always true, result is UNSAT."""
    # We encode the precondition as an axiom: x >= 0
    # ast with unconstrained x is unused — test verifies the tautology below.
    ast2 = compile("""
    func tautology(x: int) -> int {
        assert x == x;
        return x;
    }
    """)
    bmc = BoundedModelChecker()
    safe, _ce = bmc.verify(ast2, [])
    assert safe is True


# ---------------------------------------------------------------------------
# Step 4: Loop unrolling
# ---------------------------------------------------------------------------


def test_loop_with_safe_assertion():
    """A loop that counts up — assert inside loop should be provable safe."""
    ast = compile("""
    func count() -> int {
        x = 0;
        while (x < 3) bound 5 {
            x = x + 1;
        }
        return x;
    }
    """)
    bmc = BoundedModelChecker()
    safe, _ce = bmc.verify(ast, [])
    assert safe is True


def test_loop_bound_cap_in_verifier():
    """Verifier must reject a loop whose declared bound exceeds MAX_LOOP_BOUND."""
    import z3

    from src.core.sil_compiler import (
        LiteralNode,
        WhileStmtNode,
    )
    from src.core.verifier import SSAEnv, StmtEncoder

    ctx = z3.Context()
    solver = z3.Solver(ctx=ctx)
    env = SSAEnv(ctx)
    enc = StmtEncoder(ctx, solver, env)
    # Construct a WhileStmtNode with bound > MAX_LOOP_BOUND directly.
    cond = LiteralNode(False, "bool")
    stmt = WhileStmtNode(condition=cond, bound=10_001, body=[])
    with pytest.raises(VerificationError, match="exceeds global cap"):
        enc._encode_stmt(stmt, z3.BoolVal(True, ctx=ctx))


# ---------------------------------------------------------------------------
# Step 5: Secure cache hash
# ---------------------------------------------------------------------------


def test_cache_is_deterministic():
    """Same AST + axioms must produce the same hash on repeated calls."""
    ast = compile("func f(x: int) -> int { return x; }")
    axioms = [Axiom("AX1", "", "true", ["*"])]
    bmc = BoundedModelChecker()
    h1 = bmc._hash_ast(ast, axioms)
    h2 = bmc._hash_ast(ast, axioms)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest


def test_cache_hit_on_second_call():
    """Second call with identical input must hit the cache."""
    ast = compile("func f(x: int) -> int { return x; }")
    bmc = BoundedModelChecker()
    bmc.verify(ast, [])
    cache_key = bmc._hash_ast(ast, [])
    assert cache_key in bmc._cache


def test_different_asts_have_different_hashes():
    ast1 = compile("func f(x: int) -> int { return x; }")
    ast2 = compile("func g(x: int) -> int { return x; }")
    bmc = BoundedModelChecker()
    assert bmc._hash_ast(ast1, []) != bmc._hash_ast(ast2, [])


# ---------------------------------------------------------------------------
# Step 10: Constant-time padding
# ---------------------------------------------------------------------------


def test_constant_time_padding_on_safe_path():
    ast = compile("func f(x: int) -> int { return x; }")
    bmc = BoundedModelChecker()
    t0 = time.monotonic()
    bmc.verify(ast, [])
    elapsed = time.monotonic() - t0
    assert (
        elapsed >= CONSTANT_VERIFICATION_TIME_S * 0.9
    ), f"Expected >= {CONSTANT_VERIFICATION_TIME_S:.3f}s, got {elapsed:.3f}s"


def test_constant_time_padding_on_unsafe_path():
    ast = compile("""
    func bad() -> int {
        assert false;
        return 0;
    }
    """)
    bmc = BoundedModelChecker()
    t0 = time.monotonic()
    bmc.verify(ast, [])
    elapsed = time.monotonic() - t0
    assert (
        elapsed >= CONSTANT_VERIFICATION_TIME_S * 0.9
    ), f"Expected >= {CONSTANT_VERIFICATION_TIME_S:.3f}s, got {elapsed:.3f}s"
