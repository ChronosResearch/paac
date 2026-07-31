import pytest
from src.core.sil_compiler import SILCompiler
from src.core.sil_runtime import SILRuntime, SILRuntimeError

def test_runtime_execution():
    code = """
    func add(a: int, b: int) -> int {
        return a + b;
    }
    """
    compiler = SILCompiler()
    ast, _ = compiler.compile(code)
    runtime = SILRuntime(ast)
    assert runtime.execute("add", [2, 3]) == 5

def test_loop_bound_enforced():
    code = """
    func loop() -> int {
        x = 0;
        while (x < 10) bound 5 {
            x = x + 1;
        }
        return x;
    }
    """
    compiler = SILCompiler()
    ast, _ = compiler.compile(code)
    runtime = SILRuntime(ast)
    with pytest.raises(SILRuntimeError, match="Loop bound 5 exceeded"):
        runtime.execute("loop", [])

def test_assertion_failure():
    code = """
    func check() -> int {
        assert false;
        return 0;
    }
    """
    compiler = SILCompiler()
    ast, _ = compiler.compile(code)
    runtime = SILRuntime(ast)
    with pytest.raises(SILRuntimeError, match="Assertion failed"):
        runtime.execute("check", [])
