import time

from src.core.watchdog import Checkpointer, CircuitBreaker, Watchdog


def test_circuit_breaker():
    cb = CircuitBreaker(max_failures=2, reset_timeout=1)
    assert cb.can_execute() is True
    cb.record_failure()
    assert cb.can_execute() is True
    cb.record_failure()
    assert cb.can_execute() is False
    cb.record_success()
    assert cb.can_execute() is True


def test_circuit_breaker_timeout():
    cb = CircuitBreaker(max_failures=1, reset_timeout=1)
    cb.record_failure()
    assert cb.can_execute() is False
    # Wait for timeout
    time.sleep(1.1)
    assert cb.can_execute() is True
    assert cb.state == "HALF_OPEN"


def test_checkpointer_fallback():
    # Uses invalid port to force fallback to memory store
    cp = Checkpointer(redis_port=9999)
    assert cp.redis_client is None
    cp.save("test_key", "test_val")
    assert cp.load("test_key") == "test_val"


def test_watchdog_integration():
    wd = Watchdog()
    wd.start_health_check_loop()
    assert wd.is_running is True

    wd.record_verification_success()
    assert wd.check_health() is True

    for _ in range(3):
        wd.record_verification_failure()

    assert wd.check_health() is False
    assert wd.checkpointer.load("RECOVERY_STATE") == "ACTIVE"
