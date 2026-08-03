import pytest

from src.core.sil_compiler import SILCompiler
from src.core.sil_runtime import MAX_LOOP_BOUND, SILRuntime, SILRuntimeError


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


# Step 8: Global loop bound cap
def test_global_loop_bound_cap_enforced():
    """A loop with bound > MAX_LOOP_BOUND must be rejected at runtime."""
    # We need to bypass the parser's bound > 0 check and inject a large bound.
    # Easiest: compile a valid program then mutate the AST.
    code = """
    func f() -> int {
        x = 0;
        while (x < 1) bound 1 {
            x = x + 1;
        }
        return x;
    }
    """
    compiler = SILCompiler()
    ast, _ = compiler.compile(code)
    # Mutate the bound to exceed the global cap.
    from src.core.sil_compiler import WhileStmtNode

    for stmt in ast.functions[0].body:
        if isinstance(stmt, WhileStmtNode):
            stmt.bound = MAX_LOOP_BOUND + 1
    runtime = SILRuntime(ast)
    with pytest.raises(SILRuntimeError, match="global maximum"):
        runtime.execute("f", [])


def test_instruction_limit_enforced():
    """The global instruction counter must stop a loop that never terminates."""

    # Use bound = MAX_LOOP_BOUND (10000) so the global cap check passes,
    # but the loop body keeps x = 0 so the condition x < 1 is always true.
    # The instruction counter (MAX_INSTRUCTIONS = 100_000) fires before the
    # per-loop bound (10_000) because each iteration ticks the counter once
    # for the WhileStmtNode header AND once for each body statement.
    # With body = [assign], each iteration = 2 ticks. 10_000 * 2 = 20_000 < 100_000.
    # So we need a body with enough statements to push past MAX_INSTRUCTIONS.
    # Simplest: nest the loop inside a function called many times via a wrapper.
    # Instead, directly test that the counter raises by patching MAX_INSTRUCTIONS.
    import src.core.sil_runtime as rt_module

    original = rt_module.MAX_INSTRUCTIONS
    rt_module.MAX_INSTRUCTIONS = 5  # very low cap for this test
    try:
        code = """
        func f() -> int {
            x = 0;
            while (x < 1) bound 10000 {
                x = 0;
            }
            return x;
        }
        """
        compiler = SILCompiler()
        ast, _ = compiler.compile(code)
        runtime = SILRuntime(ast)
        with pytest.raises(SILRuntimeError, match="Instruction limit"):
            runtime.execute("f", [])
    finally:
        rt_module.MAX_INSTRUCTIONS = original
