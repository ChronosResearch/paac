import pathlib as _pl
_REPO = _pl.Path(__file__).resolve().parents[2]
import sys, importlib.util
sys.path.insert(0, str(_REPO))
spec = importlib.util.spec_from_file_location(
    "silc", str(_REPO / "src/core/sil_compiler.py"))
silc = importlib.util.module_from_spec(spec); sys.modules["silc"] = silc
spec.loader.exec_module(silc)

print("Default sys.recursionlimit =", sys.getrecursionlimit())
print()
print("Finding the minimum nesting depth that triggers an uncaught RecursionError:")
lo = None
for d in (50, 100, 150, 175, 200, 225, 250, 300, 400):
    src = "func f(x: int) -> int { return " + "(" * d + "x" + ")" * d + "; }"
    try:
        silc.SILCompiler().compile(src)
        status = "ok"
    except silc.SILError as e:
        status = "SILError (handled)"
    except RecursionError:
        status = "*** RecursionError — UNCAUGHT ***"
        if lo is None:
            lo = d
    print(f"  depth={d:4}  payload={len(src):5} bytes  -> {status}")

print()
if lo:
    src = "func f(x: int) -> int { return " + "(" * lo + "x" + ")" * lo + "; }"
    print(f"MINIMUM CRASHING PAYLOAD: depth={lo}, {len(src)} bytes")
    print("Exception type is RecursionError, which is NOT a subclass of SILError:")
    print("   issubclass(RecursionError, silc.SILError) =",
          issubclass(RecursionError, silc.SILError))
    print()
    print("code_monitor.intercept_modification catches only:")
    print("   (CompilationError, SILError), (VerificationError, VerifierError), GroundingError")
    print("   => RecursionError escapes the handler while the FileLock is held.")

print()
print("Is there ANY source-length / payload-size guard in the compiler or API?")
import subprocess
for pat in ["MAX_SOURCE", "max_length", "max_len", "len(source)", "MAX_PROGRAM", "recursionlimit"]:
    r = subprocess.run(["grep", "-rn", pat, str(_REPO / "src")],
                       capture_output=True, text=True)
    print(f"  grep '{pat}': {r.stdout.strip() or 'NO MATCH'}")
