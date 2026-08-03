"""Tests for PAAC v4.1 fail-safe mechanisms."""

import os
import threading
import time

import pytest

from src.core.failsafe import (
    CircuitBreaker,
    CircuitOpenError,
    WALEntry,
    registry_load,
    registry_save,
    wal_append,
    wal_load_latest,
)
from src.core.sil_compiler import (
    AssignmentStmtNode,
    BasicBlock,
    SILCompiler,
)
from src.core.tcb_protect import generate_ipc_token, verify_ipc_token
from src.core.verifier import BoundedModelChecker

# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------


def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, cooldown_s=60)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == "OPEN"
    with pytest.raises(CircuitOpenError):
        cb.allow_request()


def test_circuit_breaker_closed_allows_requests():
    cb = CircuitBreaker()
    cb.allow_request()  # must not raise


def test_circuit_breaker_half_open_after_cooldown():
    cb = CircuitBreaker(failure_threshold=1, cooldown_s=0.05)
    cb.record_failure()
    assert cb.state == "OPEN"
    time.sleep(0.1)
    cb.allow_request()  # should not raise — transitions to HALF_OPEN
    assert cb.state == "HALF_OPEN"


def test_circuit_breaker_closes_on_success_after_half_open():
    cb = CircuitBreaker(failure_threshold=1, cooldown_s=0.05)
    cb.record_failure()
    time.sleep(0.1)
    cb.allow_request()  # HALF_OPEN
    cb.record_success()
    assert cb.state == "CLOSED"


def test_circuit_breaker_reopens_on_failure_in_half_open():
    cb = CircuitBreaker(failure_threshold=1, cooldown_s=0.05)
    cb.record_failure()
    time.sleep(0.1)
    cb.allow_request()  # HALF_OPEN
    cb.record_failure()
    assert cb.state == "OPEN"


def test_circuit_breaker_thread_safe():
    cb = CircuitBreaker(failure_threshold=10, cooldown_s=60)
    errors = []

    def worker():
        try:
            for _ in range(5):
                cb.record_failure()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert cb.state == "OPEN"


# ---------------------------------------------------------------------------
# WAL checkpoint store
# ---------------------------------------------------------------------------


def test_wal_append_and_load(tmp_path, monkeypatch):
    wal_file = str(tmp_path / "test.wal")
    monkeypatch.setattr("src.core.failsafe._WAL_PATH", wal_file)

    entry = WALEntry(
        func_name="foo",
        old_code="old",
        new_code="new",
        pre_cond="",
        post_cond="",
        source_citation="https://example.com/v1",
        timestamp=1000.0,
    )
    wal_append(entry)

    latest = wal_load_latest()
    assert "foo" in latest
    assert latest["foo"].new_code == "new"


def test_wal_keeps_latest_entry(tmp_path, monkeypatch):
    wal_file = str(tmp_path / "test.wal")
    monkeypatch.setattr("src.core.failsafe._WAL_PATH", wal_file)

    for i, ts in enumerate([1000.0, 2000.0, 500.0]):
        wal_append(
            WALEntry("bar", "", f"code_v{i}", "", "", "https://x.com", ts)
        )

    latest = wal_load_latest()
    # Timestamp 2000.0 is the most recent.
    assert latest["bar"].new_code == "code_v1"


def test_wal_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.core.failsafe._WAL_PATH", str(tmp_path / "nonexistent.wal")
    )
    assert wal_load_latest() == {}


# ---------------------------------------------------------------------------
# Registry persistence
# ---------------------------------------------------------------------------


def test_registry_save_and_load(tmp_path, monkeypatch):
    reg_file = str(tmp_path / "registry.json")
    monkeypatch.setattr("src.core.failsafe._REGISTRY_PATH", reg_file)

    registry_save({"func_a": "code_a", "func_b": "code_b"})
    loaded = registry_load()
    assert loaded == {"func_a": "code_a", "func_b": "code_b"}


def test_registry_load_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.core.failsafe._REGISTRY_PATH", str(tmp_path / "no.json")
    )
    assert registry_load() == {}


def test_registry_save_is_atomic(tmp_path, monkeypatch):
    """save() writes to a .tmp file then renames — no partial reads."""
    reg_file = str(tmp_path / "registry.json")
    monkeypatch.setattr("src.core.failsafe._REGISTRY_PATH", reg_file)

    registry_save({"x": "1"})
    registry_save({"x": "2"})
    assert registry_load() == {"x": "2"}
    assert not os.path.exists(reg_file + ".tmp")


# ---------------------------------------------------------------------------
# IPC token (R-3)
# ---------------------------------------------------------------------------


def test_ipc_token_is_32_bytes():
    token = generate_ipc_token()
    assert isinstance(token, bytes)
    assert len(token) == 32


def test_ipc_token_verify_correct():
    token = generate_ipc_token()
    assert verify_ipc_token(token, token) is True


def test_ipc_token_verify_wrong():
    t1 = generate_ipc_token()
    t2 = generate_ipc_token()
    assert verify_ipc_token(t1, t2) is False


def test_ipc_token_unique():
    tokens = {generate_ipc_token() for _ in range(100)}
    assert len(tokens) == 100


# ---------------------------------------------------------------------------
# Z3 crash retry
# ---------------------------------------------------------------------------


def test_z3_normal_verification_still_works():
    """Ensure the retry wrapper does not break normal operation."""
    compiler = SILCompiler()
    ast, _ = compiler.compile("func f(x: int) -> int { return x; }")
    bmc = BoundedModelChecker()
    safe, ce = bmc.verify(ast, [])
    assert safe is True
    assert ce is None


# ---------------------------------------------------------------------------
# CFG builder R-5: no raw expression nodes in statements
# ---------------------------------------------------------------------------


def test_cfg_basic_block_statements_are_stmt_nodes():
    """BasicBlock.statements must contain only statement nodes, not expressions."""
    compiler = SILCompiler()
    ast, cfgs = compiler.compile("""
    func f(x: int) -> int {
        if x > 0 {
            x = x + 1;
        } else {
            x = 0;
        }
        return x;
    }
    """)
    # Walk all blocks and verify no raw expression nodes in statements.
    stmt_node_types = (
        AssignmentStmtNode,
        # ReturnStmtNode, AssertStmtNode are also valid
    )
    from src.core.sil_compiler import AssertStmtNode, ReturnStmtNode

    def walk(block: BasicBlock, visited: set) -> None:
        if id(block) in visited:
            return
        visited.add(id(block))
        for stmt in block.statements:
            assert isinstance(
                stmt, (AssignmentStmtNode, ReturnStmtNode, AssertStmtNode)
            ), f"Non-statement node in BasicBlock.statements: {type(stmt).__name__}"
        for succ in block.successors:
            walk(succ, visited)

    for entry_block in cfgs.values():
        walk(entry_block, set())


def test_cfg_branch_condition_stored_separately():
    """If/while conditions must be in branch_condition, not statements."""
    compiler = SILCompiler()
    ast, cfgs = compiler.compile("""
    func g(x: int) -> int {
        while (x < 10) bound 10 {
            x = x + 1;
        }
        return x;
    }
    """)

    def walk(block: BasicBlock, visited: set) -> list[BasicBlock]:
        if id(block) in visited:
            return []
        visited.add(id(block))
        result = [block]
        for succ in block.successors:
            result.extend(walk(succ, visited))
        return result

    all_blocks = walk(cfgs["g"], set())
    # At least one block must have a branch_condition (the while header).
    assert any(b.branch_condition is not None for b in all_blocks)


# ---------------------------------------------------------------------------
# Citation validation R-6
# ---------------------------------------------------------------------------


def test_citation_too_short_rejected():
    from src.monitor.code_monitor import CodeModification, CodeMonitor

    config = {
        "grounding": {"require_source_citations": True},
        "axiom_path": "config/axioms.yaml",
    }
    monitor = CodeMonitor(config)
    monitor.stop_watchdog()
    mod = CodeModification(
        "f", "", "func f(x: int) -> int { return x; }", "", "", "short"
    )
    result = monitor.intercept_modification(mod)
    assert result["status"] == "rejected"
    assert "citation" in result["error"].lower()


def test_citation_no_dot_rejected():
    from src.monitor.code_monitor import CodeModification, CodeMonitor

    config = {
        "grounding": {"require_source_citations": True},
        "axiom_path": "config/axioms.yaml",
    }
    monitor = CodeMonitor(config)
    monitor.stop_watchdog()
    mod = CodeModification(
        "f", "", "func f(x: int) -> int { return x; }", "", "",
        "averylongcitationwithoutadot"
    )
    result = monitor.intercept_modification(mod)
    assert result["status"] == "rejected"
    assert "citation" in result["error"].lower()


def test_citation_valid_url_accepted():
    from src.monitor.code_monitor import CodeModification, CodeMonitor

    config = {
        "grounding": {"require_source_citations": False},
        "axiom_path": "config/axioms.yaml",
    }
    monitor = CodeMonitor(config)
    monitor.stop_watchdog()
    mod = CodeModification(
        "sq", "", "func sq(x: int) -> int { y = x * x; assert y >= 0; return y; }",
        "", "", "https://doi.org/10.1234/example"
    )
    result = monitor.intercept_modification(mod)
    assert result["status"] == "accepted"


# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------


def test_watchdog_resets_circuit_breaker_on_timeout():
    from src.monitor.code_monitor import CodeMonitor

    config = {
        "grounding": {"require_source_citations": False},
        "axiom_path": "config/axioms.yaml",
    }
    monitor = CodeMonitor(config)
    monitor.stop_watchdog()

    # Force circuit open.
    for _ in range(5):
        CodeMonitor._circuit_breaker.record_failure()
    assert CodeMonitor._circuit_breaker.state == "OPEN"

    # Simulate watchdog timeout recovery.
    monitor._watchdog_recover()
    assert CodeMonitor._circuit_breaker.state == "CLOSED"
