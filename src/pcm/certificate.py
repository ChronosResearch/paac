"""
src/pcm/certificate.py
----------------------
Proof-Carrying Modification (PCM) — Certificate System.

Every accepted proof produces a PCMCertificate signed with Ed25519
(paper §4.3).  Certificates are stored in an append-only JSONL audit log.
Third parties can verify certificates using only PAAC's public key —
no shared secret required.

Certificate format:
  {
    "version": "pcm-2.0",
    "modification_id": "<unique id>",
    "code_hash": "<sha256 of SIL source>",
    "proof_hash": "<sha256 of canonical proof JSON>",
    "agent_id": "<submitting agent identity>",
    "timestamp": "<ISO-8601>",
    "axioms_covered": ["<axiom_id>", ...],
    "public_key_pem": "<PEM Ed25519 public key>",
    "paac_signature": "<base64 Ed25519 signature>"
  }

Key management mirrors attestation.py:
  - PAAC_ATTEST_PRIVATE_KEY env var (PEM Ed25519) — shared with attestation engine.
  - If unset, an ephemeral keypair is generated at module load time.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
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

_CERT_VERSION = "pcm-2.0"
_DEFAULT_LOG_PATH = os.environ.get("PAAC_PCM_LOG", "pcm_audit.jsonl")


# ---------------------------------------------------------------------------
# Key management — reuse PAAC_ATTEST_PRIVATE_KEY if available
# ---------------------------------------------------------------------------


def _load_or_generate_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    priv_pem = os.environ.get("PAAC_ATTEST_PRIVATE_KEY", "")
    if priv_pem:
        try:
            priv = load_pem_private_key(priv_pem.encode(), password=None)
            if isinstance(priv, Ed25519PrivateKey):
                return priv, priv.public_key()
        except Exception:
            pass
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key()


_PRIVATE_KEY, _PUBLIC_KEY = _load_or_generate_keypair()


def _pub_pem() -> str:
    return _PUBLIC_KEY.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()


# ---------------------------------------------------------------------------
# Certificate data model
# ---------------------------------------------------------------------------


@dataclass
class PCMCertificate:
    """An Ed25519-signed PCM certificate (paper §4.3)."""

    version: str
    modification_id: str
    code_hash: str
    proof_hash: str
    agent_id: str
    timestamp: str
    axioms_covered: list[str]
    public_key_pem: str
    paac_signature: str  # base64-encoded Ed25519 signature

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "modification_id": self.modification_id,
            "code_hash": self.code_hash,
            "proof_hash": self.proof_hash,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "axioms_covered": self.axioms_covered,
            "public_key_pem": self.public_key_pem,
            "paac_signature": self.paac_signature,
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PCMCertificate:
        return cls(
            version=d.get("version", _CERT_VERSION),
            modification_id=d["modification_id"],
            code_hash=d["code_hash"],
            proof_hash=d["proof_hash"],
            agent_id=d["agent_id"],
            timestamp=d["timestamp"],
            axioms_covered=d.get("axioms_covered", []),
            public_key_pem=d.get("public_key_pem", ""),
            paac_signature=d["paac_signature"],
        )


# ---------------------------------------------------------------------------
# Certificate verification result
# ---------------------------------------------------------------------------


@dataclass
class CertVerifyResult:
    valid: bool
    modification_id: str
    checks_passed: list[str] = field(default_factory=list)
    checks_failed: list[str] = field(default_factory=list)
    message: str = ""


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _hash_proof(proof: dict[str, Any]) -> str:
    canonical = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _canonical_payload(
    modification_id: str,
    code_hash: str,
    proof_hash: str,
    agent_id: str,
    timestamp: str,
    axioms_covered: list[str],
) -> str:
    payload = {
        "modification_id": modification_id,
        "code_hash": code_hash,
        "proof_hash": proof_hash,
        "agent_id": agent_id,
        "timestamp": timestamp,
        "axioms_covered": sorted(axioms_covered),
        "version": _CERT_VERSION,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _sign(canonical: str) -> str:
    """Sign SHA-256 digest of canonical payload with Ed25519 private key."""
    digest = hashlib.sha256(canonical.encode()).digest()
    sig_bytes = _PRIVATE_KEY.sign(digest)
    return base64.b64encode(sig_bytes).decode()


# ---------------------------------------------------------------------------
# Certificate generation
# ---------------------------------------------------------------------------


def generate_certificate(
    modification_id: str,
    code: str,
    proof: dict[str, Any],
    agent_id: str,
    axioms_covered: list[str] | None = None,
) -> PCMCertificate:
    """
    Generate an Ed25519-signed PCM certificate for an accepted proof (paper §4.3).

    Args:
        modification_id: Unique identifier for this modification.
        code: SIL source code that was proved safe.
        proof: The PPL proof dict that was accepted.
        agent_id: Identity of the submitting agent.
        axioms_covered: List of axiom IDs covered by the proof.

    Returns:
        A signed PCMCertificate.
    """
    code_hash = _hash_code(code)
    proof_hash = _hash_proof(proof)
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    covered = sorted(axioms_covered or proof.get("axioms", []))

    canonical = _canonical_payload(
        modification_id, code_hash, proof_hash, agent_id, timestamp, covered
    )
    signature = _sign(canonical)

    return PCMCertificate(
        version=_CERT_VERSION,
        modification_id=modification_id,
        code_hash=code_hash,
        proof_hash=proof_hash,
        agent_id=agent_id,
        timestamp=timestamp,
        axioms_covered=covered,
        public_key_pem=_pub_pem(),
        paac_signature=signature,
    )


# ---------------------------------------------------------------------------
# Certificate verification
# ---------------------------------------------------------------------------


def verify_certificate(cert: PCMCertificate) -> CertVerifyResult:
    """
    Verify a PCM certificate using the Ed25519 public key embedded in the record.

    Checks:
      1. Version matches expected PCM version.
      2. Ed25519 signature is valid (certificate not tampered with).
      3. Modification ID is non-empty.
      4. Code hash and proof hash are valid SHA-256 hex strings.

    Third parties need only the public key — no shared secret required.
    """
    passed: list[str] = []
    failed: list[str] = []

    # Check 1: Version
    if cert.version == _CERT_VERSION:
        passed.append("version")
    else:
        failed.append("version")

    # Check 2: Ed25519 signature
    canonical = _canonical_payload(
        cert.modification_id,
        cert.code_hash,
        cert.proof_hash,
        cert.agent_id,
        cert.timestamp,
        cert.axioms_covered,
    )
    sig_valid = False
    pub_pem = cert.public_key_pem or _pub_pem()
    try:
        pub = load_pem_public_key(pub_pem.encode())
        if isinstance(pub, Ed25519PublicKey):
            digest = hashlib.sha256(canonical.encode()).digest()
            pub.verify(base64.b64decode(cert.paac_signature), digest)
            sig_valid = True
    except (InvalidSignature, Exception):
        sig_valid = False

    if sig_valid:
        passed.append("ed25519_signature")
    else:
        failed.append("ed25519_signature")

    # Check 3: Non-empty modification ID
    if cert.modification_id.strip():
        passed.append("modification_id_nonempty")
    else:
        failed.append("modification_id_nonempty")

    # Check 4: Hash format (64-char hex)
    _hex64 = re.compile(r"^[0-9a-f]{64}$")
    if _hex64.match(cert.code_hash):
        passed.append("code_hash_format")
    else:
        failed.append("code_hash_format")

    if _hex64.match(cert.proof_hash):
        passed.append("proof_hash_format")
    else:
        failed.append("proof_hash_format")

    valid = len(failed) == 0
    return CertVerifyResult(
        valid=valid,
        modification_id=cert.modification_id,
        checks_passed=passed,
        checks_failed=failed,
        message="Certificate valid." if valid else f"Failed checks: {failed}",
    )


# ---------------------------------------------------------------------------
# Append-only audit log
# ---------------------------------------------------------------------------


class CertificateStore:
    """
    Append-only JSONL certificate store.

    Each line is a JSON-serialised PCMCertificate.  The log is append-only:
    existing entries are never modified or deleted.
    """

    def __init__(self, log_path: str = _DEFAULT_LOG_PATH) -> None:
        self._log_path = Path(log_path)

    def save(self, cert: PCMCertificate) -> None:
        """Append *cert* to the audit log."""
        with self._log_path.open("a", encoding="utf-8") as fh:
            fh.write(cert.to_json(indent=None) + "\n")

    def query(self, modification_id: str) -> PCMCertificate | None:
        """Return the first certificate matching *modification_id*, or None."""
        if not self._log_path.exists():
            return None
        with self._log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if d.get("modification_id") == modification_id:
                        return PCMCertificate.from_dict(d)
                except (json.JSONDecodeError, KeyError):
                    continue
        return None

    def all_certificates(self) -> list[PCMCertificate]:
        """Return all certificates in the log."""
        certs: list[PCMCertificate] = []
        if not self._log_path.exists():
            return certs
        with self._log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    certs.append(PCMCertificate.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError):
                    continue
        return certs

    def count(self) -> int:
        """Return the number of certificates in the log."""
        return len(self.all_certificates())
