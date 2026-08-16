import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[2]
import sys, time, json
import importlib.util
spec = importlib.util.spec_from_file_location(
    "pc", str(_REPO / "src/pcm/proof_checker.py")
)
pc = importlib.util.module_from_spec(spec)
sys.modules["pc"] = pc
spec.loader.exec_module(pc)

# Real axiom set from config/axioms.yaml
AXIOMS = [
    {"id": "no_negative_balance", "condition": "balance >= 0"},
    {"id": "counter_in_range", "condition": "counter >= 0"},
    {"id": "result_bounded", "condition": "result >= 0"},
    {"id": "no_exit", "condition": "exit_called == 0"},
    {"id": "no_network", "condition": "network_calls == 0"},
]
checker = pc.ProofChecker(AXIOMS)


def run(label, proof, n=200):
    r = checker.check(proof)
    t0 = time.perf_counter()
    for _ in range(n):
        checker.check(proof)
    per = (time.perf_counter() - t0) / n * 1000
    print(f"{label}  verdict={r.verdict.value.upper()}  covered={r.covered_axioms}")
    print(f"     reason={r.reason[:80]}")
    print(f"     mean_latency={per:.4f} ms  ({n} iterations)")
    return r


print("=" * 78)
print("EXPLOIT 1 - empty proof, zero axioms declared, single Conclude step")
print("=" * 78)
run("E1", {
    "version": "1.0",
    "axioms": [],
    "preconditions": {},
    "steps": [{"type": "Conclude", "result": "safe"}],
    "conclusion": "safe",
})

print()
print("=" * 78)
print("EXPLOIT 2 - Assume the obligation, then ApplyAxiom on all 5 real axioms")
print("=" * 78)
run("E2", {
    "version": "1.0",
    "axioms": [a["id"] for a in AXIOMS],
    "preconditions": {},
    "steps": [
        {"type": "Assume", "var": "balance",       "constraint": "balance >= 0"},
        {"type": "Assume", "var": "counter",       "constraint": "counter >= 0"},
        {"type": "Assume", "var": "result",        "constraint": "result >= 0"},
        {"type": "Assume", "var": "exit_called",   "constraint": "exit_called == 0"},
        {"type": "Assume", "var": "network_calls", "constraint": "network_calls == 0"},
        {"type": "ApplyAxiom", "axiom_id": "no_negative_balance", "condition": "balance >= 0"},
        {"type": "ApplyAxiom", "axiom_id": "counter_in_range",    "condition": "counter >= 0"},
        {"type": "ApplyAxiom", "axiom_id": "result_bounded",      "condition": "result >= 0"},
        {"type": "ApplyAxiom", "axiom_id": "no_exit",             "condition": "exit_called == 0"},
        {"type": "ApplyAxiom", "axiom_id": "no_network",          "condition": "network_calls == 0"},
        {"type": "Conclude", "result": "safe"},
    ],
    "conclusion": "safe",
})

print()
print("=" * 78)
print("EXPLOIT 3 - Assign balance = -500, then Assume it is >= 0, then Assert it")
print("=" * 78)
run("E3", {
    "version": "1.0", "axioms": [], "preconditions": {},
    "steps": [
        {"type": "Assign", "var": "balance", "expr": "-500"},
        {"type": "Assume", "var": "balance", "constraint": "balance >= 0"},
        {"type": "Assert", "condition": "balance >= 0"},
        {"type": "Conclude", "result": "safe"},
    ],
    "conclusion": "safe",
})

print()
print("=" * 78)
print("EXPLOIT 4 - LoopInvariant used as an arbitrary fact oracle")
print("=" * 78)
run("E4", {
    "version": "1.0", "axioms": [], "preconditions": {},
    "steps": [
        {"type": "LoopInvariant", "invariant": "balance >= 0", "bound": 1},
        {"type": "Assert", "condition": "balance >= 0"},
        {"type": "Conclude", "result": "safe"},
    ],
    "conclusion": "safe",
})

print()
print("=" * 78)
print("EXPLOIT 5 - BranchSafe is agent-asserted, never checked")
print("=" * 78)
run("E5", {
    "version": "1.0", "axioms": [], "preconditions": {},
    "steps": [
        {"type": "BranchSafe", "then_safe": True, "else_safe": True},
        {"type": "Conclude", "result": "safe"},
    ],
    "conclusion": "safe",
})

print()
print("=" * 78)
print("CONTROL - honest proof that SHOULD fail (no Assume laundering)")
print("=" * 78)
run("C1", {
    "version": "1.0", "axioms": ["no_negative_balance"], "preconditions": {},
    "steps": [
        {"type": "Assign", "var": "balance", "expr": "-500"},
        {"type": "ApplyAxiom", "axiom_id": "no_negative_balance", "condition": "balance >= 0"},
        {"type": "Conclude", "result": "safe"},
    ],
    "conclusion": "safe",
})

print()
print("=" * 78)
print("CONTROL 2 - is declared_axioms forced to cover the APPLICABLE axioms?")
print("=" * 78)
r = checker.check({
    "version": "1.0", "axioms": [], "preconditions": {},
    "steps": [{"type": "Conclude", "result": "safe"}],
    "conclusion": "safe",
})
print("     ProofChecker was constructed with 5 axioms:")
print("       ", [a["id"] for a in AXIOMS])
print(f"     proof declared 0 axioms -> covered_axioms={r.covered_axioms}")
print(f"     verdict={r.verdict.value.upper()}  <-- accepted while covering NOTHING")
