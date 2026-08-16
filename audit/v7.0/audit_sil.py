import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[2]
import sys, importlib.util, time, traceback
sys.path.insert(0, str(_REPO))

spec = importlib.util.spec_from_file_location(
    "silc", str(_REPO / "src/core/sil_compiler.py")
)
silc = importlib.util.module_from_spec(spec)
sys.modules["silc"] = silc
spec.loader.exec_module(silc)

SILCompiler = silc.SILCompiler
SILError = silc.SILError


def case(label, src, expect):
    """expect: 'reject' or 'accept'"""
    try:
        ast, cfgs = SILCompiler().compile(src)
        got = "accept"
        detail = f"{len(ast.functions)} func(s)"
    except SILError as e:
        got = "reject"
        detail = f"SILError: {str(e)[:90]}"
    except RecursionError as e:
        got = "CRASH"
        detail = "RecursionError (uncaught!)"
    except Exception as e:
        got = "CRASH"
        detail = f"{type(e).__name__}: {str(e)[:80]}"
    mark = "PASS" if got == expect else ("**FAIL**" if got != "CRASH" else "**CRASH**")
    print(f"[{mark:9}] {label}")
    print(f"             expected={expect:6} got={got:6}  {detail}")
    return got


print("#" * 80)
print("# SIL COMPILER — paper §3.2 compile-time checks")
print("#" * 80)
print()
print("--- 1. No recursion (direct) ---")
case("direct recursion", "func f(n: int) -> int { return f(n); }", "reject")

print("\n--- 2. No recursion (mutual, via call-graph DFS) ---")
case("mutual recursion a->b->a",
     "func a(n: int) -> int { return b(n); } func b(n: int) -> int { return a(n); }",
     "reject")
case("3-cycle a->b->c->a",
     "func a(n: int) -> int { return b(n); } "
     "func b(n: int) -> int { return c(n); } "
     "func c(n: int) -> int { return a(n); }",
     "reject")

print("\n--- 3. Duplicate parameter names (H-02 / KI-002 fix) ---")
case("func f(x: int, x: int)", "func f(x: int, x: int) -> int { return x; }", "reject")

print("\n--- 4. Loop bounds: positive and within global cap 10,000 ---")
case("bound 0",      "func f(x: int) -> int { while (x < 5) bound 0 { x = x + 1; } return x; }", "reject")
case("bound -1",     "func f(x: int) -> int { while (x < 5) bound -1 { x = x + 1; } return x; }", "reject")
case("bound 10000 (at cap)", "func f(x: int) -> int { while (x < 5) bound 10000 { x = x + 1; } return x; }", "accept")
case("bound 10001 (over cap)", "func f(x: int) -> int { while (x < 5) bound 10001 { x = x + 1; } return x; }", "reject")
case("bound 999999999",  "func f(x: int) -> int { while (x < 5) bound 999999999 { x = x + 1; } return x; }", "reject")
case("while with NO bound", "func f(x: int) -> int { while (x < 5) { x = x + 1; } return x; }", "reject")

print("\n--- 5. Undefined variable / undefined function ---")
case("undefined var", "func f(x: int) -> int { return zzz; }", "reject")
case("undefined func call", "func f(x: int) -> int { return nope(x); }", "reject")

print("\n--- 6. Missing return (KI-003: WARNING only, not an error) ---")
import warnings
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    got = case("no return stmt", "func f(x: int) -> int { x = x + 1; }", "accept")
    print(f"             warnings raised: {[str(x.category.__name__) for x in w]}")

print("\n--- 7. Is the .lark grammar actually used? ---")
print("             'lark' in sil_compiler.py imports:",
      "lark" in open(str(_REPO / "src/core/sil_compiler.py")).read())

print()
print("#" * 80)
print("# ADVERSARIAL / ROBUSTNESS PROBES")
print("#" * 80)

print("\n--- 8. Deeply nested expression (parser recursion depth) ---")
depth = 400
deep = "func f(x: int) -> int { return " + "(" * depth + "x" + ")" * depth + "; }"
case(f"{depth} nested parens", deep, "accept")

print("\n--- 9. Very long call chain, no cycle (DFS cost) ---")
n = 300
funcs = []
for i in range(n):
    nxt = f"g{i+1}" if i < n - 1 else None
    body = f"return {nxt}(x);" if nxt else "return x;"
    funcs.append(f"func g{i}(x: int) -> int {{ {body} }}")
t0 = time.perf_counter()
case(f"chain of {n} functions", " ".join(funcs), "accept")
print(f"             elapsed={1000*(time.perf_counter()-t0):.1f} ms")

print("\n--- 10. Bool-typed variable assignment (B-10 sort-mismatch probe) ---")
case("bool param reassigned",
     "func f(b: bool, x: int) -> int { if (x > 0) { b = false; } else { b = true; } return x; }",
     "accept")

print("\n--- 11. Division by zero literal (paper §7.1 admits NOT caught) ---")
case("x / 0", "func f(x: int) -> int { return x / 0; }", "accept")

print("\n--- 12. Nested loops each at the cap (encoding blowup probe, B-6) ---")
case("two nested loops bound 10000 each",
     "func f(x: int, y: int) -> int { while (x < 5) bound 10000 { "
     "while (y < 5) bound 10000 { y = y + 1; } x = x + 1; } return x; }",
     "accept")
print("             ^ if accepted, StmtEncoder would unroll 10000*10000 = 1e8 iterations")
