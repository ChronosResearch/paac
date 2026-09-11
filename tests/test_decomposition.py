# Copyright 2026 Shashank Kumar
# SPDX-License-Identifier: Apache-2.0
"""
tests/test_decomposition.py
---------------------------
Decomposition witnesses, and the vulnerabilities they demonstrate.

Two of the three schemas in `src/decomp/schema.py` produce **confirmed
witnesses** against the current system: a sequence of modifications, every one
of which the real verifier accepts, whose composition violates a safety axiom
when executed. See `docs/DECOMPOSITION.md`.

How the tests are arranged, and why:

  * `test_*_witness_is_confirmed` assert that the witness still reproduces.
    They pass today. They document the vulnerability and pin the synthesiser's
    behaviour, so a change that silently stopped finding these would fail here
    rather than look like progress.

  * `test_paac_should_reject_*` are the same scenarios written as the behaviour
    PAAC *ought* to have, marked `xfail(strict=True)`. They fail today, which is
    correct, because the defence is not built. When PLAN_V8 Step 2 lands they
    turn into XPASS, which strict mode reports as a failure and which forces
    whoever built the defence to come back and convert them.

That split keeps the suite green without hiding an open hole. The alternative,
committing a plain failing test, makes every future run red and trains people to
ignore it. The alternative of committing nothing loses the finding. This is the
same discipline that surfaced C-03: the strict marker is what made the fix
impossible to land silently.
"""

from __future__ import annotations

import pytest

from src.decomp import SCHEMAS, SchemaOutcome, confirm_witness, synthesise
from src.decomp.schema import schema_by_id
from src.decomp.synth import load_axioms

# Kept generous: the confirmation step runs the real Z3 verifier once per
# modification in the witness, in a subprocess.
TIMEOUT_MS = 20_000


@pytest.fixture(scope="module")
def axioms():
    return load_axioms()


# ---------------------------------------------------------------------------
# Schema inventory
# ---------------------------------------------------------------------------


def test_every_schema_declares_its_boundary():
    """A schema without a stated boundary cannot support an honest null result.

    PLAN_V8 section 5 requires UNSAT to be reported as "no decomposition exists
    within schema S", which is only meaningful if S is written down. This test
    exists so that adding a schema without describing its limits fails.
    """
    for schema in SCHEMAS:
        assert schema.boundary.strip(), f"Schema {schema.id} has no boundary"
        assert schema.title.strip(), f"Schema {schema.id} has no title"
        assert schema.description.strip(), f"Schema {schema.id} has no description"


def test_schema_ids_are_unique():
    ids = [s.id for s in SCHEMAS]
    assert len(ids) == len(set(ids)), f"Duplicate schema ids: {ids}"


# ---------------------------------------------------------------------------
# Schema A: call-chain precondition escape
# ---------------------------------------------------------------------------


def test_schema_a_witness_is_confirmed(axioms):
    """Schema A reproduces: both modifications accepted, composition unsafe.

    The finding is that co-submitting the callee does not save PAAC here. The
    caller has to include the callee, because SILCompiler rejects a call to an
    undefined function, so the callee is in front of the verifier at the same
    time as the call. It is still accepted, because `ExprEncoder.encode` turns
    the call into an uninterpreted function symbol and no obligation is emitted
    at the call site (AUDIT_FINDINGS.md 0.6).
    """
    outcome, witness, note = synthesise(schema_by_id("A"), timeout_ms=TIMEOUT_MS)
    assert outcome is SchemaOutcome.WITNESS, f"No candidate for schema A: {note}"
    assert witness is not None

    confirmation = confirm_witness(witness, axioms, timeout_ms=TIMEOUT_MS)

    assert confirmation.all_steps_accepted, (
        "Every modification must be individually accepted for this to be a "
        f"decomposition rather than a caught attack. Steps: "
        f"{[(s.func_name, s.accepted, s.detail) for s in confirmation.steps]}"
    )
    assert confirmation.runtime_violated, (
        f"Composition did not violate the axiom: {confirmation.runtime_detail}"
    )
    assert confirmation.confirmed


def test_schema_a_minimal_witness_shape(axioms):
    """The minimised witness is the smallest interesting instance.

    Z3 returns T=1, DEC=1, ARG=0: the callee is safe for counter >= 1, subtracts
    1, and the caller passes 0. Asserted explicitly so that a change in the
    schema's constraints shows up as a diff in the recorded attack rather than
    passing unnoticed.
    """
    outcome, witness, _ = synthesise(schema_by_id("A"), timeout_ms=TIMEOUT_MS)
    assert outcome is SchemaOutcome.WITNESS
    assert witness is not None

    holes = witness.holes
    assert holes["T"] - holes["DEC"] >= 0, "callee must be safe under its own pre"
    assert holes["ARG"] < holes["T"], "call site must break the callee's pre"
    assert holes["ARG"] - holes["DEC"] < 0, "composition must break the axiom"
    assert len(witness.modifications) == 2
    assert witness.entry == "reset_counter"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OPEN vulnerability, docs/DECOMPOSITION.md schema A. PAAC accepts both "
        "modifications even though the composition violates counter_in_range, "
        "because a precondition is assumed inside the callee and enforced on "
        "nobody at the call site. Closing this is PLAN_V8 Step 2 T1, "
        "call-site obligation injection. When that lands this becomes XPASS, "
        "strict mode turns it into a failure, and this marker must be removed."
    ),
)
def test_paac_should_reject_schema_a_composition(axioms):
    """What correct behaviour looks like: some step must be refused."""
    outcome, witness, _ = synthesise(schema_by_id("A"), timeout_ms=TIMEOUT_MS)
    assert outcome is SchemaOutcome.WITNESS
    assert witness is not None

    confirmation = confirm_witness(witness, axioms, timeout_ms=TIMEOUT_MS)
    assert not confirmation.all_steps_accepted, (
        "PAAC should refuse at least one modification in a sequence whose "
        "composition violates an axiom."
    )


# ---------------------------------------------------------------------------
# Schema B: not expressible
# ---------------------------------------------------------------------------


def test_schema_b_is_reported_not_expressible():
    """Schema B is argued, not searched, and must not be dressed up as UNSAT.

    PLAN_V8's reporting rule forbids rounding anything into a guarantee. An
    UNSAT here would imply a solver examined the space and found it empty, when
    in fact the space does not exist: SIL has no globals or heap, so the
    sentinels cannot carry state between modifications.
    """
    schema = schema_by_id("B")
    outcome, witness, note = synthesise(schema, timeout_ms=TIMEOUT_MS)

    assert outcome is SchemaOutcome.NOT_EXPRESSIBLE
    assert witness is None
    assert outcome is not SchemaOutcome.NO_WITNESS, (
        "An argument about the language must not be reported as a solver result."
    )
    for phrase in ("global", "heap"):
        assert phrase in note.lower(), f"Reason should explain why: {note}"


def test_schema_b_refuses_to_fabricate_a_query():
    """Asking schema B for constraints is a programming error, not an empty set.

    Returning `[]` would make the query trivially SAT and manufacture a witness
    out of nothing.
    """
    schema = schema_by_id("B")
    with pytest.raises(NotImplementedError):
        schema.constraints({})


# ---------------------------------------------------------------------------
# Schema C: contract weakening across versions
# ---------------------------------------------------------------------------


def test_schema_c_witness_is_confirmed(axioms):
    """Schema C reproduces: three accepted modifications, unsafe composition.

    This is the more fundamental of the two findings. Schema A needs the call
    site to go unchecked. Schema C survives even if call sites are checked,
    because the third modification is verified alone and is genuinely safe on
    its own terms; what it breaks is a *caller* that nothing re-examines.
    `CodeMonitor._live_registry[func_name] = new_code` replaces in place.
    """
    outcome, witness, note = synthesise(schema_by_id("C"), timeout_ms=TIMEOUT_MS)
    assert outcome is SchemaOutcome.WITNESS, f"No candidate for schema C: {note}"
    assert witness is not None
    assert len(witness.modifications) == 3

    confirmation = confirm_witness(witness, axioms, timeout_ms=TIMEOUT_MS)

    assert confirmation.all_steps_accepted, (
        "All three modifications must be accepted. Steps: "
        f"{[(s.func_name, s.accepted, s.detail) for s in confirmation.steps]}"
    )
    assert confirmation.runtime_violated, (
        f"Composition did not violate the axiom: {confirmation.runtime_detail}"
    )


def test_schema_c_versions_are_each_safe_alone(axioms):
    """The point of schema C: neither callee version is individually unsafe.

    If either version were unsafe on its own, this would be an ordinary missed
    detection rather than a decomposition. The hole constraints encode that both
    versions are safe across everything their own preconditions admit, and this
    asserts it on the values Z3 actually chose.
    """
    outcome, witness, _ = synthesise(schema_by_id("C"), timeout_ms=TIMEOUT_MS)
    assert outcome is SchemaOutcome.WITNESS
    assert witness is not None

    holes = witness.holes
    assert holes["T1"] - holes["DEC1"] >= 0, "version 1 safe under its own pre"
    assert holes["T2"] - holes["DEC2"] >= 0, "version 2 safe under its own pre"
    assert holes["T2"] > holes["T1"], "replacement must demand more"
    assert holes["T1"] - holes["DEC2"] < 0, "stale caller must break version 2"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OPEN vulnerability, docs/DECOMPOSITION.md schema C. Replacing a "
        "function in the live registry does not re-verify its callers, so a "
        "modification that is safe in isolation can strand a caller that was "
        "verified against the previous contract. Closing this needs the "
        "composed-program replay of PLAN_V8 Step 2 T1. Remove this marker when "
        "it starts passing."
    ),
)
def test_paac_should_reject_schema_c_composition(axioms):
    """What correct behaviour looks like: replacing a callee re-checks callers."""
    outcome, witness, _ = synthesise(schema_by_id("C"), timeout_ms=TIMEOUT_MS)
    assert outcome is SchemaOutcome.WITNESS
    assert witness is not None

    confirmation = confirm_witness(witness, axioms, timeout_ms=TIMEOUT_MS)
    assert not confirmation.all_steps_accepted, (
        "PAAC should refuse the replacement, or re-verify the caller against it."
    )


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


def test_synthesis_is_deterministic():
    """Same query, same witness, every run.

    The reason PLAN_V8 section 11 chose a solver over an LLM or random search: a
    reviewer must be able to rerun this and get the same answer. A result that
    only reproduces sometimes cannot be defended.
    """
    first = [synthesise(s, timeout_ms=TIMEOUT_MS) for s in SCHEMAS]
    second = [synthesise(s, timeout_ms=TIMEOUT_MS) for s in SCHEMAS]

    for (o1, w1, _), (o2, w2, _) in zip(first, second):
        assert o1 is o2
        if w1 is None or w2 is None:
            assert w1 is w2 is None
        else:
            assert w1.holes == w2.holes
            assert w1.composed_program() == w2.composed_program()


def test_confirmation_requires_both_halves(axioms):
    """A witness needs acceptance AND a violation. Neither alone is an attack.

    Guards the definition itself. If `confirmed` ever became "or", every
    rejected-but-unsafe candidate would be miscounted as a successful attack and
    the resistance metric would be inflated.
    """
    outcome, witness, _ = synthesise(schema_by_id("A"), timeout_ms=TIMEOUT_MS)
    assert witness is not None
    confirmation = confirm_witness(witness, axioms, timeout_ms=TIMEOUT_MS)

    assert confirmation.confirmed == (
        confirmation.all_steps_accepted and confirmation.runtime_violated
    )
