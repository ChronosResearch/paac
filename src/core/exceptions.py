# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned Core) project.
# See LICENSE for terms.

class PAACError(Exception):
    """Base exception for PAAC"""
    pass

class VerificationError(PAACError):
    """Raised when safety verification fails or times out"""
    pass

class CompilationError(PAACError):
    """Raised when SIL compilation or parsing fails"""
    pass

class SafetyViolationError(PAACError):
    """Raised when a runtime safety violation occurs"""
    pass

class AgentError(PAACError):
    """Raised when the Inner Agent fails or hallucinates"""
    pass

class SelfHealingError(PAACError):
    """Raised when self-healing recovery fails"""
    pass

class GroundingError(PAACError):
    """Raised when truthfulness or grounding constraints are violated"""
    pass
