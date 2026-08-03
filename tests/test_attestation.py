"""tests/test_attestation.py — Feature 3: Cryptographic Attestation"""

import json

from src.core.attestation import (
    AttestationEngine,
    AttestationRecord,
    attest_verification,
    verify_attestation,
)

# ---------------------------------------------------------------------------
# Basic generation and verification
# ---------------------------------------------------------------------------


def test_attest_safe_program():
    """Attestation for a safe (UNSAT) result must be generated and verify."""
    engine = AttestationEngine()
    record = engine.attest(
        modification_id="test_safe",
        program_hash="abc123",
        axiom_hash="def456",
        safe=True,
        counterexample_str=None,
    )
    assert record.result == "UNSAT"
    assert record.ce_hash is None
    assert len(record.commitment) == 64  # SHA-256 hex = 64 chars
    assert engine.verify(record) is True


def test_attest_unsafe_program():
    """Attestation for an unsafe (SAT) result must include ce_hash."""
    engine = AttestationEngine()
    record = engine.attest(
        modification_id="test_unsafe",
        program_hash="abc123",
        axiom_hash="def456",
        safe=False,
        counterexample_str="  x = -1",
    )
    assert record.result == "SAT"
    assert record.ce_hash is not None
    assert len(record.ce_hash) == 64
    assert engine.verify(record) is True


def test_tampered_result_fails_verification():
    """Modifying the result field must invalidate the commitment."""
    engine = AttestationEngine()
    record = engine.attest("mod_h1", "h1", "h2", True, None)
    # Tamper with the result.
    tampered = AttestationRecord(
        modification_id=record.modification_id,
        program_hash=record.program_hash,
        axiom_hash=record.axiom_hash,
        result="SAT",  # changed from UNSAT
        ce_hash=record.ce_hash,
        timestamp=record.timestamp,
        commitment=record.commitment,
    )
    assert engine.verify(tampered) is False


def test_tampered_program_hash_fails():
    """Modifying program_hash must invalidate the commitment."""
    engine = AttestationEngine()
    record = engine.attest("mod_orig", "original_hash", "ax_hash", True, None)
    tampered = AttestationRecord(
        modification_id=record.modification_id,
        program_hash="tampered_hash",
        axiom_hash=record.axiom_hash,
        result=record.result,
        ce_hash=record.ce_hash,
        timestamp=record.timestamp,
        commitment=record.commitment,
    )
    assert engine.verify(tampered) is False


def test_different_keys_produce_different_commitments():
    """Two engines with different keys must produce different commitments."""
    import secrets

    engine1 = AttestationEngine(key=secrets.token_bytes(32))
    engine2 = AttestationEngine(key=secrets.token_bytes(32))
    r1 = engine1.attest("mod_e1", "h", "a", True, None)
    r2 = engine2.attest("mod_e2", "h", "a", True, None)
    assert r1.commitment != r2.commitment


def test_cross_engine_verification_fails():
    """A record from engine1 must not verify under engine2."""
    import secrets

    engine1 = AttestationEngine(key=secrets.token_bytes(32))
    engine2 = AttestationEngine(key=secrets.token_bytes(32))
    record = engine1.attest("mod_e1b", "h", "a", True, None)
    assert engine2.verify(record) is False


def test_module_level_functions():
    """Module-level attest_verification and verify_attestation must work."""
    record = attest_verification("mod_test", "ph", "ah", True, None)
    assert verify_attestation(record) is True


def test_hash_program_deterministic():
    """hash_program must be deterministic."""
    h1 = AttestationEngine.hash_program("func f(x: int) -> int { return x; }")
    h2 = AttestationEngine.hash_program("func f(x: int) -> int { return x; }")
    assert h1 == h2


def test_hash_axioms_order_independent():
    """hash_axioms must be order-independent."""
    h1 = AttestationEngine.hash_axioms(["x >= 0", "y >= 0"])
    h2 = AttestationEngine.hash_axioms(["y >= 0", "x >= 0"])
    assert h1 == h2


def test_record_to_dict_serializable():
    """AttestationRecord.to_dict() must be JSON-serializable."""
    engine = AttestationEngine()
    record = engine.attest("mod_ce", "h", "a", False, "ce_text")
    d = record.to_dict()
    json_str = json.dumps(d)
    assert "commitment" in json_str
    assert "UNSAT" in json_str or "SAT" in json_str


def test_timestamp_is_recent():
    """Attestation timestamp must be a recent Unix timestamp."""
    import time

    engine = AttestationEngine()
    record = engine.attest("mod_safe", "h", "a", True, None)
    assert abs(record.timestamp - time.time()) < 5.0
