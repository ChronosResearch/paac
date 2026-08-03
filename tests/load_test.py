"""
Load test: verifications with bounded concurrency — measure p95 latency.
Uses _verify_inner directly (in-process Z3) to avoid subprocess fork issues
under concurrent load. The subprocess isolation is tested separately.
Run with: PYTHONPATH=. python3.11 tests/load_test.py
"""

import concurrent.futures
import statistics
import time

from src.core.sil_compiler import SILCompiler
from src.core.verifier import BoundedModelChecker

COMPILER = SILCompiler()

PROGRAMS = [
    "func f(x: int) -> int { return x; }",
    "func add(a: int, b: int) -> int { return a + b; }",
    "func safe(x: int) -> int { assert x == x; return x; }",
    "func neg(x: int) -> int { y = -x; assert y == 0 - x; return y; }",
    "func loop(n: int) -> int { i = 0; while (i < n) bound 5 { i = i + 1; } return i; }",
]


def run_one(i):
    code = PROGRAMS[i % len(PROGRAMS)]
    ast, _ = COMPILER.compile(code)
    bmc = BoundedModelChecker()
    t0 = time.monotonic()
    # Use _verify_inner directly for concurrent load test (avoids fork-under-threads issue)
    bmc._verify_inner(ast, [], timeout_ms=5000)
    return time.monotonic() - t0


def main():
    N = 40
    MAX_WORKERS = 4
    print(f"Running {N} verifications with {MAX_WORKERS} concurrent workers...")

    latencies = []
    errors = 0
    t_start = time.monotonic()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(run_one, i) for i in range(N)]
        for fut in concurrent.futures.as_completed(futures):
            try:
                latencies.append(fut.result())
            except Exception as e:
                errors += 1
                print(f"  ERROR: {e}")

    total = time.monotonic() - t_start

    if not latencies:
        print("LOAD TEST FAILED: no successful verifications")
        return

    latencies.sort()
    p50 = statistics.median(latencies)
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[min(int(len(latencies) * 0.99), len(latencies) - 1)]

    print(f"\nResults ({len(latencies)}/{N} succeeded, {errors} errors):")
    print(f"  Total wall time : {total:.2f}s")
    print(f"  p50 latency     : {p50*1000:.0f}ms")
    print(f"  p95 latency     : {p95*1000:.0f}ms")
    print(f"  p99 latency     : {p99*1000:.0f}ms")
    print(f"  Min             : {min(latencies)*1000:.0f}ms")
    print(f"  Max             : {max(latencies)*1000:.0f}ms")

    assert len(latencies) >= N * 0.95, f"Too many errors: {errors}/{N}"
    assert p95 < 10.0, f"p95 latency {p95:.2f}s exceeds 10s threshold"
    print("\nLOAD TEST PASSED")


if __name__ == "__main__":
    main()
