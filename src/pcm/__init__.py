"""
src/pcm/__init__.py
-------------------
Proof-Carrying Modification (PCM) — public API.
"""

from .certificate import (
    CertificateStore,
    CertVerifyResult,
    PCMCertificate,
    generate_certificate,
    verify_certificate,
)
from .proof_checker import CheckResult, ProofChecker, SymbolicEnv, Verdict
from .proof_generator import GeneratedProof, ProofGenerator

__all__ = [
    # Certificate
    "CertVerifyResult",
    "CertificateStore",
    "PCMCertificate",
    "generate_certificate",
    "verify_certificate",
    # Checker
    "CheckResult",
    "ProofChecker",
    "SymbolicEnv",
    "Verdict",
    # Generator
    "GeneratedProof",
    "ProofGenerator",
]
