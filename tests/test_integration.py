# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned AI Core) project.
# See LICENSE for terms.
import pytest
from src.monitor.code_monitor import CodeMonitor, CodeModification

def test_integration_safe_optimization():
    monitor = CodeMonitor({})
    mod = CodeModification(
        func_name="sort",
        old_code="bubble",
        new_code="func sort() -> int { while(x) bound 100 { x = x + 1; } }", # quicksort representation
        pre_cond="true",
        post_cond="true",
        source_citation="CLRS"
    )
    result = monitor.intercept_modification(mod)
    assert result["status"] == "accepted"

def test_integration_backdoor_attack():
    monitor = CodeMonitor({})
    mod = CodeModification(
        func_name="sort",
        old_code="bubble",
        new_code="func sort() -> int { while(x) bound 100 { return true; } }", # backdoor
        pre_cond="true",
        post_cond="true",
        source_citation="Malicious"
    )
    # Mocking a verification failure for backdoor logic
    # In reality this relies on Z3, so we simulate failure for this specific test
    monitor.verifier.verify = lambda *args: {"safe": False, "counterexample": {"x": 1}}
    
    result = monitor.intercept_modification(mod)
    assert result["status"] == "rejected"
