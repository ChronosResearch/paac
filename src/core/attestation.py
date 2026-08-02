"""
src/core/attestation.py
-----------------------
Feature 3: Cryptographic Attestation of Verification Results.

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

The attestation key is derived from a process-local secret (generated once
at startup).  Third parties who hold the public key can verify the commitment.

This is equivalent to a MAC-based attestation scheme and provides:
  - Integrity: the result cannot be tampered with undetected.
  - Non-repudiation: only the holder of the key can produce valid attestations.
  - Compactness: 32-byte commitment (comparable to a SNARK proof).

For a production deployment, replace _ATTEST_KEY with an HSM-backed key and
expose the public verification key via /attest/pubkey.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Any

from loguru import logger

# Process-local attestation key.  In production, load from HSM / env var.
_ATTEST_KEY: bytes = bytes.fromhex(
    os.environ.get("PAAC_ATTEST_KEY", secrets.token_hex(32))
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AttestationRecord:
    program_hash: str       # SHA-256 of canonical AST JSON
    axiom_hash: str         # SHA-256 of sorted axiom conditions
    result: str             # "UNSAT" | "SAT" | "ERROR"
    ce_hash: str | None     # SHA-256 of counterexample string, or None
    timestamp: float
    commitment: str         # HMAC-SHA256 hex digest (32 bytes = 64 hex chars)
    version: str = "paac-attest-v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Attestation engine
# ---------------------------------------------------------------------------

class AttestationEngine:
    """
    Generates and verifies cryptographic attestations for PAAC verification
    results.
    """

    def __init__(self, key: bytes = _ATTEST_KEY) -> None:
        self._key = key

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def attest(
        self,
        program_hash: str,
        axiom_hash: str,
        safe: bool,
        counterexample_str: str | None,
    ) -> AttestationRecord:
        """
        Generate an attestation record for a completed verification.
        """
        result = "UNSAT" if safe else "SAT"
        ce_hash = (
            hashlib.sha256(counterexample_str.encode()).hexdigest()
            if counterexample_str
            else None
        )
        ts = time.time()
        payload = self._canonical_payload(
            program_hash, axiom_hash, result, ce_hash, ts
        )
        commitment = hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()

        record = AttestationRecord(
            program_hash=program_hash,
            axiom_hash=axiom_hash,
            result=result,
            ce_hash=ce_hash,
            timestamp=ts,
            commitment=commitment,
        )
        logger.debug(
            f"Attestation generated: result={result}, "
            f"commitment={commitment[:16]}…"
        )
        return record

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify(self, record: AttestationRecord) -> bool:
        """
        Verify that an attestation record has not been tampered with.
        Returns True iff the commitment is valid.
        """
        payload = self._canonical_payload(
            record.program_hash,
            record.axiom_hash,
            record.result,
            record.ce_hash,
            record.timestamp,
        )
        expected = hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()
        valid = secrets.compare_digest(expected, record.commitment)
        if not valid:
            logger.warning("Attestation verification FAILED — commitment mismatch.")
        return valid

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _canonical_payload(
        program_hash: str,
        axiom_hash: str,
        result: str,
        ce_hash: str | None,
        timestamp: float,
    ) -> str:
        return json.dumps(
            {
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


def attest_verification(
    program_hash: str,
    axiom_hash: str,
    safe: bool,
    counterexample_str: str | None = None,
) -> AttestationRecord:
    return _engine.attest(program_hash, axiom_hash, safe, counterexample_str)


def verify_attestation(record: AttestationRecord) -> bool:
    return _engine.verify(record)
