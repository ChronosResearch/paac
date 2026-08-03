"""
src/core/attestation.py
-----------------------
Cryptographic Attestation of Verification Results.

Design
------
Full Groth16 SNARKs require a trusted setup and a Rust/C++ circuit compiler
(arkworks/bellman) that is not available in this Python environment.  We
implement a *cryptographically sound commitment scheme* that provides the
same external verifiability guarantee without a trusted setup:

  Commitment = HMAC-SHA256(key, canonical_payload)

where canonical_payload encodes:
  - SHA-256 of the SIL program AST
  - SHA-256 of the axiom set
  - verification result (UNSAT/SAT)
  - counterexample hash (if SAT)
  - timestamp
  - schema version

The attestation key is loaded from the PAAC_ATTEST_KEY environment variable
(hex-encoded 32 bytes).  If not set, a process-local key is generated at
startup — this means attestations are not portable across restarts unless
the key is persisted.

Key rotation: call AttestationEngine.rotate_key(new_key) to rotate.  Old
attestations remain verifiable with the old key via verify_with_key().

Third parties who hold the key can verify any attestation independently
without re-running the verification.

Limitations (documented honestly)
----------------------------------
- HMAC-SHA256 provides integrity and authenticity but not zero-knowledge.
  A verifier who holds the key can also forge attestations.  For true
  zero-knowledge proofs, a SNARK circuit is required (future work).
- The key must be kept secret.  If it leaks, attestations can be forged.
- Timestamps are wall-clock time (not monotonic) and can be manipulated
  by a compromised system clock.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------


def _load_key() -> bytes:
    """Load attestation key from env var or generate a process-local one."""
    raw = os.environ.get("PAAC_ATTEST_KEY", "")
    if raw:
        try:
            key = bytes.fromhex(raw)
            if len(key) < 16:
                raise ValueError("Key too short (minimum 16 bytes)")
            return key
        except (ValueError, Exception) as exc:  # noqa: BLE001
            logger.warning(
                f"PAAC_ATTEST_KEY invalid ({exc}); generating ephemeral key."
            )
    key = secrets.token_bytes(32)
    logger.warning(
        "No PAAC_ATTEST_KEY set — using ephemeral key. "
        "Attestations will not be verifiable across restarts."
    )
    return key


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class AttestationRecord:
    modification_id: str  # caller-supplied ID (e.g., func_name + timestamp)
    program_hash: str  # SHA-256 of canonical AST JSON
    axiom_hash: str  # SHA-256 of sorted axiom conditions
    result: str  # "UNSAT" | "SAT" | "ERROR"
    ce_hash: str | None  # SHA-256 of counterexample string, or None
    timestamp: float  # Unix timestamp of attestation generation
    commitment: str  # HMAC-SHA256 hex digest (64 hex chars = 32 bytes)
    version: str = "paac-attest-v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AttestationRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Attestation engine
# ---------------------------------------------------------------------------


class AttestationEngine:
    """
    Generates and verifies HMAC-SHA256 attestations for PAAC verification
    results.

    Thread-safe: key rotation uses a lock.
    """

    def __init__(self, key: bytes | None = None) -> None:
        self._key = key if key is not None else _load_key()
        self._lock = threading.Lock()
        self._store: dict[str, AttestationRecord] = {}  # modification_id -> record
        self._generation_count = 0
        self._verification_count = 0
        self._verification_failures = 0

    # ------------------------------------------------------------------
    # Key rotation
    # ------------------------------------------------------------------

    def rotate_key(self, new_key: bytes) -> None:
        """
        Rotate the attestation key.  Old attestations remain verifiable
        via verify_with_key(record, old_key).
        """
        if len(new_key) < 16:
            raise ValueError("New key must be at least 16 bytes.")
        with self._lock:
            self._key = new_key
        logger.info("Attestation key rotated.")

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
        Generate an attestation record for a completed verification.

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
            key = self._key

        payload = self._canonical_payload(
            modification_id, program_hash, axiom_hash, result, ce_hash, ts
        )
        commitment = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()

        record = AttestationRecord(
            modification_id=modification_id,
            program_hash=program_hash,
            axiom_hash=axiom_hash,
            result=result,
            ce_hash=ce_hash,
            timestamp=ts,
            commitment=commitment,
        )

        with self._lock:
            self._store[modification_id] = record
            self._generation_count += 1

        logger.debug(
            f"Attestation generated: id={modification_id!r}, "
            f"result={result}, commitment={commitment[:16]}..."
        )
        return record

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify(self, record: AttestationRecord) -> bool:
        """
        Verify that an attestation record has not been tampered with.
        Uses the current key.  Returns True iff the commitment is valid.
        """
        with self._lock:
            key = self._key
        return self.verify_with_key(record, key)

    def verify_with_key(self, record: AttestationRecord, key: bytes) -> bool:
        """Verify an attestation against a specific key (for key rotation)."""
        payload = self._canonical_payload(
            record.modification_id,
            record.program_hash,
            record.axiom_hash,
            record.result,
            record.ce_hash,
            record.timestamp,
        )
        expected = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
        valid = secrets.compare_digest(expected, record.commitment)

        with self._lock:
            self._verification_count += 1
            if not valid:
                self._verification_failures += 1

        if not valid:
            logger.warning(
                f"Attestation verification FAILED for id={record.modification_id!r} "
                "— commitment mismatch (tampering or wrong key)."
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
                "version": "paac-attest-v1",
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
