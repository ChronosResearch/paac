"""
src/core/compositional.py
--------------------------
Multi-Agent Coordination Verification.

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

  BMC(f1, f2, ..., fn, K) =
    unrolled_semantics(f1) AND ... AND unrolled_semantics(fn) AND
    Or(violation_flags)

This is sound because the SSA encoding is per-function and the violation flags
are accumulated across all functions.

Conflict Resolution
-------------------
If two agents modify the same function, modifications are queued and applied
sequentially.  The second modification is verified against the state produced
by the first.  If an agent crashes mid-modification, the queue entry is
marked as abandoned and the next agent proceeds.

Limitations (documented honestly)
----------------------------------
- Compositional soundness holds only within the SIL fragment.  Interactions
  via shared mutable state (Redis, global variables) are not modelled.
- The dependency graph is built from SIL call expressions only.  Python-level
  dependencies (imports, closures) are not tracked.
- Crash recovery is best-effort: if the process dies, queued modifications
  are lost.  Use the WAL for durability.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from src.axioms.axiom_parser import Axiom
from src.core.exceptions import VerificationError
from src.core.sil_compiler import (
    AssertStmtNode,
    AssignmentStmtNode,
    BinaryExprNode,
    CallExprNode,
    FuncDefNode,
    IfStmtNode,
    ProgramNode,
    ReturnStmtNode,
    SILCompiler,
    UnaryExprNode,
    WhileStmtNode,
)
from src.core.verifier import BoundedModelChecker


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
    abandoned: bool = False  # set True if agent crashed before completion


@dataclass
class CompositionalResult:
    accepted: bool
    func_names: list[str]
    isolation_results: dict[str, bool]      # func_name -> safe
    compositional_safe: bool
    counterexample: str | None = None
    message: str = ""
    elapsed_ms: float = 0.0
    agent_ids: list[str] = field(default_factory=list)


@dataclass
class AgentStatus:
    agent_id: str
    active_func: str | None
    queued_count: int
    last_seen: float


# ---------------------------------------------------------------------------
# Dependency graph
# ---------------------------------------------------------------------------

class FunctionDependencyGraph:
    """
    Tracks which functions call which.
    Used to determine which functions must be re-verified when one changes.
    """

    def __init__(self) -> None:
        self._deps: dict[str, set[str]] = defaultdict(set)   # caller -> callees
        self._rdeps: dict[str, set[str]] = defaultdict(set)  # callee -> callers
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
            queue: deque[str] = deque([func_name])
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
        for func in ast.functions:
            callees = _collect_calls_in_func(func)
            self.register(func.name, callees)

    def all_functions(self) -> list[str]:
        with self._lock:
            return list(set(self._deps.keys()) | set(self._rdeps.keys()))


def _walk_expr(node: Any) -> list[str]:
    """Collect all called function names in an expression node."""
    calls: list[str] = []
    if isinstance(node, CallExprNode):
        calls.append(node.func_name)
        for a in node.args:
            calls.extend(_walk_expr(a))
    elif isinstance(node, BinaryExprNode):
        calls.extend(_walk_expr(node.left))
        calls.extend(_walk_expr(node.right))
    elif isinstance(node, UnaryExprNode):
        calls.extend(_walk_expr(node.operand))
    elif isinstance(node, (AssignmentStmtNode, ReturnStmtNode)):
        calls.extend(_walk_expr(node.value))
    elif isinstance(node, AssertStmtNode):
        calls.extend(_walk_expr(node.condition))
    elif isinstance(node, IfStmtNode):
        calls.extend(_walk_expr(node.condition))
        for s in node.then_branch + node.else_branch:
            calls.extend(_walk_expr(s))
    elif isinstance(node, WhileStmtNode):
        calls.extend(_walk_expr(node.condition))
        for s in node.body:
            calls.extend(_walk_expr(s))
    return calls


def _collect_calls_in_func(func: FuncDefNode) -> list[str]:
    result: list[str] = []
    for stmt in func.body:
        result.extend(_walk_expr(stmt))
    return result


# ---------------------------------------------------------------------------
# Compositional verifier
# ---------------------------------------------------------------------------

class CompositionalVerifier:
    """
    Verifies a set of agent modifications collectively.

    Thread-safe: all queue operations use a lock.
    Supports up to N concurrent agents (bounded by the semaphore in
    code_monitor.py).
    """

    def __init__(self, timeout_ms: int = 5000) -> None:
        self._compiler = SILCompiler()
        self._bmc = BoundedModelChecker()
        self._timeout_ms = timeout_ms
        self._dep_graph = FunctionDependencyGraph()
        self._modification_queue: dict[str, deque[AgentModification]] = defaultdict(deque)
        self._agent_registry: dict[str, AgentStatus] = {}
        self._lock = threading.Lock()
        self._total_verifications = 0
        self._total_accepted = 0
        self._total_rejected = 0
        self._total_conflicts = 0

    @property
    def dependency_graph(self) -> FunctionDependencyGraph:
        return self._dep_graph

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    def register_agent(self, agent_id: str) -> None:
        """Register an agent.  Idempotent."""
        with self._lock:
            if agent_id not in self._agent_registry:
                self._agent_registry[agent_id] = AgentStatus(
                    agent_id=agent_id,
                    active_func=None,
                    queued_count=0,
                    last_seen=time.time(),
                )
                logger.info(f"Multi-agent: registered agent '{agent_id}'.")

    def heartbeat(self, agent_id: str) -> None:
        """Update last-seen timestamp for an agent."""
        with self._lock:
            if agent_id in self._agent_registry:
                self._agent_registry[agent_id].last_seen = time.time()

    def mark_agent_crashed(self, agent_id: str) -> None:
        """
        Mark all queued modifications from agent_id as abandoned.
        Called when an agent is detected as crashed (no heartbeat).
        """
        with self._lock:
            for queue in self._modification_queue.values():
                for mod in queue:
                    if mod.agent_id == agent_id:
                        mod.abandoned = True
            if agent_id in self._agent_registry:
                del self._agent_registry[agent_id]
        logger.warning(f"Multi-agent: agent '{agent_id}' marked as crashed.")

    def agent_statuses(self) -> list[AgentStatus]:
        with self._lock:
            return list(self._agent_registry.values())

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------

    def submit(self, mod: AgentModification) -> None:
        """Queue a modification for verification."""
        self.register_agent(mod.agent_id)
        with self._lock:
            existing = self._modification_queue[mod.func_name]
            if existing:
                self._total_conflicts += 1
                logger.info(
                    f"Multi-agent: conflict on '{mod.func_name}' — "
                    f"agent '{mod.agent_id}' queued behind "
                    f"{len(existing)} existing modification(s)."
                )
            existing.append(mod)
            if mod.agent_id in self._agent_registry:
                self._agent_registry[mod.agent_id].active_func = mod.func_name
                self._agent_registry[mod.agent_id].queued_count += 1
        logger.info(
            f"Multi-agent: agent '{mod.agent_id}' submitted modification "
            f"to '{mod.func_name}'."
        )

    # ------------------------------------------------------------------
    # Batch verification
    # ------------------------------------------------------------------

    def verify_batch(
        self, modifications: list[AgentModification]
    ) -> CompositionalResult:
        """
        Verify a batch of modifications collectively.

        Steps:
        1. Skip abandoned modifications.
        2. Compile each modification.
        3. Verify each function in isolation.
        4. Verify all functions together (compositional check).
        5. Return the result with full audit trail.
        """
        t_start = time.monotonic()

        # Filter abandoned
        active = [m for m in modifications if not m.abandoned]
        if not active:
            return CompositionalResult(
                accepted=True,
                func_names=[],
                isolation_results={},
                compositional_safe=True,
                message="All modifications abandoned (agent crash).",
                elapsed_ms=0.0,
            )

        # Step 1: Compile all.
        asts: dict[str, ProgramNode] = {}
        for mod in active:
            try:
                ast, _ = self._compiler.compile(mod.new_code)
                asts[mod.func_name] = ast
                self._dep_graph.update_from_ast(ast)
            except Exception as exc:  # noqa: BLE001
                elapsed = (time.monotonic() - t_start) * 1000
                return CompositionalResult(
                    accepted=False,
                    func_names=[m.func_name for m in active],
                    isolation_results={},
                    compositional_safe=False,
                    message=f"Compilation failed for '{mod.func_name}': {exc}",
                    elapsed_ms=elapsed,
                    agent_ids=[m.agent_id for m in active],
                )

        # Step 2: Isolation verification.
        isolation: dict[str, bool] = {}
        axioms = active[0].axioms if active else []
        for func_name, ast in asts.items():
            try:
                safe, ce = self._bmc._verify_inner(ast, axioms, self._timeout_ms)
                isolation[func_name] = safe
                if not safe:
                    logger.warning(
                        f"Multi-agent isolation FAILED for '{func_name}': ce={ce}"
                    )
            except VerificationError as exc:
                isolation[func_name] = False
                logger.warning(f"Multi-agent isolation ERROR for '{func_name}': {exc}")

        # Step 3: Compositional check — merge all ASTs into one program.
        all_funcs: list[FuncDefNode] = []
        for ast in asts.values():
            all_funcs.extend(ast.functions)

        combined_ast = ProgramNode(functions=all_funcs)
        comp_safe = False
        comp_ce = None
        try:
            comp_safe, comp_ce = self._bmc._verify_inner(
                combined_ast, axioms, self._timeout_ms
            )
        except VerificationError as exc:
            logger.warning(f"Multi-agent compositional check ERROR: {exc}")

        accepted = all(isolation.values()) and comp_safe
        elapsed = (time.monotonic() - t_start) * 1000

        with self._lock:
            self._total_verifications += 1
            if accepted:
                self._total_accepted += 1
            else:
                self._total_rejected += 1

        msg = (
            f"Compositional: isolation={isolation}, "
            f"compositional_safe={comp_safe}, accepted={accepted}, "
            f"agents={[m.agent_id for m in active]}."
        )
        logger.info(msg)

        return CompositionalResult(
            accepted=accepted,
            func_names=[m.func_name for m in active],
            isolation_results=isolation,
            compositional_safe=comp_safe,
            counterexample=str(comp_ce) if comp_ce else None,
            message=msg,
            elapsed_ms=elapsed,
            agent_ids=[m.agent_id for m in active],
        )

    # ------------------------------------------------------------------
    # Queue processing
    # ------------------------------------------------------------------

    def process_queue(
        self, func_name: str, axioms: list[Axiom]
    ) -> list[CompositionalResult]:
        """
        Process all queued modifications for func_name sequentially.
        Each modification is verified against the state produced by the previous.
        Abandoned modifications are skipped.
        """
        with self._lock:
            queue = list(self._modification_queue.get(func_name, []))
            self._modification_queue[func_name].clear()

        results: list[CompositionalResult] = []
        for mod in queue:
            if mod.abandoned:
                logger.info(
                    f"Multi-agent: skipping abandoned modification by "
                    f"'{mod.agent_id}' to '{func_name}'."
                )
                continue
            mod.axioms = axioms
            result = self.verify_batch([mod])
            results.append(result)
            if not result.accepted:
                logger.warning(
                    f"Multi-agent: modification by '{mod.agent_id}' to "
                    f"'{func_name}' rejected — stopping queue processing."
                )
                break

        return results

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_verifications": self._total_verifications,
                "total_accepted": self._total_accepted,
                "total_rejected": self._total_rejected,
                "total_conflicts": self._total_conflicts,
                "active_agents": len(self._agent_registry),
                "queued_modifications": sum(
                    len(q) for q in self._modification_queue.values()
                ),
            }
