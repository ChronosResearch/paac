import threading
import time

from src.axioms.axiom_loader import AxiomDatabase
from src.axioms.axiom_parser import Axiom
from src.monitor.interceptor import CodeModification, Interceptor


def run_load_test():
    db = AxiomDatabase()
    db.axioms["AX1"] = Axiom("AX1", "", "true", ["*"])
    interceptor = Interceptor(db)

    mod = CodeModification("foo.py", "bar", "func bar() -> int { return 1; }", "agent")

    total_requests = 100
    threads = []

    def worker():
        for _ in range(10):
            interceptor.intercept(mod)

    start = time.time()
    for _ in range(10):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    end = time.time()
    duration = end - start
    print(f"\\n[LOAD TEST] {total_requests} requests processed in {duration:.4f}s")
    print(f"Throughput: {total_requests / duration:.2f} req/s")


if __name__ == "__main__":
    run_load_test()
