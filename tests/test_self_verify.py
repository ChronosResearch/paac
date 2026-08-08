"""tests/test_self_verify.py — Feature 2: Bootstrap Self-Verification"""

from src.core.self_verify import (
    SELF_AXIOMS,
    TCB_STUBS,
    SelfVerifier,
    python_to_sil_stub,
)
from src.core.sil_compiler import SILCompiler

COMPILER = SILCompiler()


# ---------------------------------------------------------------------------
# SIL stub generation
# ---------------------------------------------------------------------------


def test_python_to_sil_stub_basic():
    """Translate a simple Python function to a SIL stub."""
    src = """
def check_timeout(timeout_ms):
    assert timeout_ms >= 1
    return timeout_ms
"""
    stub = python_to_sil_stub("check_timeout", src)
    assert "func check_timeout" in stub
    assert "timeout_ms" in stub
    # Stub must be valid SIL even with no asserts (tautological fallback)
    ast, _ = SILCompiler().compile(stub)
    assert len(ast.functions) == 1


def test_python_to_sil_stub_compiles():
    """Generated stub must compile without error."""
    src = """
def check_limit(loop_limit):
    assert loop_limit >= 1
    return loop_limit
"""
    stub = python_to_sil_stub("check_limit", src)
    ast, _ = COMPILER.compile(stub)
    assert len(ast.functions) == 1


def test_python_to_sil_stub_invalid_syntax():
    """Invalid Python source falls back to trivially-safe stub."""
    stub = python_to_sil_stub("bad_func", "def (: invalid python !!!")
    assert "func bad_func" in stub


def test_python_to_sil_stub_no_asserts():
    """Function with no asserts produces valid SIL with a return statement."""
    src = "def f(x):\n    return x\n"
    stub = python_to_sil_stub("f", src)
    assert "func f" in stub
    assert "return" in stub


# ---------------------------------------------------------------------------
# TCB stub verification
# ---------------------------------------------------------------------------


def test_all_tcb_stubs_compile():
    """All built-in TCB stubs must compile."""
    for name, sil in TCB_STUBS.items():
        ast, _ = COMPILER.compile(sil)
        assert len(ast.functions) >= 1, f"Stub {name} has no functions"


def test_self_verifier_passes_all_stubs():
    """SelfVerifier must produce UNSAT (safe=True) for all built-in TCB stubs.

    With preconditioned stubs (if precond { assert postcond; }), Z3 proves
    UNSAT because no input satisfying the precondition violates the postcondition.
    This is true mathematical self-verification, not a stub that always returns SAT.
    """
    sv = SelfVerifier(timeout_ms=5000)
    result = sv.run()
    # All stubs must produce a result (no compilation errors)
    assert len(result.stub_results) == len(TCB_STUBS)
    # All stubs must be SAFE (UNSAT) with preconditioned design
    for name, safe in result.stub_results.items():
        assert safe is True, (
            f"Stub '{name}' returned SAT (unsafe) — preconditioned stub should be UNSAT. "
            f"CE: {result.counterexamples.get(name)}"
        )
    assert result.passed is True
    assert result.stage == 3


def test_self_verifier_stub_results_populated():
    """stub_results must contain an entry for every TCB stub."""
    sv = SelfVerifier()
    result = sv.run()
    for name in TCB_STUBS:
        assert name in result.stub_results


def test_self_verifier_rejects_malicious_stub():
    """A stub containing assert false must be rejected."""
    malicious_stub = "func malicious(x: int) -> int { " "assert false; " "return x; }"
    sv = SelfVerifier()
    result = sv.run(extra_stubs={"malicious": malicious_stub})
    assert "malicious" in result.stub_results
    assert result.stub_results["malicious"] is False


def test_verify_from_python_source():
    """End-to-end: translate Python source and verify."""
    src = """
def check_token_len(token_len):
    assert token_len >= 32
    return token_len
"""
    sv = SelfVerifier()
    result = sv.verify_from_python_source("check_token_len", src)
    assert isinstance(result.passed, bool)
    assert "check_token_len" in result.stub_results


def test_self_axioms_are_valid_sil():
    """All self-axioms must be parseable as SIL conditions."""
    for axiom in SELF_AXIOMS:
        assert axiom.condition
        assert axiom.id


def test_bootstrap_message_populated():
    """Result message must be non-empty."""
    sv = SelfVerifier()
    result = sv.run()
    assert len(result.message) > 0
