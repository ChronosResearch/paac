# Copyright (c) 2026 Shashank Kumar. All rights reserved.
import gc
import os
import psutil
from src.core.verifier import Verifier
from src.core.sil_compiler import SILCompiler

def stress_test():
    v = Verifier({"verification_timeout_ms": 1000, "constant_verification_time_padding_ms": 0})
    compiler = SILCompiler()
    ast = compiler.compile("func sort() -> int { while(x) bound 10 { x = x + 1; } }")
    
    gc.collect()
    process = psutil.Process(os.getpid())
    start_memory = process.memory_info().rss
    
    for i in range(1000):
        # Slightly alter the AST string representation to avoid cache hits if needed,
        # but here we just pass the same one and rely on cache.
        # Actually, let's bypass cache to stress test Z3.
        v.solver.push()
        v.solver.check()
        v.solver.pop()
        
        # Periodic reset logic as in actual code
        if i % 100 == 0:
            v.solver.reset()
            gc.collect()
            
    end_memory = process.memory_info().rss
    growth_mb = (end_memory - start_memory) / (1024 * 1024)
    print(f"Memory growth over 1000 runs: {growth_mb:.2f} MB")
    assert growth_mb < 20, f"Memory leak detected! Growth: {growth_mb}MB"
