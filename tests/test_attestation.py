"""tests/test_attestation.py — Feature 3: Asymmetric Cryptographic Attestation (Ed25519)"""

import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.core.attestation import (
    AttestationEngine,
    AttestationRecord,
    _generate_keypair,
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
    # Ed25519 signature is 64 bytes → 88 base64 chars
    assert len(record.commitment) == 88
    assert record.public_key_pem.startswith("-----BEGIN PUBLIC KEY-----")
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
    """Modifying the result field must invalidate the Ed25519 signature."""
    engine = AttestationEngine()
    record = engine.attest("mod_h1", "h1", "h2", True, None)
    tampered = AttestationRecord(
        modification_id=record.modification_id,
        program_hash=record.program_hash,
        axiom_hash=record.axiom_hash,
        result="SAT",  # changed from UNSAT
        ce_hash=record.ce_hash,
        timestamp=record.timestamp,
        commitment=record.commitment,
        public_key_pem=record.public_key_pem,
    )
    assert engine.verify(tampered) is False


def test_tampered_program_hash_fails():
    """Modifying program_hash must invalidate the Ed25519 signature."""
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
        public_key_pem=record.public_key_pem,
    )
    assert engine.verify(tampered) is False


def test_different_keys_produce_different_commitments():
    """Two engines with different keypairs must produce different signatures."""
    priv1, _ = _generate_keypair()
    priv2, _ = _generate_keypair()
    engine1 = AttestationEngine(private_key=priv1)
    engine2 = AttestationEngine(private_key=priv2)
    r1 = engine1.attest("mod_e1", "h", "a", True, None)
    r2 = engine2.attest("mod_e2", "h", "a", True, None)
    assert r1.commitment != r2.commitment


def test_cross_engine_verification_fails():
    """A record from engine1 must not verify under engine2's public key."""
    priv1, _ = _generate_keypair()
    priv2, pub2 = _generate_keypair()
    engine1 = AttestationEngine(private_key=priv1)
    engine2 = AttestationEngine(private_key=priv2)
    record = engine1.attest("mod_e1b", "h", "a", True, None)
    # Verify using engine2's public key — must fail
    from src.core.attestation import _serialize_public_key
    pub2_pem = _serialize_public_key(pub2)
    assert engine2.verify_with_public_key(record, pub2_pem) is False


def test_verify_with_embedded_public_key():
    """Any holder of the public key embedded in the record can verify it."""
    engine = AttestationEngine()
    record = engine.attest("mod_pub", "h", "a", True, None)
    # Verify using the public key embedded in the record (third-party verification)
    assert engine.verify_with_public_key(record, record.public_key_pem) is True


def test_key_rotation():
    """After rotation, old records verify with old key, new records with new key."""
    priv_old, pub_old = _generate_keypair()
    priv_new, _ = _generate_keypair()
    engine = AttestationEngine(private_key=priv_old)

    old_record = engine.attest("mod_old", "h", "a", True, None)
    engine.rotate_key(priv_new)
    new_record = engine.attest("mod_new", "h", "a", True, None)

    # Old record verifies with its embedded public key
    assert engine.verify_with_public_key(old_record, old_record.public_key_pem) is True
    # New record verifies with its embedded public key
    assert engine.verify_with_public_key(new_record, new_record.public_key_pem) is True
    # Old record does NOT verify with new public key
    assert engine.verify_with_public_key(old_record, new_record.public_key_pem) is False


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
    assert "public_key_pem" in json_str
    assert "UNSAT" in json_str or "SAT" in json_str


def test_timestamp_is_recent():
    """Attestation timestamp must be a recent Unix timestamp."""
    import time

    engine = AttestationEngine()
    record = engine.attest("mod_safe", "h", "a", True, None)
    assert abs(record.timestamp - time.time()) < 5.0


def test_public_key_pem_exported():
    """public_key_pem() must return a valid PEM string."""
    engine = AttestationEngine()
    pem = engine.public_key_pem()
    assert pem.startswith("-----BEGIN PUBLIC KEY-----")
    assert "-----END PUBLIC KEY-----" in pem


def test_asymmetric_property():
    """Verify that the scheme is asymmetric: public key alone cannot forge."""
    priv, pub = _generate_keypair()
    engine = AttestationEngine(private_key=priv)
    record = engine.attest("mod_asym", "h", "a", True, None)

    # Forge attempt: create a record with tampered data but same commitment
    forged = AttestationRecord(
        modification_id=record.modification_id,
        program_hash="forged_hash",
        axiom_hash=record.axiom_hash,
        result=record.result,
        ce_hash=record.ce_hash,
        timestamp=record.timestamp,
        commitment=record.commitment,  # reuse original signature
        public_key_pem=record.public_key_pem,
    )
    # Must fail — signature covers the payload, not just the public key
    assert engine.verify(forged) is False
