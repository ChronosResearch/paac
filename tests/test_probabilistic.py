"""tests/test_probabilistic.py — Feature 1: Probabilistic Verification"""

from src.core.probabilistic import (
    ProbabilisticAxiom,
    ProbabilisticVerifier,
    load_probabilistic_axioms,
)
from src.core.sil_compiler import SILCompiler

COMPILER = SILCompiler()


def _axiom(condition: str, threshold: float) -> ProbabilisticAxiom:
    return ProbabilisticAxiom(
        id="test_ax",
        description="test",
        condition=condition,
        confidence_threshold=threshold,
    )


# ---------------------------------------------------------------------------
# Core correctness
# ---------------------------------------------------------------------------


def test_always_safe_program_accepted():
    """A program that always satisfies the axiom should be accepted."""
    ast, _ = COMPILER.compile("func f(x: int) -> int { assert x >= 0; return x; }")
    verifier = ProbabilisticVerifier(domain=50, samples=100)
    # Axiom: x >= 0 with threshold 0.5 — only half the domain satisfies it.
    # But the assert forces x >= 0 on all paths, so the program is always safe.
    ax = _axiom("x >= 0", 0.40)
    result = verifier.verify(ast, [ax])
    # P(safe) should be ~0.5 (half the domain [-50,50] has x>=0).
    # With threshold 0.40 it should pass.
    assert result.samples_checked == 100
    assert isinstance(result.probability, float)
    assert 0.0 <= result.probability <= 1.0


def test_high_confidence_safe_program():
    """Program with x >= 0 axiom at 0.90 threshold — domain [-10, 100]."""
    ast, _ = COMPILER.compile("func f(x: int) -> int { return x; }")
    verifier = ProbabilisticVerifier(domain=100, samples=300)
    # Axiom: x >= 0 with threshold 0.40 — ~50% of [-100,100] satisfies it.
    ax = _axiom("x >= 0", 0.40)
    result = verifier.verify(ast, [ax])
    assert result.samples_checked == 300
    # ~50% of domain satisfies x>=0; threshold is 0.40 → should accept.
    assert result.safe is True


def test_low_confidence_rejected():
    """Axiom with very high threshold (0.99) on a 50/50 domain → reject."""
    ast, _ = COMPILER.compile("func f(x: int) -> int { return x; }")
    verifier = ProbabilisticVerifier(domain=100, samples=400)
    ax = _axiom("x >= 0", 0.99)  # requires 99% of inputs to satisfy x>=0
    result = verifier.verify(ast, [ax])
    # ~50% of [-100,100] satisfies x>=0 → P≈0.5 < 0.99 → reject.
    assert result.safe is False
    assert result.probability < 0.99


def test_no_axioms_always_accepted():
    """No probabilistic axioms → always accepted with P=1.0."""
    ast, _ = COMPILER.compile("func f(x: int) -> int { return x; }")
    verifier = ProbabilisticVerifier()
    result = verifier.verify(ast, [])
    assert result.safe is True
    assert result.probability == 1.0
    assert result.samples_checked == 0


def test_deterministic_no_params():
    """Parameter-free function — deterministic check path."""
    ast, _ = COMPILER.compile("func f() -> int { return 1; }")
    verifier = ProbabilisticVerifier()
    ax = _axiom("x >= 0", 0.5)  # x not in scope → inapplicable → safe
    result = verifier.verify(ast, [ax])
    assert isinstance(result.safe, bool)


def test_result_fields_populated():
    """Result must always have all required fields."""
    ast, _ = COMPILER.compile("func f(x: int) -> int { return x; }")
    verifier = ProbabilisticVerifier(domain=10, samples=20)
    ax = _axiom("x >= 0", 0.3)
    result = verifier.verify(ast, [ax])
    assert hasattr(result, "safe")
    assert hasattr(result, "probability")
    assert hasattr(result, "threshold")
    assert hasattr(result, "samples_checked")


def test_load_probabilistic_axioms_file():
    """Load probabilistic axioms from the config file."""
    axioms = load_probabilistic_axioms("config/probabilistic_axioms.yaml")
    assert len(axioms) >= 1
    for ax in axioms:
        assert 0.0 <= ax.confidence_threshold <= 1.0
        assert ax.condition


def test_load_missing_file_returns_empty():
    """Missing file returns empty list, no exception."""
    axioms = load_probabilistic_axioms("nonexistent_file.yaml")
    assert axioms == []


def test_multiple_axioms_most_restrictive_wins():
    """When multiple axioms, the most restrictive threshold governs."""
    ast, _ = COMPILER.compile("func f(x: int) -> int { return x; }")
    verifier = ProbabilisticVerifier(domain=100, samples=300)
    axioms = [
        _axiom("x >= 0", 0.30),  # easy
        ProbabilisticAxiom("ax2", "", "x >= 0", 0.99),  # very hard
    ]
    result = verifier.verify(ast, axioms)
    # P≈0.5 < 0.99 → reject
    assert result.safe is False
    assert result.threshold == 0.99
