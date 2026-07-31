# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned AI Core) project.
# See LICENSE for terms.
import pytest
from src.core.runtime import SILRuntime
from src.core.exceptions import SafetyViolationError

def test_adversarial_memory_overflow():
    runtime = SILRuntime({"max_memory_bytes": 100})
    with pytest.raises(SafetyViolationError):
        runtime.allocate(200)

def test_adversarial_unauthorized_io():
    runtime = SILRuntime({"safe_io_whitelist": ["print_to_log"]})
    with pytest.raises(SafetyViolationError):
        runtime.execute_call("delete_file", [])
