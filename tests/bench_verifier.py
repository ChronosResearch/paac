import time

from src.axioms.axiom_parser import Axiom
from src.core.sil_compiler import ProgramNode
from src.core.verifier import BoundedModelChecker


def test_benchmark_verifier():
    bmc = BoundedModelChecker()
    axioms = [Axiom("AX_1", "", "balance >= 0", ["*"])]
    ast = ProgramNode([])

    start = time.perf_counter()
    for _ in range(50):
        # We pass empty axioms so it hits cache (or doesn't if hash varies)
        # Actually hash of identical AST and axioms should be identical
        bmc.verify(ast, axioms)

    end = time.perf_counter()
    duration = end - start

    print(f"\\n[BENCHMARK] 50 verifications took {duration:.4f}s")
    # This should be fast due to caching
    assert duration < 5.0
