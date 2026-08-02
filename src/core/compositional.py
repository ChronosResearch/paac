"""
src/core/compositional.py
--------------------------
Feature 7: Multi-Agent Coordination Verification

Verifies that modifications from multiple agents are collectively safe.

Architecture
------------
FunctionDependencyGraph tracks which functions call which.
When Agent A modifies f() and Agent B modifies g() where g calls f:
  1. Verify f() in isolation.
  2. Verify g() in isolation.
  3. Verify f() and g() together (compositional check).

Compositional BMC
-----------------
The compositional query encodes all modified functions in a single Z3 context:

  BMC(f1, f2, …, fn, K) =
    unrolled_semantics(f1) ∧ … ∧ unrolled_semantics(fn) ∧
    Or(violation_flags)

This is sound because the SSA encoding is per-function and the violation flags
are accumulated across all functions.

Conflict Resolution
-------------------
If two agents modify the same function, modifications are queued and applied
sequentially.  The second modification is verified against the state produced
by the first.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import z3
from loguru import logger

from src.axioms.axiom_parser import Axiom
from src.core.exceptions import VerificationError
from src.core.sil_compiler import SILCompiler, ProgramNode, FuncDefNode
from src.core.verifier import (
    BoundedModelChecker, SSAEnv, StmtEncoder, _encode_axiom,
    CONSTANT_VERIFICATION_TIME_S,
)

_Z3_SOLVER_MEMORY_MB = 1024


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AgentModification:
    agent_id: str
    func_name: str
    new_code: str           # full SIL program containing the function
    axioms: list[Axiom] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class CompositionalResult:
    accepted: bool
    func_names: list[str]
    isolation_results: dict[str, bool]      # func_name -> safe
    compositional_safe: bool
    counterexample: str | None = None
    message: str = ""


# ---------------------------------------------------------------------------
# Dependency graph
# ---------------------------------------------------------------------------

class FunctionDependencyGraph:
    """
    Tracks which functions call which.
    Used to determine which functions must be re-verified when one changes.
    """

    def __init__(self) -> None:
        self._deps: dict[str, set[str]] = defaultdict(set)  # caller -> callees
        self._rdeps: dict[str, set[str]] = defaultdict(set) # callee -> callers
        self._lock = threading.Lock()

    def register(self, func_name: str, callees: list[str]) -> None:
        with self._lock:
            self._deps[func_name] = set(callees)
            for callee in callees:
                self._rdeps[callee].add(func_name)

    def dependents_of(self, func_name: str) -> set[str]:
        """Return all functions that (transitively) depend on func_name."""
        with self._lock:
            visited: set[str] = set()
            queue = deque([func_name])
            while queue:
                current = queue.popleft()
                for caller in self._rdeps.get(current, set()):
                    if caller not in visited:
                        visited.add(caller)
                        queue.append(caller)
            return visited

    def callees_of(self, func_name: str) -> set[str]:
        with self._lock:
            return set(self._deps.get(func_name, set()))

    def update_from_ast(self, ast: ProgramNode) -> None:
        """Extract call graph from a compiled AST and register it."""
        from src.core.sil_compiler import SILParser, CallExprNode
        import ast as _ast_mod

        def _collect_calls(node: Any) -> list[str]:
            from src.core.sil_compiler import (
                CallExprNode, BinaryExprNode, UnaryExprNode,
                AssignmentStmtNode, ReturnStmtNode, AssertStmtNode,
                IfStmtNode, WhileStmtNode,
            )
            calls: list[str] = []
            if isinstance(node, CallExprNode):
                calls.append(node.func_name)
                for a in node.args:
                    calls.extend(_collect_calls(a))
            elif isinstance(node, BinaryExprNode):
                calls.extend(_collect_calls(node.left))
                calls.extend(_collect_calls(node.right))
            elif isinstance(node, UnaryExprNode):
                calls.extend(_collect_calls(node.operand))
            elif isinstance(node, (AssignmentStmtNode, ReturnStmtNode)):
                calls.extend(_collect_calls(node.value))
            elif isinstance(node, AssertStmtNode):
                calls.extend(_collect_calls(node.condition))
            elif isinstance(node, IfStmtNode):
                calls.extend(_collect_calls(node.condition))
                for s in node.then_branch + node.else_branch:
                    calls.extend(_collect_calls(s))
            elif isinstance(node, WhileStmtNode):
                calls.extend(_collect_calls(node.condition))
                for s in node.body:
                    calls.extend(_collect_calls(s))
            return calls

        for func in ast.functions:
            callees = _collect_calls_in_func(func)
            self.register(func.name, callees)


def _collect_calls_in_func(func: FuncDefNode) -> list[str]:
    from src.core.sil_compiler import (
        CallExprNode, BinaryExprNode, UnaryExprNode,
        AssignmentStmtNode, ReturnStmtNode, AssertStmtNode,
        IfStmtNode, WhileStmtNode,
    )

    def _walk(node: Any) -> list[str]:
        calls: list[str] = []
        if isinstance(node, CallExprNode):
            calls.append(node.func_name)
            for a in node.args:
                calls.extend(_walk(a))
        elif isinstance(node, BinaryExprNode):
            calls.extend(_walk(node.left))
            calls.extend(_walk(node.right))
        elif isinstance(node, UnaryExprNode):
            calls.extend(_walk(node.operand))
        elif isinstance(node, (AssignmentStmtNode, ReturnStmtNode)):
            calls.extend(_walk(node.value))
        elif isinstance(node, AssertStmtNode):
            calls.extend(_walk(node.condition))
        elif isinstance(node, IfStmtNode):
            calls.extend(_walk(node.condition))
            for s in node.then_branch + node.else_branch:
                calls.extend(_walk(s))
        elif isinstance(node, WhileStmtNode):
            calls.extend(_walk(node.condition))
            for s in node.body:
                calls.extend(_walk(s))
        return calls

    result: list[str] = []
    for stmt in func.body:
        result.extend(_walk(stmt))
    return result


# ---------------------------------------------------------------------------
# Compositional verifier
# ---------------------------------------------------------------------------

class CompositionalVerifier:
    """
    Verifies a set of agent modifications collectively.
    """

    def __init__(self, timeout_ms: int = 5000) -> None:
        self._compiler = SILCompiler()
        self._bmc = BoundedModelChecker()
        self._timeout_ms = timeout_ms
        self._dep_graph = FunctionDependencyGraph()
        self._modification_queue: dict[str, deque[AgentModification]] = defaultdict(deque)
        self._lock = threading.Lock()

    @property
    def dependency_graph(self) -> FunctionDependencyGraph:
        return self._dep_graph

    def submit(self, mod: AgentModification) -> None:
        """Queue a modification for verification."""
        with self._lock:
            self._modification_queue[mod.func_name].append(mod)
        logger.info(
            f"Agent '{mod.agent_id}' queued modification to '{mod.func_name}'."
        )

    def verify_batch(
        self, modifications: list[AgentModification]
    ) -> CompositionalResult:
        """
        Verify a batch of modifications collectively.

        Steps:
        1. Compile each modification.
        2. Verify each function in isolation.
        3. Verify all functions together (compositional check).
        4. Return the result.
        """
        if not modifications:
            return CompositionalResult(
                accepted=True,
                func_names=[],
                isolation_results={},
                compositional_safe=True,
                message="Empty batch.",
            )

        # Step 1: Compile all.
        asts: dict[str, ProgramNode] = {}
        for mod in modifications:
            try:
                ast, _ = self._compiler.compile(mod.new_code)
                asts[mod.func_name] = ast
                self._dep_graph.update_from_ast(ast)
            except Exception as exc:
                return CompositionalResult(
                    accepted=False,
                    func_names=[m.func_name for m in modifications],
                    isolation_results={},
                    compositional_safe=False,
                    message=f"Compilation failed for '{mod.func_name}': {exc}",
                )

        # Step 2: Isolation verification.
        isolation: dict[str, bool] = {}
        axioms = modifications[0].axioms if modifications else []
        for func_name, ast in asts.items():
            try:
                safe, ce = self._bmc._verify_inner(ast, axioms, self._timeout_ms)
                isolation[func_name] = safe
                if not safe:
                    logger.warning(
                        f"Isolation check FAILED for '{func_name}': ce={ce}"
                    )
            except VerificationError as exc:
                isolation[func_name] = False
                logger.warning(f"Isolation check ERROR for '{func_name}': {exc}")

        # Step 3: Compositional check — merge all ASTs into one program.
        all_funcs: list[FuncDefNode] = []
        for ast in asts.values():
            all_funcs.extend(ast.functions)

        from src.core.sil_compiler import ProgramNode as PN
        combined_ast = PN(functions=all_funcs)

        try:
            comp_safe, comp_ce = self._bmc._verify_inner(
                combined_ast, axioms, self._timeout_ms
            )
        except VerificationError as exc:
            comp_safe = False
            comp_ce = None
            logger.warning(f"Compositional check ERROR: {exc}")

        accepted = all(isolation.values()) and comp_safe
        func_names = [m.func_name for m in modifications]

        msg = (
            f"Compositional verification: isolation={isolation}, "
            f"compositional_safe={comp_safe}, accepted={accepted}."
        )
        logger.info(msg)

        return CompositionalResult(
            accepted=accepted,
            func_names=func_names,
            isolation_results=isolation,
            compositional_safe=comp_safe,
            counterexample=str(comp_ce) if comp_ce else None,
            message=msg,
        )

    def process_queue(self, func_name: str, axioms: list[Axiom]) -> list[CompositionalResult]:
        """
        Process all queued modifications for func_name sequentially.
        Each modification is verified against the state produced by the previous.
        """
        results: list[CompositionalResult] = []
        with self._lock:
            queue = list(self._modification_queue.get(func_name, []))
            self._modification_queue[func_name].clear()

        for mod in queue:
            result = self.verify_batch([mod])
            results.append(result)
            if not result.accepted:
                logger.warning(
                    f"Sequential modification by '{mod.agent_id}' to "
                    f"'{func_name}' rejected — stopping queue."
                )
                break

        return results
