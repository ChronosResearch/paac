import pytest
from src.core.sil_compiler import SILCompiler, SILError

def test_valid_sil_parses_correctly():
    code = """
    func add(a: int, b: int) -> int {
        return a + b;
    }
    """
    compiler = SILCompiler()
    ast, cfgs = compiler.compile(code)
    assert len(ast.functions) == 1
    assert ast.functions[0].name == "add"
    assert "add" in cfgs

def test_invalid_sil_no_loop_bound():
    code = """
    func loop() -> int {
        while (true) {
            return 1;
        }
    }
    """
    compiler = SILCompiler()
    with pytest.raises(SILError, match="Expected token type KEYWORD"):
        compiler.compile(code)

def test_type_mismatch_caught():
    code = """
    func mismatch() -> int {
        x = 5;
        x = true;
        return x;
    }
    """
    compiler = SILCompiler()
    with pytest.raises(SILError, match="Type mismatch"):
        compiler.compile(code)

def test_recursion_rejected():
    code = """
    func fib(n: int) -> int {
        if n <= 1 {
            return n;
        }
        return fib(n-1) + fib(n-2);
    }
    """
    compiler = SILCompiler()
    with pytest.raises(SILError, match="Recursion detected"):
        compiler.compile(code)
