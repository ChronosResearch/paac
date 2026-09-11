# Copyright 2026 Shashank Kumar
# SPDX-License-Identifier: Apache-2.0
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


class PreconditionUnsatisfiableError(PAACError):
    """Raised when a submitted precondition is unsatisfiable on its own.

    An unsatisfiable precondition (e.g. "1 == 0", "x != x") makes every
    verification query vacuously UNSAT: Z3 conjoins the precondition with the
    axiom-violation disjunction, and False AND anything is False, so the
    solver reports "safe" regardless of what the modification actually does.
    This is a distinct failure mode from a compilation error or a genuine
    verification failure, so it gets its own exception type rather than being
    folded into VerificationError or CompilationError.
    """

class AxiomNotEncodableError(PAACError):
    """Raised when an axiom that targets the function under verification cannot
    be encoded, because it references state the function never binds and the
    axiom declares no default for it.

    This exists to make a fail-open path fail closed. Previously such an axiom
    was classified as "inapplicable", logged at DEBUG, and dropped from the
    violation disjunction. When every applicable axiom was dropped that way,
    `_verify_inner` found no violation flags at all and returned safe=True
    *without ever invoking the solver*, so a modification could be accepted
    having been checked against nothing. See AUDIT_FINDINGS.md C-03.

    An axiom naming a variable the function does not bind is one of two things,
    and neither is grounds for silently continuing:

      * a configuration error, such as a typo in `config/axioms.yaml`, or an
        axiom aimed at functions it does not fit, or
      * an axiom over state that only conditionally materialises, such as the
        `exit_called` and `network_calls` sentinels, in which case the axiom
        must declare the value to assume when the state is absent, via the
        `defaults` key.

    Distinct from VerificationError because nothing about the *submission* is
    wrong: the verifier could not evaluate its own policy. The operator has to
    fix the axiom set, not the agent its code.
    """
