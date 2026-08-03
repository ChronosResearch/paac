# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned Core) project.
# See LICENSE for terms.


class PAACError(Exception):
    """Base exception for PAAC"""


class VerificationError(PAACError):
    """Raised when safety verification fails or times out"""


class CompilationError(PAACError):
    """Raised when SIL compilation or parsing fails"""


class SafetyViolationError(PAACError):
    """Raised when a runtime safety violation occurs"""


class AgentError(PAACError):
    """Raised when the Inner Agent fails or hallucinates"""


class SelfHealingError(PAACError):
    """Raised when self-healing recovery fails"""


class GroundingError(PAACError):
    """Raised when truthfulness or grounding constraints are violated"""


class ConfigurationError(PAACError):
    """Raised when PAAC is misconfigured (e.g. empty or missing axiom set)"""
