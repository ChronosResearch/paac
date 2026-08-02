import operator
from typing import Any

from src.core.sil_compiler import (
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

# Step 8: Global caps — cannot be overridden by SIL source code.
MAX_LOOP_BOUND = 10_000
MAX_INSTRUCTIONS = 100_000


class SILRuntimeError(Exception):
    pass


class SILReturn(Exception):
    def __init__(self, value: Any):
        self.value = value


class SILRuntime:
    def __init__(self, ast: ProgramNode):
        self.functions: dict[str, FuncDefNode] = {f.name: f for f in ast.functions}
        self.env: list[dict[str, Any]] = []
        self._instruction_count: int = 0

    def _tick(self) -> None:
        self._instruction_count += 1
        import src.core.sil_runtime as _rt  # noqa: PLW0406

        if self._instruction_count > _rt.MAX_INSTRUCTIONS:
            raise SILRuntimeError(
                f"Instruction limit {_rt.MAX_INSTRUCTIONS} exceeded. Possible infinite loop."
            )

    def execute(self, func_name: str, args: list[Any]) -> Any:
        if func_name not in self.functions:
            raise SILRuntimeError(f"Function {func_name} not found")
        func = self.functions[func_name]
        if len(args) != len(func.params):
            raise SILRuntimeError(
                f"Function {func_name} expects {len(func.params)} arguments, got {len(args)}"
            )

        local_env = {p.name: a for p, a in zip(func.params, args)}
        self.env.append(local_env)

        try:
            for stmt in func.body:
                self._exec_stmt(stmt)
        except SILReturn as r:
            self.env.pop()
            return r.value

        self.env.pop()
        return None

    def _exec_stmt(self, stmt: ASTNode):
        self._tick()
        if isinstance(stmt, AssignmentStmtNode):
            val = self._eval_expr(stmt.value)
            self.env[-1][stmt.target] = val
        elif isinstance(stmt, IfStmtNode):
            cond = self._eval_expr(stmt.condition)
            if cond:
                for s in stmt.then_branch:
                    self._exec_stmt(s)
            else:
                for s in stmt.else_branch:
                    self._exec_stmt(s)
        elif isinstance(stmt, WhileStmtNode):
            # Step 8: Enforce global cap independent of declared bound.
            effective_bound = stmt.bound
            if effective_bound > MAX_LOOP_BOUND:
                raise SILRuntimeError(
                    f"Declared loop bound {effective_bound} exceeds global maximum {MAX_LOOP_BOUND}."
                )
            iters = 0
            while self._eval_expr(stmt.condition):
                self._tick()  # count each loop iteration against the global instruction budget
                if iters >= effective_bound:
                    raise SILRuntimeError(f"Loop bound {effective_bound} exceeded")
                for s in stmt.body:
                    self._exec_stmt(s)
                iters += 1
        elif isinstance(stmt, ReturnStmtNode):
            val = self._eval_expr(stmt.value)
            raise SILReturn(val)
        elif isinstance(stmt, AssertStmtNode):
            cond = self._eval_expr(stmt.condition)
            if not cond:
                raise SILRuntimeError("Assertion failed")

    def _eval_expr(self, expr: ASTNode) -> Any:
        if isinstance(expr, LiteralNode):
            return expr.value
        elif isinstance(expr, IdentifierNode):
            if expr.name not in self.env[-1]:
                raise SILRuntimeError(f"Undefined variable {expr.name}")
            return self.env[-1][expr.name]
        elif isinstance(expr, UnaryExprNode):
            operand = self._eval_expr(expr.operand)
            if expr.operator == "not":
                return not operand
            raise SILRuntimeError(f"Unknown unary operator: {expr.operator}")
        elif isinstance(expr, BinaryExprNode):
            l = self._eval_expr(expr.left)
            r = self._eval_expr(expr.right)
            ops = {
                "+": operator.add,
                "-": operator.sub,
                "*": operator.mul,
                "/": operator.floordiv,
                "==": operator.eq,
                "!=": operator.ne,
                "<": operator.lt,
                "<=": operator.le,
                ">": operator.gt,
                ">=": operator.ge,
            }
            if expr.operator in ops:
                return ops[expr.operator](l, r)
            elif expr.operator == "and":
                return l and r
            elif expr.operator == "or":
                return l or r
        elif isinstance(expr, CallExprNode):
            args = [self._eval_expr(a) for a in expr.args]
            return self.execute(expr.func_name, args)
        raise SILRuntimeError(f"Unknown expression type {type(expr)}")
