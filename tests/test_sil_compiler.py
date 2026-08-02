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


def test_direct_recursion_rejected():
    code = """
    func fib(n: int) -> int {
        if n <= 1 {
            return n;
        }
        return fib(n-1) + fib(n-2);
    }
    """
    compiler = SILCompiler()
    with pytest.raises(SILError, match="Recursion cycle detected"):
        compiler.compile(code)


# Step 6: Lexer catch-all ERROR token
def test_illegal_character_raises_error():
    """Unrecognised characters must raise SILError, not be silently dropped."""
    code = """
    func f() -> int {
        x = 1 @ 2;
        return x;
    }
    """
    compiler = SILCompiler()
    with pytest.raises(SILError, match="Illegal character"):
        compiler.compile(code)


def test_null_byte_raises_error():
    code = "func f() -> int { return 0\x00; }"
    compiler = SILCompiler()
    with pytest.raises(SILError, match="Illegal character"):
        compiler.compile(code)


# Step 7: Mutual recursion detection
def test_mutual_recursion_rejected():
    """A calls B and B calls A — must be rejected as a cycle."""
    code = """
    func a(x: int) -> int {
        return b(x);
    }
    func b(x: int) -> int {
        return a(x);
    }
    """
    compiler = SILCompiler()
    with pytest.raises(SILError, match="Recursion cycle detected"):
        compiler.compile(code)


def test_recursion_in_call_argument_rejected():
    """foo(foo(x)) must be detected as direct recursion."""
    code = """
    func foo(x: int) -> int {
        return foo(foo(x));
    }
    """
    compiler = SILCompiler()
    with pytest.raises(SILError, match="Recursion cycle detected"):
        compiler.compile(code)
