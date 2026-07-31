# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned AI Core) project.
# See LICENSE for terms.

import pytest
from src.monitor.code_monitor import CodeMonitor, CodeModification
from src.monitor.watchdog import Watchdog
import time

def test_redis_rollback_fallback():
    # Because Redis is not running locally in this CI environment,
    # the CodeMonitor should gracefully fall back to the in-memory array.
    monitor = CodeMonitor({"grounding": {"require_source_citations": False}})
    assert monitor.use_redis is False
    
    # Send a valid modification to act as the first checkpoint
    mod1 = CodeModification(
        func_name="test_func",
        old_code="",
        new_code="func test_func() -> int { return 1; }",
        pre_cond="true",
        post_cond="true"
    )
    res1 = monitor.intercept_modification(mod1)
    assert res1["status"] == "accepted"
    
    # Now send an invalid modification (e.g. backdoor) that should trigger rollback
    mod2 = CodeModification(
        func_name="test_func",
        old_code="func test_func() -> int { return 1; }",
        new_code="func test_func() -> int { return true; }", # backdoor
        pre_cond="true",
        post_cond="true"
    )
    # Mocking a verification failure for backdoor logic
    monitor.verifier.verify = lambda *args: {"safe": False, "counterexample": {"x": 1}}
    
    res2 = monitor.intercept_modification(mod2)
    assert res2["status"] == "rejected"
    # Verification failed, so it should have fallen back and retained mod1 in its memory list
    assert len(monitor.verified_checkpoints) == 1
    assert monitor.verified_checkpoints[0] == mod1
