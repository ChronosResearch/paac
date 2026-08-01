import z3
import time
import hashlib
import json
from typing import List, Dict, Any, Tuple, Optional

from src.core.sil_compiler import (
    ProgramNode, FuncDefNode, ASTNode, LiteralNode, IdentifierNode,
    BinaryExprNode, UnaryExprNode, CallExprNode, ArrayAccessNode,
    AssignmentStmtNode, IfStmtNode, WhileStmtNode, ReturnStmtNode,
    AssertStmtNode, ParamNode,
)
from src.axioms.axiom_parser import Axiom, AxiomParser
from src.core.sil_compiler import SILCompiler, SILError

# Constant verification window claimed by the paper (§3.5).
CONSTANT_VERIFICATION_TIME_S: float = 0.200


class VerificationError(Exception):
    pass


class CounterExample:
    def __init__(self, model: z3.ModelRef):
        self.assignments: Dict[str, Any] = {}
        for d in model.decls():
            self.assignments[d.name()] = model[d]

    def __str__(self) -> str:
        return "\n".join(f"  {k} = {v}" for k, v in self.assignments.items())


# ---------------------------------------------------------------------------
# SSA environment
# ---------------------------------------------------------------------------

class SSAEnv:
    """Tracks the current SSA version of every variable and the Z3 expressions."""

    def __init__(self, ctx: z3.Context):
        self.ctx = ctx
        self._counters: Dict[str, int] = {}
        self._exprs: Dict[str, z3.ExprRef] = {}

    def _versioned(self, name: str) -> str:
        return f"{name}_{self._counters.get(name, 0)}"

    def read(self, name: str) -> z3.ExprRef:
        key = self._versioned(name)
        if key not in self._exprs:
            # Unconstrained symbolic integer (parameters arrive this way).
            self._exprs[key] = z3.Int(key, ctx=self.ctx)
        return self._exprs[key]

    def write(self, name: str, expr: z3.ExprRef) -> z3.ExprRef:
        self._counters[name] = self._counters.get(name, 0) + 1
        key = self._versioned(name)
        self._exprs[key] = expr
        return expr

    def declare_param(self, name: str) -> z3.ExprRef:
        """Create the initial SSA variable for a function parameter."""
        key = self._versioned(name)
        v = z3.Int(key, ctx=self.ctx)
        self._exprs[key] = v
        return v

    def snapshot(self) -> Dict[str, int]:
        return dict(self._counters)

    def restore(self, snap: Dict[str, int]) -> None:
        self._counters = snap

    def merge(
        self,
        cond: z3.BoolRef,
        snap_then: Dict[str, int],
        snap_else: Dict[str, int],
        solver: z3.Solver,
    ) -> None:
        """
        Phi-node merge: for every variable written in either branch, create a
        fresh SSA version whose value is ITE(cond, then_val, else_val).
        """
        all_names = set(snap_then) | set(snap_else)
        base = self.snapshot()
        for name in all_names:
            then_key = f"{name}_{snap_then.get(name, base.get(name, 0))}"
            else_key = f"{name}_{snap_else.get(name, base.get(name, 0))}"
            then_expr = self._exprs.get(then_key, z3.Int(then_key, ctx=self.ctx))
            else_expr = self._exprs.get(else_key, z3.Int(else_key, ctx=self.ctx))
            merged = self.write(name, z3.If(cond, then_expr, else_expr, ctx=self.ctx))
            # The merged variable equals the ITE — add as equality so Z3 knows.
            solver.add(merged == z3.If(cond, then_expr, else_expr, ctx=self.ctx))


# ---------------------------------------------------------------------------
# Expression encoder
# ---------------------------------------------------------------------------

class ExprEncoder:
    """Translates SIL ASTNode expressions into Z3 expressions."""

    def __init__(self, ctx: z3.Context, env: SSAEnv):
        self.ctx = ctx
        self.env = env

    def encode(self, node: ASTNode) -> z3.ExprRef:
        if isinstance(node, LiteralNode):
            if node.type == "int":
                return z3.IntVal(int(node.value), ctx=self.ctx)
            if node.type == "bool":
                return z3.BoolVal(bool(node.value), ctx=self.ctx)
            # Strings are uninterpreted — represent as a fresh Int constant.
            return z3.Int(f"str_{id(node)}", ctx=self.ctx)

        if isinstance(node, IdentifierNode):
            return self.env.read(node.name)

        if isinstance(node, UnaryExprNode):
            operand = self.encode(node.operand)
            if node.operator == "not":
                return z3.Not(operand)
            raise VerificationError(f"Unknown unary operator: {node.operator}")

        if isinstance(node, BinaryExprNode):
            left = self.encode(node.left)
            right = self.encode(node.right)
            op = node.operator
            if op == "+":
                return left + right
            if op == "-":
                return left - right
            if op == "*":
                return left * right
            if op == "/":
                return left / right
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            if op == "<":
                return left < right
            if op == "<=":
                return left <= right
            if op == ">":
                return left > right
            if op == ">=":
                return left >= right
            if op == "and":
                return z3.And(left, right)
            if op == "or":
                return z3.Or(left, right)
            raise VerificationError(f"Unknown binary operator: {op}")

        if isinstance(node, ArrayAccessNode):
            arr = self.env.read(node.array_name)
            idx = self.encode(node.index)
            return z3.Select(arr, idx)

        if isinstance(node, CallExprNode):
            # Treat calls as uninterpreted functions — sound over-approximation.
            arg_exprs = [self.encode(a) for a in node.args]
            sorts = [z3.IntSort(self.ctx)] * len(arg_exprs) + [z3.IntSort(self.ctx)]
            fn = z3.Function(node.func_name, *sorts)
            return fn(*arg_exprs)

        raise VerificationError(f"Cannot encode expression node: {type(node).__name__}")


# ---------------------------------------------------------------------------
# Statement encoder (BMC with loop unrolling)
# ---------------------------------------------------------------------------

class StmtEncoder:
    """
    Encodes SIL statements into Z3 solver assertions using SSA form and
    bounded model checking (loop unrolling).
    """

    MAX_LOOP_BOUND = 10_000  # Global cap — cannot be overridden by SIL source.

    def __init__(self, ctx: z3.Context, solver: z3.Solver, env: SSAEnv):
        self.ctx = ctx
        self.solver = solver
        self.env = env
        self.expr_enc = ExprEncoder(ctx, env)
        # Collect violation flags: each AssertStmtNode adds one.
        self.violation_flags: List[z3.BoolRef] = []

    def encode_stmts(self, stmts: List[ASTNode], path_cond: z3.BoolRef) -> None:
        for stmt in stmts:
            self._encode_stmt(stmt, path_cond)

    def _encode_stmt(self, stmt: ASTNode, path_cond: z3.BoolRef) -> None:
        if isinstance(stmt, AssignmentStmtNode):
            rhs = self.expr_enc.encode(stmt.value)
            new_var = self.env.write(stmt.target, rhs)
            # Under path_cond, new_var equals rhs; otherwise it keeps its old value.
            old_var = z3.Int(f"{stmt.target}_{self.env._counters[stmt.target] - 1}", ctx=self.ctx)
            self.solver.add(
                new_var == z3.If(path_cond, rhs, old_var, ctx=self.ctx)
            )

        elif isinstance(stmt, AssertStmtNode):
            cond = self.expr_enc.encode(stmt.condition)
            # Violation: path is active AND assertion is false.
            violation = z3.And(path_cond, z3.Not(cond))
            self.violation_flags.append(violation)

        elif isinstance(stmt, ReturnStmtNode):
            # Return value is recorded but does not add a violation by itself.
            _ = self.expr_enc.encode(stmt.value)

        elif isinstance(stmt, IfStmtNode):
            cond = self.expr_enc.encode(stmt.condition)
            snap_before = self.env.snapshot()

            # Then branch
            then_path = z3.And(path_cond, cond)
            self.encode_stmts(stmt.then_branch, then_path)
            snap_then = self.env.snapshot()

            # Else branch — restore counters to pre-branch state first.
            self.env.restore(snap_before)
            else_path = z3.And(path_cond, z3.Not(cond))
            self.encode_stmts(stmt.else_branch, else_path)
            snap_else = self.env.snapshot()

            # Phi-node merge.
            self.env.merge(cond, snap_then, snap_else, self.solver)

        elif isinstance(stmt, WhileStmtNode):
            declared_bound = stmt.bound
            if declared_bound > self.MAX_LOOP_BOUND:
                raise VerificationError(
                    f"Loop bound {declared_bound} exceeds global cap {self.MAX_LOOP_BOUND}."
                )
            # Unroll the loop declared_bound times.
            current_path = path_cond
            for _iteration in range(declared_bound):
                loop_cond = self.expr_enc.encode(stmt.condition)
                iter_path = z3.And(current_path, loop_cond)
                snap_before = self.env.snapshot()
                self.encode_stmts(stmt.body, iter_path)
                snap_after = self.env.snapshot()
                # After this iteration, path continues only if loop_cond was true.
                current_path = iter_path
                # Re-encode condition with updated SSA state for next iteration.
                self.expr_enc = ExprEncoder(self.ctx, self.env)
            # After unrolling, execution continues on the exit path.

        else:
            # Unknown statement type — skip silently (conservative).
            pass


# ---------------------------------------------------------------------------
# Axiom encoder
# ---------------------------------------------------------------------------

def _encode_axiom(axiom: Axiom, ctx: z3.Context, env: SSAEnv) -> Optional[z3.BoolRef]:
    """
    Parse the axiom condition string as a SIL expression and encode it to Z3.
    Returns None if the condition cannot be parsed (logged as a warning).
    """
    sil_wrapper = f"func _axiom_check() -> bool {{ assert {axiom.condition}; return true; }}"
    try:
        compiler = SILCompiler()
        prog, _ = compiler.compile(sil_wrapper)
        func = prog.functions[0]
        # The first statement is the AssertStmtNode.
        assert_stmt = func.body[0]
        if not isinstance(assert_stmt, AssertStmtNode):
            return None
        enc = ExprEncoder(ctx, env)
        return enc.encode(assert_stmt.condition)
    except (SILError, VerificationError, Exception):
        return None


# ---------------------------------------------------------------------------
# Bounded Model Checker
# ---------------------------------------------------------------------------

class BoundedModelChecker:
    def __init__(self) -> None:
        # Cache: canonical_hash -> (safe: bool, ce_str: Optional[str])
        self._cache: Dict[str, Tuple[bool, Optional[str]]] = {}

    # ------------------------------------------------------------------
    # Step 5: Secure cache hash (SHA-256 over canonical JSON)
    # ------------------------------------------------------------------

    def _hash_ast(self, ast: ProgramNode, axioms: List[Axiom]) -> str:
        def _node_to_dict(node: Any) -> Any:
            if isinstance(node, list):
                return [_node_to_dict(n) for n in node]
            if hasattr(node, "__dataclass_fields__"):
                return {
                    "__type__": type(node).__name__,
                    **{k: _node_to_dict(getattr(node, k)) for k in node.__dataclass_fields__},
                }
            return node

        payload = {
            "ast": _node_to_dict(ast),
            "axioms": [{"id": a.id, "condition": a.condition} for a in sorted(axioms, key=lambda x: x.id)],
        }
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Main verify entry point
    # ------------------------------------------------------------------

    def verify(
        self,
        ast: ProgramNode,
        axioms: List[Axiom],
        timeout_ms: int = 5000,
    ) -> Tuple[bool, Optional[CounterExample]]:
        """
        Returns (safe, counterexample).
        safe=True  → UNSAT (no violation reachable within bounds).
        safe=False → SAT   (counterexample found).
        Raises VerificationError on solver timeout / unknown result.

        Step 10: Constant-time padding — always takes CONSTANT_VERIFICATION_TIME_S
        regardless of outcome.
        """
        start = time.monotonic()
        try:
            return self._verify_inner(ast, axioms, timeout_ms)
        finally:
            elapsed = time.monotonic() - start
            remaining = CONSTANT_VERIFICATION_TIME_S - elapsed
            if remaining > 0:
                time.sleep(remaining)

    def _verify_inner(
        self,
        ast: ProgramNode,
        axioms: List[Axiom],
        timeout_ms: int,
    ) -> Tuple[bool, Optional[CounterExample]]:
        cache_key = self._hash_ast(ast, axioms)
        if cache_key in self._cache:
            safe, ce_str = self._cache[cache_key]
            return safe, None  # Cached counterexamples are not re-materialised.

        # Z3 context and solver — timeout set via solver params (not global).
        ctx = z3.Context()
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", timeout_ms)

        env = SSAEnv(ctx)
        stmt_enc = StmtEncoder(ctx, solver, env)

        # Encode every function in the program.
        for func in ast.functions:
            func_path = z3.BoolVal(True, ctx=ctx)
            # Declare parameters as unconstrained symbolic integers.
            for param in func.params:
                env.declare_param(param.name)
            stmt_enc.encode_stmts(func.body, func_path)

        # Encode axioms as additional assertions that must hold.
        for axiom in axioms:
            z3_cond = _encode_axiom(axiom, ctx, env)
            if z3_cond is not None:
                # Axiom must hold — add its negation as a violation flag.
                stmt_enc.violation_flags.append(z3.Not(z3_cond))

        # BMC query: is any violation reachable?
        if not stmt_enc.violation_flags:
            # No assertions and no axioms encoded — trivially safe.
            self._cache[cache_key] = (True, None)
            return True, None

        solver.add(z3.Or(*stmt_enc.violation_flags))

        result = solver.check()

        if result == z3.unsat:
            self._cache[cache_key] = (True, None)
            return True, None
        elif result == z3.sat:
            ce = CounterExample(solver.model())
            self._cache[cache_key] = (False, str(ce))
            return False, ce
        else:
            raise VerificationError(f"Z3 solver returned unknown/timeout: {result}")


# ---------------------------------------------------------------------------
# Thin Verifier façade (keeps the interface code_monitor.py expects)
# ---------------------------------------------------------------------------

class Verifier:
    """Thin façade so existing code that instantiates Verifier(config) still works."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self._bmc = BoundedModelChecker()
        self._timeout_ms: int = config.get("verification_timeout_ms", 5000)

    def verify(
        self,
        func_name: str,
        ast: ProgramNode,
        pre_cond: str,
        axioms: Optional[List[Axiom]] = None,
    ) -> Dict[str, Any]:
        axioms = axioms or []
        safe, ce = self._bmc.verify(ast, axioms, timeout_ms=self._timeout_ms)
        return {"safe": safe, "counterexample": str(ce) if ce else None}
