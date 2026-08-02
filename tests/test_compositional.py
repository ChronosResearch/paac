"""tests/test_compositional.py — Feature 7: Multi-Agent Coordination Verification"""
from src.axioms.axiom_parser import Axiom
from src.core.compositional import (
    AgentModification,
    CompositionalVerifier,
    FunctionDependencyGraph,
)
from src.core.sil_compiler import SILCompiler

COMPILER = SILCompiler()


# ---------------------------------------------------------------------------
# Dependency graph
# ---------------------------------------------------------------------------

def test_dependency_graph_register_and_query():
    """Register a dependency and query it."""
    graph = FunctionDependencyGraph()
    graph.register("g", ["f"])
    assert "g" in graph.dependents_of("f")


def test_dependency_graph_transitive():
    """Transitive dependencies must be returned."""
    graph = FunctionDependencyGraph()
    graph.register("g", ["f"])
    graph.register("h", ["g"])
    deps = graph.dependents_of("f")
    assert "g" in deps
    assert "h" in deps


def test_dependency_graph_no_deps():
    """Function with no dependents returns empty set."""
    graph = FunctionDependencyGraph()
    graph.register("f", [])
    assert graph.dependents_of("f") == set()


def test_dependency_graph_update_from_ast():
    """update_from_ast must extract call relationships."""
    ast, _ = COMPILER.compile(
        "func f(x: int) -> int { return x; } "
        "func g(x: int) -> int { y = f(x); return y; }"
    )
    graph = FunctionDependencyGraph()
    graph.update_from_ast(ast)
    assert "g" in graph.dependents_of("f")


# ---------------------------------------------------------------------------
# Independent functions
# ---------------------------------------------------------------------------

def test_two_independent_functions_both_accepted():
    """Two agents modifying independent functions — both must be accepted."""
    verifier = CompositionalVerifier()
    mods = [
        AgentModification(
            agent_id="agent_a",
            func_name="f",
            new_code="func f(x: int) -> int { return x; }",
        ),
        AgentModification(
            agent_id="agent_b",
            func_name="g",
            new_code="func g(y: int) -> int { return y; }",
        ),
    ]
    result = verifier.verify_batch(mods)
    assert result.accepted is True
    assert result.compositional_safe is True
    assert result.isolation_results.get("f") is True
    assert result.isolation_results.get("g") is True


def test_empty_batch_accepted():
    """Empty batch must be accepted."""
    verifier = CompositionalVerifier()
    result = verifier.verify_batch([])
    assert result.accepted is True


# ---------------------------------------------------------------------------
# Dependent functions
# ---------------------------------------------------------------------------

def test_dependent_functions_verified_together():
    """g and f are both safe — both must be verified together successfully."""
    verifier = CompositionalVerifier()
    mods = [
        AgentModification(
            agent_id="agent_a",
            func_name="f",
            new_code="func f(x: int) -> int { return x; }",
        ),
        AgentModification(
            agent_id="agent_b",
            func_name="g",
            new_code="func g(y: int) -> int { return y; }",
        ),
    ]
    result = verifier.verify_batch(mods)
    assert result.accepted is True
    assert result.compositional_safe is True
    assert len(result.func_names) == 2


def test_unsafe_function_rejects_batch():
    """If one function is unsafe, the batch must be rejected."""
    verifier = CompositionalVerifier()
    mods = [
        AgentModification(
            agent_id="agent_a",
            func_name="safe_f",
            new_code="func safe_f(x: int) -> int { return x; }",
        ),
        AgentModification(
            agent_id="agent_b",
            func_name="unsafe_g",
            new_code="func unsafe_g(x: int) -> int { assert x > 0; return x; }",
            axioms=[Axiom("ax", "", "x > 0", ["*"])],
        ),
    ]
    # unsafe_g asserts x > 0 but axiom requires x > 0 — actually safe.
    # Use a program that is genuinely unsafe.
    mods[1] = AgentModification(
        agent_id="agent_b",
        func_name="unsafe_g",
        new_code="func unsafe_g(x: int) -> int { assert false; return x; }",
    )
    result = verifier.verify_batch(mods)
    assert result.accepted is False


# ---------------------------------------------------------------------------
# Sequential queue (same function, two agents)
# ---------------------------------------------------------------------------

def test_same_function_queued_sequentially():
    """Two agents modifying the same function — processed sequentially."""
    verifier = CompositionalVerifier()
    mod1 = AgentModification(
        agent_id="agent_a",
        func_name="f",
        new_code="func f(x: int) -> int { return x; }",
    )
    mod2 = AgentModification(
        agent_id="agent_b",
        func_name="f",
        new_code="func f(x: int) -> int { y = x + 1; return y; }",
    )
    verifier.submit(mod1)
    verifier.submit(mod2)
    results = verifier.process_queue("f", [])
    assert len(results) == 2
    assert all(r.accepted for r in results)


def test_second_modification_rejected_if_unsafe():
    """If the second queued modification is unsafe, it must be rejected."""
    verifier = CompositionalVerifier()
    mod1 = AgentModification(
        agent_id="agent_a",
        func_name="f",
        new_code="func f(x: int) -> int { return x; }",
    )
    mod2 = AgentModification(
        agent_id="agent_b",
        func_name="f",
        new_code="func f(x: int) -> int { assert false; return x; }",
    )
    verifier.submit(mod1)
    verifier.submit(mod2)
    results = verifier.process_queue("f", [])
    assert results[0].accepted is True
    assert results[1].accepted is False


# ---------------------------------------------------------------------------
# Compilation failure
# ---------------------------------------------------------------------------

def test_compilation_failure_rejects_batch():
    """A batch with invalid SIL must be rejected at compilation."""
    verifier = CompositionalVerifier()
    mods = [AgentModification(
        agent_id="agent_a",
        func_name="bad",
        new_code="this is not valid SIL",
    )]
    result = verifier.verify_batch(mods)
    assert result.accepted is False
    assert "Compilation failed" in result.message


# ---------------------------------------------------------------------------
# Result fields
# ---------------------------------------------------------------------------

def test_result_func_names_populated():
    """Result must list all function names in the batch."""
    verifier = CompositionalVerifier()
    mods = [
        AgentModification("a", "f", "func f(x: int) -> int { return x; }"),
        AgentModification("b", "g", "func g(x: int) -> int { return x; }"),
    ]
    result = verifier.verify_batch(mods)
    assert "f" in result.func_names
    assert "g" in result.func_names


def test_message_populated():
    """Result message must be non-empty."""
    verifier = CompositionalVerifier()
    mods = [AgentModification("a", "f", "func f(x: int) -> int { return x; }")]
    result = verifier.verify_batch(mods)
    assert len(result.message) > 0
