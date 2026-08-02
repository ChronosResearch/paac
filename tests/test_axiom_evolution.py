"""tests/test_axiom_evolution.py — Feature 5: Verified Self-Evolving Axioms"""
import pytest
from src.axioms.axiom_parser import Axiom
from src.core.axiom_evolution import (
    AxiomEvolutionEngine, AxiomModification,
)


def _base_axioms() -> list[Axiom]:
    return [
        Axiom("balance_nonneg", "Balance non-negative", "balance >= 0", ["*"]),
        Axiom("counter_nonneg", "Counter non-negative", "counter >= 0", ["*"]),
    ]


# ---------------------------------------------------------------------------
# Conservative extension check
# ---------------------------------------------------------------------------

def test_strengthen_axiom_accepted():
    """Strengthening balance >= 0 to balance >= 1 must be accepted."""
    engine = AxiomEvolutionEngine(_base_axioms())
    mod = AxiomModification(
        old_axiom_id="balance_nonneg",
        new_condition="balance >= 1",   # strictly stronger
        justification="Require positive balance",
    )
    result = engine.propose_change(mod)
    assert result.accepted is True
    assert result.counterexample is None


def test_relax_axiom_rejected():
    """Relaxing balance >= 0 to balance >= -10 must be rejected."""
    engine = AxiomEvolutionEngine(_base_axioms())
    mod = AxiomModification(
        old_axiom_id="balance_nonneg",
        new_condition="balance >= -10",  # weaker
        justification="Allow overdraft",
    )
    result = engine.propose_change(mod)
    assert result.accepted is False
    assert result.counterexample is not None  # Z3 found a violating state


def test_equivalent_axiom_accepted():
    """Replacing balance >= 0 with balance >= 0 (same) must be accepted."""
    engine = AxiomEvolutionEngine(_base_axioms())
    mod = AxiomModification(
        old_axiom_id="balance_nonneg",
        new_condition="balance >= 0",   # identical
        justification="No change",
    )
    result = engine.propose_change(mod)
    assert result.accepted is True


def test_add_new_axiom_accepted():
    """Adding a brand-new axiom must always be accepted."""
    engine = AxiomEvolutionEngine(_base_axioms())
    new_ax = Axiom("result_nonneg", "Result non-negative", "result >= 0", ["*"])
    result = engine.add_axiom(new_ax)
    assert result.accepted is True
    assert len(engine.axioms) == 3


def test_add_duplicate_axiom_rejected():
    """Adding an axiom with an existing ID must be rejected."""
    engine = AxiomEvolutionEngine(_base_axioms())
    dup = Axiom("balance_nonneg", "dup", "balance >= 0", ["*"])
    result = engine.add_axiom(dup)
    assert result.accepted is False


def test_unknown_axiom_id_rejected():
    """Proposing a change to a non-existent axiom ID must be rejected."""
    engine = AxiomEvolutionEngine(_base_axioms())
    mod = AxiomModification(
        old_axiom_id="nonexistent",
        new_condition="x >= 0",
        justification="test",
    )
    result = engine.propose_change(mod)
    assert result.accepted is False


# ---------------------------------------------------------------------------
# Monotonicity and history
# ---------------------------------------------------------------------------

def test_axiom_set_updated_after_acceptance():
    """After an accepted change, the axiom set must reflect the new condition."""
    engine = AxiomEvolutionEngine(_base_axioms())
    mod = AxiomModification("balance_nonneg", "balance >= 5", "stronger")
    engine.propose_change(mod)
    updated = next(a for a in engine.axioms if a.id == "balance_nonneg")
    assert updated.condition == "balance >= 5"


def test_axiom_set_unchanged_after_rejection():
    """After a rejected change, the axiom set must be unchanged."""
    engine = AxiomEvolutionEngine(_base_axioms())
    mod = AxiomModification("balance_nonneg", "balance >= -100", "weaker")
    engine.propose_change(mod)
    unchanged = next(a for a in engine.axioms if a.id == "balance_nonneg")
    assert unchanged.condition == "balance >= 0"


def test_history_records_all_proposals():
    """Every proposal (accepted or rejected) must appear in history."""
    engine = AxiomEvolutionEngine(_base_axioms())
    engine.propose_change(AxiomModification("balance_nonneg", "balance >= 1", "ok"))
    engine.propose_change(AxiomModification("balance_nonneg", "balance >= -1", "bad"))
    history = engine.history()
    assert len(history) == 2
    assert history[0].accepted is True
    assert history[1].accepted is False


def test_version_increments_on_acceptance():
    """Version number must increment on each accepted change."""
    engine = AxiomEvolutionEngine(_base_axioms())
    assert engine._version == 0
    engine.propose_change(AxiomModification("balance_nonneg", "balance >= 1", "ok"))
    assert engine._version == 1
    engine.propose_change(AxiomModification("balance_nonneg", "balance >= 2", "ok"))
    assert engine._version == 2


def test_version_unchanged_on_rejection():
    """Version must not change on rejected proposals."""
    engine = AxiomEvolutionEngine(_base_axioms())
    engine.propose_change(AxiomModification("balance_nonneg", "balance >= -1", "bad"))
    assert engine._version == 0


def test_monotonic_strengthening_chain():
    """A chain of strengthenings must all be accepted."""
    engine = AxiomEvolutionEngine(_base_axioms())
    for threshold in [1, 2, 3, 5, 10]:
        mod = AxiomModification(
            "balance_nonneg", f"balance >= {threshold}", f"raise to {threshold}"
        )
        result = engine.propose_change(mod)
        assert result.accepted is True, f"Failed at threshold {threshold}"
    final = next(a for a in engine.axioms if a.id == "balance_nonneg")
    assert final.condition == "balance >= 10"
