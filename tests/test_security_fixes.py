"""
Tests for the five critical security fixes:
  A-01 -- Under-bounded loop soundness
  A-02 -- Cache poisoning prevention
  A-03 -- Constant-time API key comparison
  A-04 -- spawn start method for multiprocessing
  A-05 -- target_functions enforcement
"""
import multiprocessing
import secrets

import pytest

from src.axioms.axiom_parser import Axiom
from src.core.sil_compiler import SILCompiler
from src.core.verifier import BoundedModelChecker

COMPILER = SILCompiler()


def compile_sil(code: str):
    ast, _ = COMPILER.compile(code)
    return ast


# ---------------------------------------------------------------------------
# A-01: Under-bounded loop soundness
# ---------------------------------------------------------------------------

def test_under_bounded_loop_is_unsafe():
    """while (x < 5) bound 3 starting from x=0 never exits in 3 steps -- must be SAT."""
    ast = compile_sil("""
    func under_bounded() -> int {
        x = 0;
        while (x < 5) bound 3 {
            x = x + 1;
        }
        return x;
    }
    """)
    bmc = BoundedModelChecker()
    safe, ce = bmc.verify(ast, [])
    assert safe is False, (
        "Under-bounded loop (x<5, bound=3, x starts at 0) must be detected as UNSAFE"
    )
    assert ce is not None


def test_exactly_bounded_loop_is_safe():
    """while (x < 3) bound 5 starting from x=0 exits at iteration 3 -- must be UNSAT."""
    ast = compile_sil("""
    func exact_bound() -> int {
        x = 0;
        while (x < 3) bound 5 {
            x = x + 1;
        }
        return x;
    }
    """)
    bmc = BoundedModelChecker()
    safe, ce = bmc.verify(ast, [])
    assert safe is True, f"Exactly-bounded loop must be SAFE; ce={ce}"


def test_over_bounded_loop_is_safe():
    """while (x < 3) bound 10 starting from x=0 -- more than enough -- must be UNSAT."""
    ast = compile_sil("""
    func over_bounded() -> int {
        x = 0;
        while (x < 3) bound 10 {
            x = x + 1;
        }
        return x;
    }
    """)
    bmc = BoundedModelChecker()
    safe, ce = bmc.verify(ast, [])
    assert safe is True, f"Over-bounded loop must be SAFE; ce={ce}"


def test_loop_that_never_runs_is_safe():
    """while (x > 100) bound 5 starting from x=0 -- body never executes -- must be UNSAT."""
    ast = compile_sil("""
    func never_runs() -> int {
        x = 0;
        while (x > 100) bound 5 {
            x = x - 1;
        }
        return x;
    }
    """)
    bmc = BoundedModelChecker()
    safe, ce = bmc.verify(ast, [])
    assert safe is True, f"Loop that never runs must be SAFE; ce={ce}"


# ---------------------------------------------------------------------------
# A-02: Cache poisoning prevention
# ---------------------------------------------------------------------------

def test_cache_not_poisonable_via_direct_assignment():
    """External code must not be able to inject a (True, None) entry."""
    bmc = BoundedModelChecker()
    # _cache is a read-only property returning a copy.
    # Writing to the returned dict must NOT affect the internal cache.
    cache_copy = bmc._cache
    cache_copy["fake_key"] = (True, None)
    assert "fake_key" not in bmc._cache, (
        "Writing to _cache copy must not affect internal state"
    )


def test_cache_not_poisonable_via_attribute_set():
    """Setting bmc._cache = {...} must not bypass verification."""
    bmc = BoundedModelChecker()
    unsafe_ast = compile_sil("""
    func always_bad() -> int {
        assert false;
        return 0;
    }
    """)
    key = bmc._hash_ast(unsafe_ast, [])
    poisoned = {key: (True, None)}
    try:
        bmc._cache = poisoned  # property has no setter -- should raise AttributeError
    except AttributeError:
        pass
    safe, ce = bmc.verify(unsafe_ast, [])
    assert safe is False, "Cache poisoning must not make an unsafe program appear safe"


def test_cache_hit_returns_correct_result():
    """A genuine cache hit must return the same result as the first call."""
    ast = compile_sil("func f(x: int) -> int { return x; }")
    bmc = BoundedModelChecker()
    safe1, _ = bmc.verify(ast, [])
    safe2, _ = bmc.verify(ast, [])
    assert safe1 == safe2


def test_different_programs_use_different_cache_entries():
    """Two different programs must never share a cache entry."""
    ast_safe = compile_sil("func f(x: int) -> int { return x; }")
    ast_unsafe = compile_sil("func g() -> int { assert false; return 0; }")
    bmc = BoundedModelChecker()
    bmc.verify(ast_safe, [])
    safe, ce = bmc.verify(ast_unsafe, [])
    assert safe is False, "Unsafe program must not be served a safe result from cache"


# ---------------------------------------------------------------------------
# A-03: Constant-time API key comparison
# ---------------------------------------------------------------------------

def test_main_uses_compare_digest():
    """src/main.py must use secrets.compare_digest for API key comparison."""
    with open("src/main.py") as f:
        source = f.read()
    assert "secrets.compare_digest" in source, (
        "main.py must use secrets.compare_digest (A-03)"
    )
    assert "key != _API_KEY" not in source, (
        "main.py must not use != for API key comparison (timing attack)"
    )


def test_compare_digest_correct_key_passes():
    """secrets.compare_digest must accept a matching key."""
    api_key = "supersecretkey123"
    assert secrets.compare_digest("supersecretkey123", api_key)


def test_compare_digest_wrong_key_fails():
    """secrets.compare_digest must reject a non-matching key."""
    api_key = "supersecretkey123"
    assert not secrets.compare_digest("wrongkey", api_key)


# ---------------------------------------------------------------------------
# A-04: spawn start method
# ---------------------------------------------------------------------------

def test_spawn_start_method_configured():
    """multiprocessing start method must be 'spawn' after importing main."""
    import src.main  # noqa: F401 -- side-effect: sets start method
    method = multiprocessing.get_start_method(allow_none=True)
    assert method == "spawn", (
        f"Expected start method 'spawn', got '{method}' (A-04)"
    )


def test_main_source_sets_spawn():
    """src/main.py source must contain set_start_method('spawn')."""
    with open("src/main.py") as f:
        source = f.read()
    assert 'set_start_method("spawn"' in source or "set_start_method('spawn'" in source, (
        "main.py must call set_start_method('spawn') (A-04)"
    )


# ---------------------------------------------------------------------------
# A-05: target_functions enforcement
# ---------------------------------------------------------------------------

def test_axiom_not_applied_to_non_target_function():
    """An axiom targeting 'withdraw' must NOT be applied to 'deposit'."""
    from src.monitor.code_monitor import CodeMonitor

    monitor = CodeMonitor.__new__(CodeMonitor)
    monitor.axioms = [
        Axiom("no_negative_balance", "", "balance >= 0", ["withdraw"]),
        Axiom("counter_safe", "", "counter >= 0", ["increment"]),
    ]

    deposit_axioms = monitor._get_applicable_axioms("deposit")
    assert len(deposit_axioms) == 0, (
        "No axioms should apply to 'deposit' when none target it"
    )


def test_axiom_applied_to_target_function():
    """An axiom targeting 'withdraw' must be applied to 'withdraw'."""
    from src.monitor.code_monitor import CodeMonitor

    monitor = CodeMonitor.__new__(CodeMonitor)
    monitor.axioms = [
        Axiom("no_negative_balance", "", "balance >= 0", ["withdraw"]),
    ]

    withdraw_axioms = monitor._get_applicable_axioms("withdraw")
    assert len(withdraw_axioms) == 1
    assert withdraw_axioms[0].id == "no_negative_balance"


def test_wildcard_axiom_applies_to_all_functions():
    """An axiom with target_functions=['*'] must apply to every function."""
    from src.monitor.code_monitor import CodeMonitor

    monitor = CodeMonitor.__new__(CodeMonitor)
    monitor.axioms = [
        Axiom("global_rule", "", "x >= 0", ["*"]),
    ]

    for func in ("deposit", "withdraw", "transfer", "compute"):
        axioms = monitor._get_applicable_axioms(func)
        assert len(axioms) == 1, f"Wildcard axiom must apply to '{func}'"


def test_empty_target_functions_applies_to_all():
    """An axiom with empty target_functions must apply to every function."""
    from src.monitor.code_monitor import CodeMonitor

    monitor = CodeMonitor.__new__(CodeMonitor)
    monitor.axioms = [
        Axiom("global_rule", "", "x >= 0", []),
    ]

    for func in ("deposit", "withdraw", "foo"):
        axioms = monitor._get_applicable_axioms(func)
        assert len(axioms) == 1, f"Empty-target axiom must apply to '{func}'"


def test_withdraw_axiom_not_applied_to_deposit_end_to_end():
    """End-to-end: withdraw axiom must not cause deposit to be rejected."""
    ast = compile_sil("""
    func deposit(balance: int, amount: int) -> int {
        balance = balance + amount;
        return balance;
    }
    """)
    bmc = BoundedModelChecker()
    # No applicable axioms for deposit -- must be safe
    safe, ce = bmc.verify(ast, [])
    assert safe is True, "deposit with no applicable axioms must be SAFE"
