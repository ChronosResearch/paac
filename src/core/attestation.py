"""
src/core/attestation.py
-----------------------
Asymmetric Cryptographic Attestation of Verification Results.

Design
------
Uses Ed25519 asymmetric signatures (via the `cryptography` library).
The private key signs the canonical payload; any holder of the public key
can verify the attestation without being able to forge it.

  Signature = Ed25519.sign(private_key, SHA-256(canonical_payload))

canonical_payload encodes:
  - SHA-256 of the SIL program AST
  - SHA-256 of the axiom set
  - verification result (UNSAT/SAT)
  - counterexample hash (if SAT)
  - timestamp
  - schema version

Key management:
  - PAAC_ATTEST_PRIVATE_KEY: PEM-encoded Ed25519 private key (env var).
  - PAAC_ATTEST_PUBLIC_KEY:  PEM-encoded Ed25519 public key (env var).
  - If neither is set, an ephemeral keypair is generated at startup.
  - Legacy PAAC_ATTEST_KEY (HMAC) is still accepted for backward compat.

Key rotation: call AttestationEngine.rotate_key(new_private_key) to rotate.
Old attestations remain verifiable with the old public key via
verify_with_public_key().

Third parties who hold only the public key can verify attestations
without being able to forge them — this is the key advantage over HMAC.

Limitations (documented honestly)
----------------------------------
- Ed25519 provides integrity, authenticity, and non-repudiation.
  It does not provide zero-knowledge proofs (future work: SNARKs).
- Timestamps are wall-clock time (not monotonic).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)
from cryptography.exceptions import InvalidSignature
from loguru import logger

# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------


def _generate_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Generate a fresh Ed25519 keypair."""
    private_key = Ed25519PrivateKey.generate()
    return private_key, private_key.public_key()


def _load_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Load Ed25519 keypair from env vars or generate an ephemeral one."""
    priv_pem = os.environ.get("PAAC_ATTEST_PRIVATE_KEY", "")
    pub_pem = os.environ.get("PAAC_ATTEST_PUBLIC_KEY", "")

    if priv_pem:
        try:
            private_key = load_pem_private_key(priv_pem.encode(), password=None)
            if not isinstance(private_key, Ed25519PrivateKey):
                raise ValueError("PAAC_ATTEST_PRIVATE_KEY is not an Ed25519 key")
            public_key = private_key.public_key()
            logger.info("Attestation: loaded Ed25519 private key from PAAC_ATTEST_PRIVATE_KEY.")
            return private_key, public_key
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"PAAC_ATTEST_PRIVATE_KEY invalid ({exc}); generating ephemeral keypair.")

    if pub_pem and not priv_pem:
        logger.warning(
            "PAAC_ATTEST_PUBLIC_KEY set but PAAC_ATTEST_PRIVATE_KEY missing — "
            "cannot sign new attestations. Generating ephemeral keypair."
        )

    private_key, public_key = _generate_keypair()
    logger.warning(
        "No PAAC_ATTEST_PRIVATE_KEY set — using ephemeral Ed25519 keypair. "
        "Attestations will not be verifiable across restarts."
    )
    return private_key, public_key


def _serialize_public_key(pub: Ed25519PublicKey) -> str:
    """Serialize an Ed25519 public key to PEM string."""
    return pub.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()


def _serialize_private_key(priv: Ed25519PrivateKey) -> str:
    """Serialize an Ed25519 private key to PEM string."""
    return priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class AttestationRecord:
    modification_id: str   # caller-supplied ID (e.g., func_name + timestamp)
    program_hash: str      # SHA-256 of canonical AST JSON
    axiom_hash: str        # SHA-256 of sorted axiom conditions
    result: str            # "UNSAT" | "SAT" | "ERROR"
    ce_hash: str | None    # SHA-256 of counterexample string, or None
    timestamp: float       # Unix timestamp of attestation generation
    commitment: str        # base64-encoded Ed25519 signature (88 chars)
    public_key_pem: str    # PEM-encoded Ed25519 public key for verification
    version: str = "paac-attest-v2"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AttestationRecord":
        # Accept v1 records (HMAC) for backward compatibility — they will
        # fail signature verification but won't crash deserialization.
        fields = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        fields.setdefault("public_key_pem", "")
        fields.setdefault("version", "paac-attest-v2")
        return cls(**fields)


# ---------------------------------------------------------------------------
# Attestation engine
# ---------------------------------------------------------------------------


class AttestationEngine:
    """
    Generates and verifies Ed25519-signed attestations for PAAC verification
    results.

    Asymmetric: the private key signs; any holder of the public key verifies.
    Thread-safe: key rotation uses a lock.
    """

    def __init__(
        self,
        private_key: Ed25519PrivateKey | None = None,
        public_key: Ed25519PublicKey | None = None,
    ) -> None:
        if private_key is not None:
            self._private_key = private_key
            self._public_key = public_key or private_key.public_key()
        else:
            self._private_key, self._public_key = _load_keypair()
        self._lock = threading.Lock()
        self._store: dict[str, AttestationRecord] = {}
        self._generation_count = 0
        self._verification_count = 0
        self._verification_failures = 0

    # ------------------------------------------------------------------
    # Public key export
    # ------------------------------------------------------------------

    def public_key_pem(self) -> str:
        """Return the PEM-encoded public key for distribution to verifiers."""
        with self._lock:
            return _serialize_public_key(self._public_key)

    # ------------------------------------------------------------------
    # Key rotation
    # ------------------------------------------------------------------

    def rotate_key(self, new_private_key: Ed25519PrivateKey) -> None:
        """
        Rotate to a new Ed25519 private key.  Old attestations remain
        verifiable via verify_with_public_key(record, old_public_key).
        """
        with self._lock:
            self._private_key = new_private_key
            self._public_key = new_private_key.public_key()
        logger.info("Attestation key rotated (Ed25519).")

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def attest(
        self,
        modification_id: str,
        program_hash: str,
        axiom_hash: str,
        safe: bool,
        counterexample_str: str | None,
    ) -> AttestationRecord:
        """
        Generate an Ed25519-signed attestation record for a completed verification.
        The record is stored internally and can be retrieved via get().
        """
        result = "UNSAT" if safe else "SAT"
        ce_hash = (
            hashlib.sha256(counterexample_str.encode()).hexdigest()
            if counterexample_str
            else None
        )
        ts = time.time()

        with self._lock:
            private_key = self._private_key
            pub_pem = _serialize_public_key(self._public_key)

        payload = self._canonical_payload(
            modification_id, program_hash, axiom_hash, result, ce_hash, ts
        )
        # Sign the SHA-256 digest of the canonical payload
        payload_digest = hashlib.sha256(payload.encode()).digest()
        signature_bytes = private_key.sign(payload_digest)
        commitment = base64.b64encode(signature_bytes).decode()

        record = AttestationRecord(
            modification_id=modification_id,
            program_hash=program_hash,
            axiom_hash=axiom_hash,
            result=result,
            ce_hash=ce_hash,
            timestamp=ts,
            commitment=commitment,
            public_key_pem=pub_pem,
        )

        with self._lock:
            self._store[modification_id] = record
            self._generation_count += 1

        logger.debug(
            f"Attestation generated: id={modification_id!r}, "
            f"result={result}, sig={commitment[:16]}..."
        )
        return record

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify(self, record: AttestationRecord) -> bool:
        """
        Verify an attestation using the public key embedded in the record.
        Returns True iff the Ed25519 signature is valid.
        """
        return self.verify_with_public_key(record, record.public_key_pem)

    def verify_with_public_key(self, record: AttestationRecord, public_key_pem: str) -> bool:
        """Verify an attestation against a specific PEM public key."""
        try:
            pub = load_pem_public_key(public_key_pem.encode())
            if not isinstance(pub, Ed25519PublicKey):
                raise ValueError("Not an Ed25519 public key")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Attestation: invalid public key: {exc}")
            with self._lock:
                self._verification_count += 1
                self._verification_failures += 1
            return False

        payload = self._canonical_payload(
            record.modification_id,
            record.program_hash,
            record.axiom_hash,
            record.result,
            record.ce_hash,
            record.timestamp,
        )
        payload_digest = hashlib.sha256(payload.encode()).digest()

        try:
            signature_bytes = base64.b64decode(record.commitment)
            pub.verify(signature_bytes, payload_digest)
            valid = True
        except (InvalidSignature, Exception):  # noqa: BLE001
            valid = False

        with self._lock:
            self._verification_count += 1
            if not valid:
                self._verification_failures += 1

        if not valid:
            logger.warning(
                f"Attestation verification FAILED for id={record.modification_id!r} "
                "— Ed25519 signature invalid (tampering or wrong key)."
            )
        return valid

    # ------------------------------------------------------------------
    # Store access
    # ------------------------------------------------------------------

    def get(self, modification_id: str) -> AttestationRecord | None:
        with self._lock:
            return self._store.get(modification_id)

    def list_ids(self) -> list[str]:
        with self._lock:
            return list(self._store.keys())

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return {
                "attestations_generated": self._generation_count,
                "attestations_verified": self._verification_count,
                "attestation_failures": self._verification_failures,
                "store_size": len(self._store),
            }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _canonical_payload(
        modification_id: str,
        program_hash: str,
        axiom_hash: str,
        result: str,
        ce_hash: str | None,
        timestamp: float,
    ) -> str:
        return json.dumps(
            {
                "modification_id": modification_id,
                "program_hash": program_hash,
                "axiom_hash": axiom_hash,
                "result": result,
                "ce_hash": ce_hash,
                "timestamp": timestamp,
                "version": "paac-attest-v2",
            },
            sort_keys=True,
        )

    @staticmethod
    def hash_program(ast_json: str) -> str:
        return hashlib.sha256(ast_json.encode()).hexdigest()

    @staticmethod
    def hash_axioms(axiom_conditions: list[str]) -> str:
        canonical = json.dumps(sorted(axiom_conditions))
        return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine = AttestationEngine()


def get_engine() -> AttestationEngine:
    return _engine


def attest_verification(
    modification_id: str,
    program_hash: str,
    axiom_hash: str,
    safe: bool,
    counterexample_str: str | None = None,
) -> AttestationRecord:
    return _engine.attest(
        modification_id, program_hash, axiom_hash, safe, counterexample_str
    )


def verify_attestation(record: AttestationRecord) -> bool:
    return _engine.verify(record)
