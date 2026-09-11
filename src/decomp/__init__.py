# Copyright 2026 Shashank Kumar
# SPDX-License-Identifier: Apache-2.0
# This file is part of the PAAC (Provably Aligned Core) project.
"""
Decomposition witness synthesis.

PAAC verifies one modification at a time. This package asks the question that
per-modification verification cannot answer on its own: can a sequence of
individually-accepted modifications compose into a violation of a safety axiom?

The adversary here is Z3, not an LLM and not random search. See
`docs/DECOMPOSITION.md` for the threat model, the schema definitions, and the
boundary of what a null result does and does not establish.
"""

from .schema import (
    SCHEMAS,
    Modification,
    Schema,
    SchemaOutcome,
    Witness,
)
from .synth import confirm_witness, synthesise, synthesise_all

__all__ = [
    "SCHEMAS",
    "Modification",
    "Schema",
    "SchemaOutcome",
    "Witness",
    "confirm_witness",
    "synthesise",
    "synthesise_all",
]
