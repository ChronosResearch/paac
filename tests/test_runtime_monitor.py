"""tests/test_runtime_monitor.py — Feature 6: Runtime Verification"""
import pytest
from src.axioms.axiom_parser import Axiom
from src.core.sil_compiler import SILCompiler
from src.core.runtime_monitor import RuntimeMonitor, RuntimeSafetyViolation, RuntimeTrace

COMPILER = SILCompiler()


def _axiom(condition: str) -> Axiom:
    return Axiom("test", "test axiom", condition, ["*"])


# ---------------------------------------------------------------------------
# Basic execution
# ---------------------------------------------------------------------------

def test_safe_program_no_violations():
    """A safe program must execute without violations."""
    ast, _ = COMPILER.compile(
        "func f(x: int) -> int { assert x >= 0; return x; }"
    )
    monitor = RuntimeMonitor(ast)
    trace = monitor.execute("f", [5])
    assert trace.safe is True
    assert trace.violations == []
    assert trace.assertions_checked == 1
    assert trace.steps > 0


def test_assertion_failure_raises():
    """A failing assert must raise RuntimeSafetyViolation."""
    ast, _ = COMPILER.compile(
        "func f(x: int) -> int { assert x > 0; return x; }"
    )
    monitor = RuntimeMonitor(ast)
    with pytest.raises(RuntimeSafetyViolation):
        monitor.execute("f", [0])


def test_axiom_violation_raises():
    """An axiom violation must raise RuntimeSafetyViolation."""
    ast, _ = COMPILER.compile(
        "func f(balance: int) -> int { balance = balance - 10; return balance; }"
    )
    monitor = RuntimeMonitor(ast, axioms=[_axiom("balance >= 0")])
    with pytest.raises(RuntimeSafetyViolation):
        monitor.execute("f", [5])   # 5 - 10 = -5 → violates balance >= 0


def test_axiom_satisfied_no_violation():
    """When axiom is satisfied, no violation must occur."""
    ast, _ = COMPILER.compile(
        "func f(balance: int) -> int { balance = balance + 10; return balance; }"
    )
    monitor = RuntimeMonitor(ast, axioms=[_axiom("balance >= 0")])
    trace = monitor.execute("f", [5])
    assert trace.safe is True


def test_on_violation_callback_called():
    """on_violation callback must be called on violation."""
    ast, _ = COMPILER.compile(
        "func f(x: int) -> int { assert x > 0; return x; }"
    )
    calls = []
    def cb(msg, env):
        calls.append(msg)

    monitor = RuntimeMonitor(ast, on_violation=cb)
    with pytest.raises(RuntimeSafetyViolation):
        monitor.execute("f", [0])
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Trace fields
# ---------------------------------------------------------------------------

def test_trace_steps_counted():
    """Trace must count executed steps."""
    ast, _ = COMPILER.compile(
        "func f(x: int) -> int { y = x + 1; return y; }"
    )
    monitor = RuntimeMonitor(ast)
    trace = monitor.execute("f", [3])
    assert trace.steps >= 1


def test_trace_elapsed_ms_positive():
    """Elapsed time must be positive."""
    ast, _ = COMPILER.compile("func f(x: int) -> int { return x; }")
    monitor = RuntimeMonitor(ast)
    trace = monitor.execute("f", [1])
    assert trace.elapsed_ms >= 0.0


def test_trace_axioms_checked_counted():
    """Axioms checked counter must be incremented."""
    ast, _ = COMPILER.compile(
        "func f(x: int) -> int { y = x + 1; return y; }"
    )
    monitor = RuntimeMonitor(ast, axioms=[_axiom("x >= 0")])
    trace = monitor.execute("f", [1])
    assert trace.axioms_checked >= 1


# ---------------------------------------------------------------------------
# Control flow
# ---------------------------------------------------------------------------

def test_if_branch_monitored():
    """Both branches of an if must be monitored."""
    ast, _ = COMPILER.compile(
        "func f(x: int) -> int { "
        "if x > 0 { assert x > 0; } else { assert x <= 0; } "
        "return x; }"
    )
    monitor = RuntimeMonitor(ast)
    trace_pos = monitor.execute("f", [1])
    assert trace_pos.safe is True
    trace_neg = monitor.execute("f", [-1])
    assert trace_neg.safe is True


def test_while_loop_monitored():
    """Loop body must be monitored on each iteration."""
    ast, _ = COMPILER.compile(
        "func f(n: int) -> int { "
        "i = 0; while (i < n) bound 10 { assert i >= 0; i = i + 1; } "
        "return i; }"
    )
    monitor = RuntimeMonitor(ast)
    trace = monitor.execute("f", [5])
    assert trace.safe is True
    assert trace.assertions_checked == 5


def test_unknown_function_raises():
    """Calling an unknown function must raise SILRuntimeError."""
    from src.core.sil_runtime import SILRuntimeError
    ast, _ = COMPILER.compile("func f(x: int) -> int { return x; }")
    monitor = RuntimeMonitor(ast)
    with pytest.raises(SILRuntimeError):
        monitor.execute("nonexistent", [1])


# ---------------------------------------------------------------------------
# Hybrid verification
# ---------------------------------------------------------------------------

def test_static_safe_runtime_safe():
    """Program safe statically and at runtime — both must agree."""
    from src.core.verifier import BoundedModelChecker
    code = "func f(x: int) -> int { assert x == x; return x; }"
    ast, _ = COMPILER.compile(code)

    bmc = BoundedModelChecker()
    static_safe, _ = bmc._verify_inner(ast, [], 5000)
    assert static_safe is True

    monitor = RuntimeMonitor(ast)
    trace = monitor.execute("f", [42])
    assert trace.safe is True
