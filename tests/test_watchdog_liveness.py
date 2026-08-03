"""
Tests for the two-thread watchdog design in src/monitor/watchdog.py
and the embedded liveness loop in CodeMonitor.

Pass criteria:
  - No watchdog recovery fires during idle periods.
  - Recovery fires only when the liveness thread is genuinely stalled.
  - heartbeat() resets the timestamp (supplementary, not required).
  - Watchdog stops cleanly.
"""

import threading
import time

from src.monitor.watchdog import Watchdog

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_watchdog(
    timeout: int = 4, heartbeat_interval: int = 1, monitor_interval: int = 1
) -> Watchdog:
    config = {
        "self_healing": {
            "enabled": True,
            "heartbeat_interval_secs": heartbeat_interval,
            "monitor_interval_secs": monitor_interval,
            "recovery_timeout_secs": timeout,
        }
    }
    return Watchdog(config)


# ---------------------------------------------------------------------------
# Core correctness
# ---------------------------------------------------------------------------


def test_idle_does_not_trigger_recovery():
    """Watchdog must NOT fire during idle periods (no requests sent).

    The liveness thread keeps last_heartbeat fresh every second.
    We wait 3× the timeout and confirm _trigger_recovery was never called.
    """
    wd = _make_watchdog(timeout=4)
    recovery_calls = []

    original = wd._trigger_recovery

    def patched():
        recovery_calls.append(time.monotonic())
        original()

    wd._trigger_recovery = patched

    wd.start()
    time.sleep(6)  # 1.5× timeout — liveness thread should keep it alive
    wd.stop()

    assert recovery_calls == [], (
        f"Watchdog fired {len(recovery_calls)} time(s) during idle — "
        "liveness thread is not running correctly."
    )


def test_recovery_fires_when_liveness_thread_stalls():
    """Recovery must fire when the liveness thread stops updating the timestamp.

    We stop the liveness thread via its own flag while keeping the monitor
    running, then wait for the monitor to detect the stall.
    """
    wd = _make_watchdog(timeout=3, heartbeat_interval=1, monitor_interval=1)
    recovery_event = threading.Event()

    original = wd._trigger_recovery

    def patched():
        recovery_event.set()
        original()

    wd._trigger_recovery = patched

    wd.start()
    time.sleep(0.5)  # let liveness thread start

    # Stop only the liveness thread; monitor keeps running.
    wd._liveness_running = False
    time.sleep(1.5)  # let liveness thread exit its sleep and check the flag

    # Now the timestamp will drift past timeout.
    fired = recovery_event.wait(timeout=8)
    wd.stop()

    assert fired, "Watchdog did not fire after liveness thread stalled."


def test_explicit_heartbeat_resets_timestamp():
    """heartbeat() must update last_heartbeat (supplementary path)."""
    wd = _make_watchdog(timeout=60)
    wd.start()
    time.sleep(0.1)

    before = wd._last_heartbeat
    time.sleep(0.05)
    wd.heartbeat()
    after = wd._last_heartbeat

    wd.stop()
    assert after >= before, "heartbeat() did not advance last_heartbeat."


def test_watchdog_stops_cleanly():
    """stop() must not hang and threads must exit."""
    wd = _make_watchdog(timeout=60)
    wd.start()
    time.sleep(0.2)
    wd.stop()

    assert not wd.running
    if wd._liveness_thread:
        wd._liveness_thread.join(timeout=3)
        assert not wd._liveness_thread.is_alive(), "Liveness thread did not exit."
    if wd._monitor_thread:
        wd._monitor_thread.join(timeout=3)
        assert not wd._monitor_thread.is_alive(), "Monitor thread did not exit."


def test_disabled_watchdog_starts_no_threads():
    """When enabled=False, no threads must be started."""
    config = {"self_healing": {"enabled": False}}
    wd = Watchdog(config)
    wd.start()
    assert wd._liveness_thread is None
    assert wd._monitor_thread is None


def test_heartbeat_count_increments():
    """Liveness thread must increment _heartbeat_count every interval."""
    wd = _make_watchdog(timeout=60, heartbeat_interval=1)
    wd.start()
    time.sleep(3.5)  # expect ~3 ticks
    wd.stop()

    assert (
        wd._heartbeat_count >= 2
    ), f"Expected ≥2 heartbeat ticks, got {wd._heartbeat_count}."


# ---------------------------------------------------------------------------
# CodeMonitor embedded watchdog
# ---------------------------------------------------------------------------


def test_code_monitor_idle_does_not_trigger(tmp_path, monkeypatch):
    """CodeMonitor's embedded watchdog must not fire during idle."""
    monkeypatch.setenv("PAAC_WATCHDOG_TIMEOUT", "4")
    monkeypatch.setattr("src.core.failsafe._WAL_PATH", str(tmp_path / "test.wal"))
    monkeypatch.setattr("src.core.failsafe._REGISTRY_PATH", str(tmp_path / "reg.json"))

    from src.monitor.code_monitor import CodeMonitor

    recovery_calls = []
    original_recover = CodeMonitor._watchdog_recover

    def patched_recover(self):
        recovery_calls.append(time.monotonic())
        original_recover(self)

    monkeypatch.setattr(CodeMonitor, "_watchdog_recover", patched_recover)

    config = {
        "axiom_path": "config/axioms.yaml",
        "grounding": {"require_source_citations": False},
    }
    monitor = CodeMonitor(config)
    time.sleep(6)  # 1.5× timeout — liveness thread must keep it alive
    monitor.stop_watchdog()

    assert (
        recovery_calls == []
    ), f"CodeMonitor watchdog fired {len(recovery_calls)} time(s) during idle."
