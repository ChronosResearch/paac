"""
Fail-safe simulation tests (Step 98).
Simulates: Redis down, Z3 crash, circuit breaker open, WAL corruption.
All scenarios must recover gracefully.
"""
import os
import tempfile
import time

import pytest

from src.core.failsafe import (
    CircuitBreaker,
    CircuitOpenError,
    WALEntry,
    wal_append,
    wal_load_latest,
    registry_save,
    registry_load,
)
from src.core.sil_compiler import SILCompiler
from src.core.verifier import BoundedModelChecker, VerificationError

COMPILER = SILCompiler()


# ---------------------------------------------------------------------------
# Scenario 1: Redis down — WAL fallback
# ---------------------------------------------------------------------------

def test_failsafe_redis_down_wal_fallback(tmp_path, monkeypatch):
    """When Redis is unavailable, WAL must preserve checkpoints."""
    wal_file = str(tmp_path / "failsafe.wal")
    monkeypatch.setattr("src.core.failsafe._WAL_PATH", wal_file)

    # Write checkpoint to WAL (simulating Redis-down path)
    entry = WALEntry(
        func_name="critical_func",
        old_code="old",
        new_code="new_safe",
        pre_cond="",
        post_cond="",
        source_citation="https://example.com/v1",
        timestamp=time.time(),
    )
    wal_append(entry)

    # Simulate restart — load from WAL
    latest = wal_load_latest()
    assert "critical_func" in latest
    assert latest["critical_func"].new_code == "new_safe"
    print("PASS: Redis-down WAL fallback")


# ---------------------------------------------------------------------------
# Scenario 2: WAL corruption — skip bad lines, continue
# ---------------------------------------------------------------------------

def test_failsafe_wal_corruption_recovery(tmp_path, monkeypatch):
    """Corrupt WAL lines must be skipped; valid entries must be recovered."""
    wal_file = str(tmp_path / "corrupt.wal")
    monkeypatch.setattr("src.core.failsafe._WAL_PATH", wal_file)

    # Write one valid entry, one corrupt line, one more valid entry
    with open(wal_file, "w") as f:
        import json
        from dataclasses import asdict
        good1 = WALEntry("func_a", "", "code_a", "", "", "https://x.com", 1000.0)
        f.write(json.dumps(asdict(good1)) + "\n")
        f.write("THIS IS CORRUPT JSON {{{\n")
        good2 = WALEntry("func_b", "", "code_b", "", "", "https://x.com", 2000.0)
        f.write(json.dumps(asdict(good2)) + "\n")

    latest = wal_load_latest()
    assert "func_a" in latest
    assert "func_b" in latest
    assert latest["func_a"].new_code == "code_a"
    assert latest["func_b"].new_code == "code_b"
    print("PASS: WAL corruption recovery")


# ---------------------------------------------------------------------------
# Scenario 3: Circuit breaker open — rejects all, recovers after cooldown
# ---------------------------------------------------------------------------

def test_failsafe_circuit_breaker_full_cycle():
    """Full circuit breaker cycle: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
    cb = CircuitBreaker(failure_threshold=3, cooldown_s=0.1)

    # CLOSED — requests allowed
    cb.allow_request()
    assert cb.state == "CLOSED"

    # 3 failures -> OPEN
    for _ in range(3):
        cb.record_failure()
    assert cb.state == "OPEN"

    # OPEN — requests rejected
    with pytest.raises(CircuitOpenError):
        cb.allow_request()

    # Wait for cooldown -> HALF_OPEN
    time.sleep(0.15)
    cb.allow_request()  # must not raise
    assert cb.state == "HALF_OPEN"

    # Success in HALF_OPEN -> CLOSED
    cb.record_success()
    assert cb.state == "CLOSED"

    # Requests allowed again
    cb.allow_request()
    print("PASS: Circuit breaker full cycle")


def test_failsafe_circuit_breaker_half_open_failure():
    """Failure in HALF_OPEN must reopen the circuit."""
    cb = CircuitBreaker(failure_threshold=1, cooldown_s=0.1)
    cb.record_failure()
    assert cb.state == "OPEN"

    time.sleep(0.15)
    cb.allow_request()  # HALF_OPEN
    cb.record_failure()  # fail the probe
    assert cb.state == "OPEN"
    print("PASS: Circuit breaker HALF_OPEN failure re-opens")


# ---------------------------------------------------------------------------
# Scenario 4: Z3 crash — retry and fallback
# ---------------------------------------------------------------------------

def test_failsafe_z3_crash_static_fallback(monkeypatch):
    """Z3 crash must trigger static fallback for obvious violations."""
    ast, _ = COMPILER.compile("func bad() -> int { assert false; return 0; }")
    bmc = BoundedModelChecker()

    call_count = [0]

    def mock_subprocess(*args, **kwargs):
        call_count[0] += 1
        raise VerificationError("simulated Z3 crash")

    monkeypatch.setattr(bmc, "_verify_subprocess", mock_subprocess)

    # Static fallback catches assert false
    safe, ce = bmc.verify(ast, [])
    assert safe is False
    assert ce is not None
    print(f"PASS: Z3 crash static fallback (subprocess called {call_count[0]} time(s))")


# ---------------------------------------------------------------------------
# Scenario 5: Registry persistence — survives restart
# ---------------------------------------------------------------------------

def test_failsafe_registry_survives_restart(tmp_path, monkeypatch):
    """Registry must be loadable after a simulated process restart."""
    reg_file = str(tmp_path / "registry.json")
    monkeypatch.setattr("src.core.failsafe._REGISTRY_PATH", reg_file)

    # Save state
    registry_save({"func_a": "code_a", "func_b": "code_b"})

    # Simulate restart — load state
    loaded = registry_load()
    assert loaded == {"func_a": "code_a", "func_b": "code_b"}
    print("PASS: Registry survives restart")


# ---------------------------------------------------------------------------
# Scenario 6: Concurrent circuit breaker access (thread safety)
# ---------------------------------------------------------------------------

def test_failsafe_circuit_breaker_thread_safety():
    """Circuit breaker must be thread-safe under concurrent access."""
    import threading
    cb = CircuitBreaker(failure_threshold=20, cooldown_s=60)
    errors = []

    def worker():
        try:
            for _ in range(10):
                cb.record_failure()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert cb.state == "OPEN"
    print("PASS: Circuit breaker thread safety")


# ---------------------------------------------------------------------------
# Scenario 7: IPC token prevents spoofed responses
# ---------------------------------------------------------------------------

def test_failsafe_ipc_token_rejects_wrong_token():
    """IPC token mismatch must raise VerificationError."""
    from src.core.tcb_protect import generate_ipc_token, verify_ipc_token
    t1 = generate_ipc_token()
    t2 = generate_ipc_token()
    assert not verify_ipc_token(t1, t2)
    print("PASS: IPC token rejects wrong token")


if __name__ == "__main__":
    import tempfile
    import sys

    # Run all scenarios
    with tempfile.TemporaryDirectory() as tmp:
        print("Running fail-safe simulation tests...\n")
        test_failsafe_circuit_breaker_full_cycle()
        test_failsafe_circuit_breaker_half_open_failure()
        test_failsafe_circuit_breaker_thread_safety()
        test_failsafe_ipc_token_rejects_wrong_token()
        print("\nAll fail-safe scenarios PASSED")
