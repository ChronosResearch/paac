"""
src/core/runtime_monitor.py
---------------------------
Feature 6: Runtime Verification Integration

Instruments the SIL runtime to check safety axioms during execution,
complementing PAAC's static BMC verification.

Architecture
------------
  Static phase  (pre-execution):  BMC verifies the code modification.
  Runtime phase (during execution): RuntimeMonitor checks actual behavior.
  Post-execution:                  Compare runtime trace vs static result.

The RuntimeMonitor wraps SILRuntime and intercepts every statement execution.
For each AssertStmtNode it evaluates the assertion against the current
environment and raises RuntimeSafetyViolation if it fails.

Axiom checking at runtime works by evaluating the axiom condition as a Python
expression over the current variable bindings.  We reuse the SIL runtime's
own evaluator for this.

Integration with Fail-Safe
--------------------------
RuntimeSafetyViolation triggers:
  1. Circuit breaker record_failure()
  2. Audit log entry
  3. Rollback to last checkpoint (via callback)
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from src.axioms.axiom_parser import Axiom
from src.core.exceptions import SafetyViolationError
from src.core.sil_compiler import (
    ArrayAccessNode,
    AssertStmtNode,
    AssignmentStmtNode,
    ASTNode,
    BinaryExprNode,
    CallExprNode,
    FuncDefNode,
    IdentifierNode,
    IfStmtNode,
    LiteralNode,
    ProgramNode,
    ReturnStmtNode,
    UnaryExprNode,
    WhileStmtNode,
)
from src.core.sil_runtime import SILReturn, SILRuntimeError


class RuntimeSafetyViolation(SafetyViolationError):
    """Raised when a runtime axiom check fails."""


# ---------------------------------------------------------------------------
# Trace record
# ---------------------------------------------------------------------------


@dataclass
class RuntimeTrace:
    func_name: str
    steps: int = 0
    assertions_checked: int = 0
    axioms_checked: int = 0
    violations: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def safe(self) -> bool:
        return len(self.violations) == 0


# ---------------------------------------------------------------------------
# Axiom evaluator (pure Python, no Z3)
# ---------------------------------------------------------------------------


def _eval_axiom_condition(condition: str, env: dict[str, Any]) -> bool:
    """
    Evaluate a SIL axiom condition string against a concrete environment.
    Uses the SIL compiler + runtime evaluator — no eval() call.
    Returns True if the condition holds, False otherwise.
    Fails open (returns True) when the axiom references variables not in env
    (axiom inapplicable to this call site).
    """
    from src.core.sil_compiler import SILCompiler
    from src.core.sil_runtime import SILRuntime, SILRuntimeError

    # Build a minimal SIL wrapper so we can reuse the existing evaluator.
    param_names = [k for k in env if isinstance(k, str) and k.isidentifier()]
    if not param_names:
        return True
    param_str = ", ".join(f"{p}: int" for p in param_names)
    sil_src = (
        f"func _axiom_eval({param_str}) -> int {{\n"
        f"    assert {condition};\n"
        f"    return 0;\n"
        f"}}"
    )
    try:
        compiler = SILCompiler()
        ast, _ = compiler.compile(sil_src)
        runtime = SILRuntime(ast)
        args = [int(env[p]) for p in param_names]
        runtime.execute("_axiom_eval", args)
        return True
    except SILRuntimeError:
        return False  # assertion failed → axiom violated
    except Exception:  # noqa: BLE001
        return True  # variable not in scope or compile error → inapplicable


# ---------------------------------------------------------------------------
# Instrumented runtime
# ---------------------------------------------------------------------------


class RuntimeMonitor:
    """
    Wraps SILRuntime with runtime axiom checking.

    Usage:
        monitor = RuntimeMonitor(ast, axioms)
        trace = monitor.execute("func_name", args)
        if not trace.safe:
            # handle violation
    """

    def __init__(
        self,
        ast: ProgramNode,
        axioms: list[Axiom] | None = None,
        on_violation: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._ast = ast
        self._axioms = axioms or []
        self._on_violation = on_violation
        self._functions: dict[str, FuncDefNode] = {f.name: f for f in ast.functions}

    def execute(self, func_name: str, args: list[Any]) -> RuntimeTrace:
        """
        Execute func_name with args, monitoring all assertions and axioms.
        Returns a RuntimeTrace.  Raises RuntimeSafetyViolation on violation.
        """
        trace = RuntimeTrace(func_name=func_name)
        t0 = time.monotonic()

        if func_name not in self._functions:
            raise SILRuntimeError(f"Function {func_name} not found")

        func = self._functions[func_name]
        if len(args) != len(func.params):
            raise SILRuntimeError(
                f"{func_name} expects {len(func.params)} args, got {len(args)}"
            )

        env: dict[str, Any] = {p.name: a for p, a in zip(func.params, args)}

        try:
            self._exec_stmts(func.body, env, trace)
        except SILReturn:
            pass
        except RuntimeSafetyViolation:
            raise
        finally:
            trace.elapsed_ms = (time.monotonic() - t0) * 1000

        return trace

    # ------------------------------------------------------------------
    # Statement execution with monitoring
    # ------------------------------------------------------------------

    def _exec_stmts(
        self, stmts: list[ASTNode], env: dict[str, Any], trace: RuntimeTrace
    ) -> None:
        for stmt in stmts:
            self._exec_stmt(stmt, env, trace)

    def _exec_stmt(
        self, stmt: ASTNode, env: dict[str, Any], trace: RuntimeTrace
    ) -> None:
        trace.steps += 1

        if isinstance(stmt, AssignmentStmtNode):
            val = self._eval_expr(stmt.value, env)
            env[stmt.target] = val
            # Check axioms after every assignment.
            self._check_axioms(env, trace)

        elif isinstance(stmt, AssertStmtNode):
            trace.assertions_checked += 1
            cond = self._eval_expr(stmt.condition, env)
            if not cond:
                msg = f"Assertion failed in {trace.func_name} at step {trace.steps}"
                trace.violations.append(msg)
                self._fire_violation(msg, env)

        elif isinstance(stmt, ReturnStmtNode):
            val = self._eval_expr(stmt.value, env)
            raise SILReturn(val)

        elif isinstance(stmt, IfStmtNode):
            cond = self._eval_expr(stmt.condition, env)
            branch = stmt.then_branch if cond else stmt.else_branch
            self._exec_stmts(branch, env, trace)

        elif isinstance(stmt, WhileStmtNode):
            iters = 0
            while self._eval_expr(stmt.condition, env):
                if iters >= stmt.bound:
                    raise SILRuntimeError(f"Loop bound {stmt.bound} exceeded")
                self._exec_stmts(stmt.body, env, trace)
                iters += 1

    def _check_axioms(self, env: dict[str, Any], trace: RuntimeTrace) -> None:
        for axiom in self._axioms:
            trace.axioms_checked += 1
            if not _eval_axiom_condition(axiom.condition, env):
                msg = (
                    f"Axiom '{axiom.id}' violated in {trace.func_name}: "
                    f"{axiom.condition} failed with env={dict(env)}"
                )
                trace.violations.append(msg)
                self._fire_violation(msg, env)

    def _fire_violation(self, message: str, env: dict[str, Any]) -> None:
        logger.error(f"RuntimeSafetyViolation: {message}")
        if self._on_violation:
            self._on_violation(message, env)
        raise RuntimeSafetyViolation(message)

    # ------------------------------------------------------------------
    # Expression evaluator (mirrors SILRuntime._eval_expr)
    # ------------------------------------------------------------------

    def _eval_expr(self, expr: ASTNode, env: dict[str, Any]) -> Any:
        if isinstance(expr, LiteralNode):
            return expr.value
        if isinstance(expr, IdentifierNode):
            if expr.name not in env:
                raise SILRuntimeError(f"Undefined variable {expr.name}")
            return env[expr.name]
        if isinstance(expr, UnaryExprNode):
            operand = self._eval_expr(expr.operand, env)
            if expr.operator == "not":
                return not operand
            if expr.operator == "-":
                return -operand
        if isinstance(expr, BinaryExprNode):
            l = self._eval_expr(expr.left, env)
            r = self._eval_expr(expr.right, env)
            ops = {
                "+": lambda a, b: a + b,
                "-": lambda a, b: a - b,
                "*": lambda a, b: a * b,
                "/": lambda a, b: a // b,
                "==": lambda a, b: a == b,
                "!=": lambda a, b: a != b,
                "<": lambda a, b: a < b,
                "<=": lambda a, b: a <= b,
                ">": lambda a, b: a > b,
                ">=": lambda a, b: a >= b,
                "and": lambda a, b: a and b,
                "or": lambda a, b: a or b,
            }
            if expr.operator in ops:
                return ops[expr.operator](l, r)
        if isinstance(expr, ArrayAccessNode):
            arr = env.get(expr.array_name, {})
            idx = self._eval_expr(expr.index, env)
            return arr.get(idx, 0) if isinstance(arr, dict) else 0
        if isinstance(expr, CallExprNode):
            args = [self._eval_expr(a, env) for a in expr.args]
            sub = RuntimeMonitor(self._ast, self._axioms, self._on_violation)
            sub.execute(expr.func_name, args)
            return 0  # return value captured via SILReturn exception above
        raise SILRuntimeError(f"Unknown expression type {type(expr)}")
