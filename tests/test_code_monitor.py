"""
tests/test_code_monitor.py
---------------------------
Regression tests for the precondition satisfiability gate.

See PLAN_V8.md §0.5 for the full finding. Summary: `CodeModification.pre_cond`
is agent-supplied (src/monitor/agent_adapter.py) and, before this fix, reached
`_verify_inner` unvalidated. `_verify_inner` treats pre_cond as a solver
CONSTRAINT (paper §3.4), so an unsatisfiable pre_cond such as "1 == 0" forces
the whole BMC query to UNSAT regardless of what the modification's body does:
Z3 conjoins the precondition with the axiom-violation disjunction, and False
AND anything is False. Every submission was accepted; no axiom was actually
checked.

The bypass tests below submit `compute` returning a negative value, paired
with a different spelling of an unsatisfiable precondition. Before the fix,
`intercept_modification` returned {"status": "accepted"} for all four. After
the fix, it must reject with an "Unsatisfiable precondition" error, and the
payload must never reach CodeMonitor._live_registry.

IMPORTANT, and the reason the boundary tests use `decrement` rather than
`compute`: the `result_bounded: result >= 0` axiom in config/axioms.yaml does
NOT actually reject `compute` returning -1. See AUDIT_FINDINGS.md C-03. The
encoder discards the return value (`StmtEncoder._encode_stmt`, the
ReturnStmtNode branch, does `_ = self.expr_enc.encode(stmt.value)`), so no
variable named `result` ever enters the SSA environment, so `_encode_axiom`
fails with "Undefined variable: result", classifies the axiom as
*inapplicable*, and silently drops it. `result_bounded` is dead for every
function. So the four bypass tests above prove only that the GATE rejects an
unsatisfiable precondition, which is exactly what they are for; they must not
be read as evidence that the axiom check works.

The boundary tests therefore use the `counter_in_range: counter >= 0` axiom
against `decrement`, where `counter` is a real parameter and so is genuinely
bound in the environment. That is an axiom that actually fires, which makes
"still rejected for the right reason" and "accepted when genuinely safe"
meaningful assertions rather than vacuous ones.
"""

from pathlib import Path

import pytest

from src.core.exceptions import PreconditionUnsatisfiableError
from src.core.failsafe import CircuitBreaker
from src.core.verifier import check_precondition_satisfiable
from src.monitor.code_monitor import CodeModification, CodeMonitor

# Absolute, so the tests keep working after the isolation fixture below
# changes the working directory.
_AXIOM_PATH = str(Path(__file__).resolve().parents[1] / "config" / "axioms.yaml")


@pytest.fixture(autouse=True)
def _isolate_monitor_state(monkeypatch, tmp_path):
    """Give every test a clean monitor world. Fixes AUDIT_FINDINGS.md I-07.

    Without this the suite is not merely untidy, it reports wrong answers.
    Two concrete failures observed before this existed:

    1.  `test_result_bounded_axiom_actually_rejects_negative_return` documents
        C-03 by showing an unsafe `compute` is ACCEPTED. Acceptance persists
        that payload to `live_registry.json`. On the next run every bypass
        test loaded it back and failed its "unsafe code must not reach the
        registry" assertion, blaming the C-02 fix for a leftover the C-03 test
        had written.
    2.  `CodeMonitor._circuit_breaker` is class-level and explicitly one
        instance per process. Rejections used to call `record_failure()`, so the
        four bypass tests plus one boundary test opened the breaker, and every
        later test got 503 instead of a verdict. That specific cause is gone,
        since H-06 was fixed and a reached verdict of "unsafe" now records a
        success. The reset stays regardless: the breaker is shared process-wide
        mutable state, and a test that inherits it is order-dependent whatever
        the current bookkeeping rules happen to be.

    Both are ordering artefacts, and both produced confident, wrong failures,
    which is worse than a flaky skip.

    `chdir` covers all three on-disk paths at once: `_WAL_PATH` and
    `_REGISTRY_PATH` in src/core/failsafe.py are relative and resolved at
    open() time, and `CodeMonitor.lock_path` is built from `os.getcwd()`.
    They are read from the environment at import time, so setting env vars
    here would be too late.
    """
    monkeypatch.chdir(tmp_path)
    CodeMonitor._live_registry.clear()
    CodeMonitor._circuit_breaker = CircuitBreaker()
    yield
    CodeMonitor._live_registry.clear()
    CodeMonitor._circuit_breaker = CircuitBreaker()

# Every CodeMonitor construction runs a Redis health check that used to have
# no socket timeout (see the fix and comment in src/monitor/code_monitor.py).
# On this machine an unreachable Redis fails the connect attempt slowly
# rather than immediately -- likely local firewall/security-software
# interception on the loopback socket -- so relying only on the default
# REDIS_HOST ("redis", an unresolvable hostname) plus that fix's 1s timeout
# is what keeps this whole suite from stalling for tens of seconds per test.
# No environment variable override needed now that the timeout is bounded.

_UNSAFE_NEW_CODE = """
func compute(x: int) -> int {
    return -1;
}
"""

_VALID_CITATION = "https://example.com/paac-decomposition-finding"

# `counter` is a declared parameter, so it IS bound in the SSA environment and
# the `counter_in_range: counter >= 0` axiom genuinely encodes against it.
# Unguarded, Z3 picks counter == 0, making the post-assignment value -1, which
# violates the axiom. This is an axiom violation the verifier actually detects,
# unlike result_bounded (C-03).
_UNSAFE_DECREMENT = """
func decrement(counter: int) -> int {
    counter = counter - 1;
    return counter;
}
"""


def _fresh_monitor() -> CodeMonitor:
    """
    A CodeMonitor built against the real config/axioms.yaml with PCM disabled.

    Hermetic by way of the autouse `_isolate_monitor_state` fixture, which
    redirects the registry, WAL and lock into a per-test tmp_path and resets
    the class-level registry and circuit breaker.
    """
    return CodeMonitor(
        {
            "axiom_path": _AXIOM_PATH,
            "pcm_mode": False,
            "grounding": {"require_source_citations": True},
        }
    )


# ---------------------------------------------------------------------------
# Direct unit tests of the gate function
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unsatisfiable_precondition",
    [
        "1 == 0",
        "false",
        "x != x",
        "x > 0 and x < 0",
    ],
)
def test_gate_rejects_unsatisfiable_precondition(unsatisfiable_precondition):
    """The four semantic spellings from PLAN_V8.md §0.5 must all be caught.

    Using four different spellings of the same contradiction proves the gate
    is a real satisfiability check, not a string blocklist for "1 == 0".
    """
    with pytest.raises(PreconditionUnsatisfiableError):
        check_precondition_satisfiable(unsatisfiable_precondition, ["x"])


def test_gate_accepts_satisfiable_precondition():
    """A genuine, satisfiable precondition must not raise."""
    check_precondition_satisfiable("x >= 0", ["x"])  # must not raise


def test_gate_is_noop_on_empty_precondition():
    """An empty pre_cond is not a precondition at all; nothing to check."""
    check_precondition_satisfiable("", ["x"])  # must not raise
    check_precondition_satisfiable("   ", ["x"])  # must not raise


def test_gate_skips_condition_referencing_undeclared_name():
    """
    A condition referencing a name outside param_names is treated as
    inapplicable by _encode_axiom and skipped identically at verification
    time (see _verify_inner), so it can never become the False constraint
    this gate exists to catch. Must not raise.
    """
    check_precondition_satisfiable("q == 0", ["x"])  # 'q' is not a param; no-op


# ---------------------------------------------------------------------------
# End-to-end: the actual bypass, through the real entry point
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unsatisfiable_precondition",
    [
        "1 == 0",
        "false",
        "x != x",
        "x > 0 and x < 0",
    ],
)
def test_unsafe_modification_is_rejected_despite_vacuous_precondition(
    unsatisfiable_precondition,
):
    """
    THE CONFIRMED BYPASS, closed.

    Before this fix, this exact call sequence returned {"status": "accepted"}
    and CodeMonitor._live_registry["compute"] was overwritten with code that
    unconditionally violates result_bounded. This is the regression test for
    PLAN_V8.md §0.5.
    """
    monitor = _fresh_monitor()
    mod = CodeModification(
        func_name="compute",
        old_code="",
        new_code=_UNSAFE_NEW_CODE,
        pre_cond=unsatisfiable_precondition,
        post_cond="",
        source_citation=_VALID_CITATION,
    )

    result = monitor.intercept_modification(mod)

    assert result["status"] == "rejected", (
        f"Unsafe modification was ACCEPTED via pre_cond={unsatisfiable_precondition!r}. "
        f"Full result: {result}"
    )
    assert "unsatisfiable" in result.get("error", "").lower()
    assert "compute" not in CodeMonitor._live_registry or (
        CodeMonitor._live_registry.get("compute") != _UNSAFE_NEW_CODE
    ), "Unsafe code reached the live registry despite rejection."


def test_unsafe_modification_still_rejected_with_true_precondition():
    """
    Boundary check: code that genuinely violates a LIVE axiom, submitted with a
    satisfiable (vacuously true) precondition, must still be rejected, and must
    be rejected by the axiom check rather than by the new gate.

    This is what proves the C-02 fix is targeted. A gate that rejected
    everything would also make the four bypass tests pass, so without this test
    those four prove nothing about precision.
    """
    monitor = _fresh_monitor()
    mod = CodeModification(
        func_name="decrement",
        old_code="",
        new_code=_UNSAFE_DECREMENT,
        pre_cond="true",
        post_cond="",
        source_citation=_VALID_CITATION,
    )

    result = monitor.intercept_modification(mod)

    assert result["status"] == "rejected", (
        "counter_in_range should be violated when counter == 0. "
        f"Full result: {result}"
    )
    assert "unsatisfiable" not in result.get("error", "").lower(), (
        "Rejected for the wrong reason: expected a genuine axiom violation, "
        f"got: {result}"
    )


def test_safe_modification_with_satisfiable_precondition_is_accepted():
    """
    Control: the SAME body as the test above, made genuinely safe by a
    precondition that rules out the counterexample, must be accepted.

    Two things follow from this pair. The gate does not produce false positives
    on satisfiable preconditions, and a satisfiable precondition is still
    honoured as a real solver constraint after the fix. The second point
    matters: the C-02 fix rejects UNSAT preconditions, and this shows it did
    not do so by weakening or ignoring SAT ones.
    """
    monitor = _fresh_monitor()
    mod = CodeModification(
        func_name="decrement",
        old_code="",
        new_code=_UNSAFE_DECREMENT,
        pre_cond="counter >= 1",
        post_cond="",
        source_citation=_VALID_CITATION,
    )

    result = monitor.intercept_modification(mod)

    assert result["status"] == "accepted", (
        "counter >= 1 rules out the only counterexample, so this is safe. "
        f"Full result: {result}"
    )


# ---------------------------------------------------------------------------
# C-03 regression: axioms must actually fire, not be silently skipped
# ---------------------------------------------------------------------------


def test_result_bounded_axiom_actually_rejects_negative_return():
    """
    C-03 regression. `result_bounded: result >= 0` must genuinely fire.

    This was an `xfail(strict=True)` marker recording the bug. It is now a
    positive test, which is the whole point of having used a strict marker:
    when the fix landed the marker turned into a failure and forced this test
    to be rewritten rather than quietly passing unnoticed.

    History, because it explains why such an obvious-looking test was missing:
    `compute` returning -1 plainly violates the axiom and `compute` is in that
    axiom's target_functions, yet the modification was ACCEPTED. Zero axioms
    applied. `no_negative_balance` and `counter_in_range` were filtered out by
    target_functions, and `result_bounded`, `no_exit` and `no_network` were all
    dropped as "inapplicable" because they named variables the function never
    bound. `_verify_inner` then found no violation flags and returned safe
    without invoking Z3 at all.
    """
    monitor = _fresh_monitor()
    mod = CodeModification(
        func_name="compute",
        old_code="",
        new_code=_UNSAFE_NEW_CODE,
        pre_cond="true",
        post_cond="",
        source_citation=_VALID_CITATION,
    )

    result = monitor.intercept_modification(mod)

    assert result["status"] == "rejected", (
        f"result_bounded did not fire. Full result: {result}"
    )
    # Rejected for the right reason: a real axiom violation, not the
    # precondition gate and not a compilation error.
    assert "unsatisfiable" not in result.get("error", "").lower(), result
    assert "compute" not in CodeMonitor._live_registry or (
        CodeMonitor._live_registry.get("compute") != _UNSAFE_NEW_CODE
    ), "Payload reached the live registry despite rejection."


def test_sentinel_axioms_do_not_reject_functions_that_ignore_them():
    """
    The other half of C-03, and the reason the fix needs declared defaults
    rather than just failing closed.

    `no_exit` and `no_network` target every function via `["*"]`, but reference
    sentinel variables (`exit_called`, `network_calls`) that an ordinary
    function never assigns. Making unencodable axioms fail closed without also
    declaring defaults would therefore reject every submission in the system.

    The `defaults` entries in config/axioms.yaml bind absence to 0, so the
    axioms are genuinely evaluated and satisfied. This test is what
    distinguishes "the axiom is enforced" from "the axiom is vacuous", and it
    would fail loudly if someone removed the defaults to silence an error.
    """
    monitor = _fresh_monitor()
    mod = CodeModification(
        func_name="decrement",
        old_code="",
        new_code=_UNSAFE_DECREMENT,
        pre_cond="counter >= 1",
        post_cond="",
        source_citation=_VALID_CITATION,
    )

    result = monitor.intercept_modification(mod)

    assert result["status"] == "accepted", (
        "A function that never touches the sentinels must not be rejected by "
        f"no_exit or no_network. Full result: {result}"
    )


def test_sentinel_axiom_rejects_code_that_trips_it():
    """
    Complements the test above: the sentinel default must not be so permissive
    that the axiom can never fail. Code that actually sets `exit_called` must
    be rejected by `no_exit`.

    Without this, `defaults: {exit_called: 0}` could be pinning the variable to
    a constant and the axiom would be satisfied unconditionally, which is
    exactly the class of vacuous pass C-03 was about. The pair of tests
    establishes that the default applies only when the program is silent.
    """
    monitor = _fresh_monitor()
    mod = CodeModification(
        func_name="decrement",
        old_code="",
        new_code="""
        func decrement(counter: int) -> int {
            exit_called = 1;
            return counter;
        }
        """,
        pre_cond="counter >= 1",
        post_cond="",
        source_citation=_VALID_CITATION,
    )

    result = monitor.intercept_modification(mod)

    assert result["status"] == "rejected", (
        f"no_exit must fire when the program sets exit_called. Result: {result}"
    )
