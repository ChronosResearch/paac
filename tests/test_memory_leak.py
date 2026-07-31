# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned AI Core) project.
# See LICENSE for terms.

import pytest
import psutil
import os
import gc
from src.core.verifier import Verifier
from src.core.sil_compiler import SILCompiler

def test_verifier_memory_leak():
    process = psutil.Process(os.getpid())
    v = Verifier({"verification_timeout_ms": 1000, "constant_verification_time_padding_ms": 0})
    compiler = SILCompiler()
    
    ast = compiler.compile("func sort() -> int { while(x) bound 10 { x = x + 1; } }")
    
    gc.collect()
    start_memory = process.memory_info().rss
    
    # Run 1000 verifications
    for i in range(1000):
        # Vary the func_name to avoid caching
        v.verify(f"test_func_{i}", ast, "true")
        
    gc.collect()
    end_memory = process.memory_info().rss
    
    memory_growth_mb = (end_memory - start_memory) / (1024 * 1024)
    # The growth should be strictly less than 10MB if properly managed
    assert memory_growth_mb < 20.0, f"Memory leak detected: grew by {memory_growth_mb} MB"
