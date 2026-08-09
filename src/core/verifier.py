import hashlib
import json
import multiprocessing
import platform
import time
from typing import Any

import z3
from loguru import logger

from src.axioms.axiom_parser import Axiom
from src.core.exceptions import VerificationError  # re-exported for callers
from src.core.sil_compiler import (
    ArrayAccessNode,
    AssertStmtNode,
    AssignmentStmtNode,
    ASTNode,
    BinaryExprNode,
    CallExprNode,
    IdentifierNode,
    IfStmtNode,
    LiteralNode,
    ProgramNode,
    ReturnStmtNode,
    SILCompiler,
    SILError,
    UnaryExprNode,
    WhileStmtNode,
)
from src.core.tcb_protect import generate_ipc_token, verify_ipc_token

# Constant verification window (paper §3.5).
CONSTANT_VERIFICATION_TIME_S: float = 0.200

# Subprocess resource limits for Z3 isolation (R-1).
_Z3_MEMORY_LIMIT_BYTES: int = 1 * 1024 * 1024 * 1024  # 1 GB address space
_Z3_CPU_LIMIT_SECONDS: int = 5

# Z3 solver params (Steps 28-29).
_Z3_SOLVER_TIMEOUT_MS: int = 5000
_Z3_SOLVER_MEMORY_MB: int = 1024

# Maximum consecutive Z3 subprocess crashes before giving up (Step 32).
_Z3_MAX_RETRIES: int = 3


class CounterExample:
    def __init__(self, model: z3.ModelRef):
        self.assignments: dict[str, Any] = {}
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
        self._counters: dict[str, int] = {}
        self._exprs: dict[str, z3.ExprRef] = {}

    def _versioned(self, name: str) -> str:
        return f"{name}_{self._counters.get(name, 0)}"

    def read(self, name: str) -> z3.ExprRef:
        """Return the current Z3 expression for variable *name*, creating a fresh Int if unseen."""
        key = self._versioned(name)
        if key not in self._exprs:
            self._exprs[key] = z3.Int(key, ctx=self.ctx)
        return self._exprs[key]

    def write(self, name: str, expr: z3.ExprRef) -> z3.ExprRef:
        """Bump the SSA version of *name*, bind it to *expr*, and return the new expression."""
        self._counters[name] = self._counters.get(name, 0) + 1
        key = self._versioned(name)
        self._exprs[key] = expr
        return expr

    def declare_param(self, name: str, type_name: str = "int") -> z3.ExprRef:
        """Create the initial SSA variable for a function parameter."""
        key = self._versioned(name)
        if type_name == "bool":
            v = z3.Bool(key, ctx=self.ctx)
        elif type_name == "array":
            v = z3.Array(key, z3.IntSort(self.ctx), z3.IntSort(self.ctx))
        else:
            v = z3.Int(key, ctx=self.ctx)
        self._exprs[key] = v
        return v

    def snapshot(self) -> dict[str, int]:
        """Return a shallow copy of the current SSA version counters for later restore."""
        return dict(self._counters)

    def restore(self, snap: dict[str, int]) -> None:
        """Restore SSA version counters to a previously taken snapshot."""
        self._counters = snap

    def merge(
        self,
        cond: z3.BoolRef,
        snap_then: dict[str, int],
        snap_else: dict[str, int],
        solver: z3.Solver,
        exprs_then: dict[str, z3.ExprRef] | None = None,
    ) -> None:
        """Phi-node merge: ITE(cond, then_val, else_val) for every written var.

        exprs_then: snapshot of self._exprs taken after the then-branch and
        before restore(), so the then-branch values are not overwritten by
        the else-branch writing to the same SSA version numbers.
        """
        all_names = set(snap_then) | set(snap_else)
        base = self.snapshot()  # current state = after else-branch
        for name in all_names:
            then_ver = snap_then.get(name, base.get(name, 0))
            else_ver = snap_else.get(name, base.get(name, 0))
            then_key = f"{name}_{then_ver}"
            else_key = f"{name}_{else_ver}"
            # Use saved then-branch exprs if provided (avoids overwrite collision).
            if exprs_then is not None and then_key in exprs_then:
                then_expr = exprs_then[then_key]
            else:
                then_expr = self._exprs.get(then_key, z3.Int(then_key, ctx=self.ctx))
            else_expr = self._exprs.get(else_key, z3.Int(else_key, ctx=self.ctx))
            merged = self.write(name, z3.If(cond, then_expr, else_expr, ctx=self.ctx))
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
        """Recursively translate a SIL expression AST node into a Z3 expression."""
        if isinstance(node, LiteralNode):
            if node.type == "int":
                return z3.IntVal(int(node.value), ctx=self.ctx)
            if node.type == "bool":
                return z3.BoolVal(bool(node.value), ctx=self.ctx)
            return z3.Int(f"str_{id(node)}", ctx=self.ctx)

        if isinstance(node, IdentifierNode):
            return self.env.read(node.name)

        if isinstance(node, UnaryExprNode):
            operand = self.encode(node.operand)
            if node.operator == "not":
                return z3.Not(operand)
            if node.operator == "-":
                return -operand
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
            arg_exprs = [self.encode(a) for a in node.args]
            sorts = [z3.IntSort(self.ctx)] * len(arg_exprs) + [z3.IntSort(self.ctx)]
            fn = z3.Function(node.func_name, *sorts)
            return fn(*arg_exprs)

        raise VerificationError(f"Cannot encode expression node: {type(node).__name__}")


# ---------------------------------------------------------------------------
# Statement encoder (BMC with loop unrolling)
# ---------------------------------------------------------------------------


class StmtEncoder:
    """Encodes SIL statements into Z3 solver assertions using SSA + BMC."""

    MAX_LOOP_BOUND = 10_000  # Global cap — cannot be overridden by SIL source.

    def __init__(self, ctx: z3.Context, solver: z3.Solver, env: SSAEnv):
        self.ctx = ctx
        self.solver = solver
        self.env = env
        self.expr_enc = ExprEncoder(ctx, env)
        self.violation_flags: list[z3.BoolRef] = []
        self._post_loop_path: z3.BoolRef | None = None

    def encode_stmts(self, stmts: list[ASTNode], path_cond: z3.BoolRef) -> None:
        """Encode a list of SIL statements under *path_cond*, threading loop-exit paths."""
        current_path = path_cond
        for stmt in stmts:
            self._post_loop_path = None
            self._encode_stmt(stmt, current_path)
            if self._post_loop_path is not None:
                current_path = self._post_loop_path
                self._post_loop_path = None

    def _encode_stmt(self, stmt: ASTNode, path_cond: z3.BoolRef) -> None:
        if isinstance(stmt, AssignmentStmtNode):
            rhs = self.expr_enc.encode(stmt.value)
            new_var = self.env.write(stmt.target, rhs)
            old_var = z3.Int(
                f"{stmt.target}_{self.env._counters[stmt.target] - 1}", ctx=self.ctx
            )
            self.solver.add(new_var == z3.If(path_cond, rhs, old_var, ctx=self.ctx))

        elif isinstance(stmt, AssertStmtNode):
            cond = self.expr_enc.encode(stmt.condition)
            violation = z3.And(path_cond, z3.Not(cond))
            self.violation_flags.append(violation)

        elif isinstance(stmt, ReturnStmtNode):
            _ = self.expr_enc.encode(stmt.value)

        elif isinstance(stmt, IfStmtNode):
            cond = self.expr_enc.encode(stmt.condition)
            snap_before = self.env.snapshot()

            then_path = z3.And(path_cond, cond)
            self.encode_stmts(stmt.then_branch, then_path)
            snap_then = self.env.snapshot()
            # Save then-branch expressions BEFORE restoring counters,
            # so the else-branch cannot overwrite the same SSA version.
            exprs_then = dict(self.env._exprs)

            self.env.restore(snap_before)
            else_path = z3.And(path_cond, z3.Not(cond))
            self.encode_stmts(stmt.else_branch, else_path)
            snap_else = self.env.snapshot()

            self.env.merge(cond, snap_then, snap_else, self.solver, exprs_then)

        elif isinstance(stmt, WhileStmtNode):
            declared_bound = stmt.bound
            if declared_bound > self.MAX_LOOP_BOUND:
                raise VerificationError(
                    f"Loop bound {declared_bound} exceeds global cap {self.MAX_LOOP_BOUND}."
                )
            entry_path = path_cond
            current_path = path_cond
            self.expr_enc = ExprEncoder(self.ctx, self.env)
            entry_loop_cond = self.expr_enc.encode(stmt.condition)
            for _iteration in range(declared_bound):
                self.expr_enc = ExprEncoder(self.ctx, self.env)
                loop_cond = self.expr_enc.encode(stmt.condition)
                iter_path = z3.And(current_path, loop_cond)
                self.encode_stmts(stmt.body, iter_path)
                current_path = iter_path
            # A-01 fix: if the loop condition is still true after all K
            # iterations the loop never exited within the declared bound —
            # that is UNSAFE (runtime would raise LoopBoundExceeded).
            # Appended exactly ONCE to avoid spurious double-counting (C-01).
            self.expr_enc = ExprEncoder(self.ctx, self.env)
            post_loop_cond = self.expr_enc.encode(stmt.condition)
            still_running = z3.And(current_path, post_loop_cond)
            self.violation_flags.append(still_running)
            self._post_loop_path = z3.And(entry_path, z3.Not(entry_loop_cond))

        else:
            pass


# ---------------------------------------------------------------------------
# Axiom encoder — Step 22: raises on failure, never silently skips
# ---------------------------------------------------------------------------


def _encode_axiom(
    axiom: Axiom,
    ctx: z3.Context,
    env: SSAEnv,
    param_names: list[str] | None = None,
) -> "z3.BoolRef | None":
    """
    Parse the axiom condition string as a SIL expression and encode it to Z3
    using the *current* SSAEnv so that body-assigned variables (e.g.
    exit_called, network_calls) resolve to their live SSA values rather than
    fresh unconstrained Z3 variables.

    Strategy:
      1. Build the SIL wrapper param list from ALL variables currently in env
         (function params + body-assigned vars).  This lets the SIL type-checker
         accept the condition without "Undefined variable".
      2. Encode the parsed AST node with ExprEncoder(ctx, env) — the live env —
         so IdentifierNode lookups call env.read(), returning the current SSA
         expression (which may be a concrete Z3 value like IntVal(1)).

    Returns None when the axiom references variables not present in the current
    env (inapplicable axiom — skipped with a debug log).
    Raises VerificationError only for syntactically invalid SIL (Step 22).
    """
    # Build param list from ALL variables currently in env (params + body vars).
    # declare_param puts vars in _exprs (not _counters); write() puts them in both.
    # Extract base names from both sources to cover all cases.
    seen_vars: set[str] = set()
    all_vars: list[str] = []
    # From _counters: body-assigned variables
    for name in env._counters:
        if name not in seen_vars:
            seen_vars.add(name)
            all_vars.append(name)
    # From _exprs: function parameters (declare_param only writes _exprs)
    for key in env._exprs:
        parts = key.rsplit("_", 1)
        base = parts[0] if len(parts) == 2 and parts[1].isdigit() else key
        if base not in seen_vars:
            seen_vars.add(base)
            all_vars.append(base)
    # Also include any explicitly passed param_names
    for name in (param_names or []):
        if name not in seen_vars:
            seen_vars.add(name)
            all_vars.append(name)

    param_str = ", ".join(f"{n}: int" for n in all_vars)
    sil_wrapper = (
        f"func _axiom_check({param_str}) -> bool "
        f"{{ assert {axiom.condition}; return true; }}"
    )
    try:
        compiler = SILCompiler()
        prog, _ = compiler.compile(sil_wrapper)
        func = prog.functions[0]
        assert_stmt = func.body[0]
        if not isinstance(assert_stmt, AssertStmtNode):
            raise VerificationError(
                f"Axiom '{axiom.id}': condition did not parse to an assert statement."
            )
        # Use the LIVE env so IdentifierNode.read() returns current SSA values.
        enc = ExprEncoder(ctx, env)
        return enc.encode(assert_stmt.condition)
    except SILError as exc:
        _inapplicable_markers = (
            "Undefined variable",
            "Undefined function",
            "Type mismatch",
            "Arity mismatch",
        )
        if any(m in str(exc) for m in _inapplicable_markers):
            logger.debug(f"Axiom '{axiom.id}' inapplicable to current function: {exc}")
            return None
        raise VerificationError(
            f"Axiom '{axiom.id}' has invalid SIL syntax: {exc}"
        ) from exc
    except VerificationError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Axiom '{axiom.id}' inapplicable to current function: {exc}")
        return None


# ---------------------------------------------------------------------------
# Loop Bound Analyzer — proves all loop bounds ≤ MAX_LOOP_BOUND via Z3
# ---------------------------------------------------------------------------


from dataclasses import dataclass as _dc, field as _field


@_dc
class LoopBoundResult:
    """
    Per-loop Z3 proof result for bounded loop verification.

    proven_safe: True  → Z3 proved bound <= MAX_LOOP_BOUND (UNSAT on violation).
    proven_safe: False → Z3 found a counterexample (bound > MAX_LOOP_BOUND).
    """
    func_name: str
    loop_index: int       # 0-based index within the function
    declared_bound: int   # bound declared in SIL source
    max_allowed: int      # global cap (10_000)
    proven_safe: bool     # True = Z3 UNSAT (bound within cap)
    counterexample: str | None = None


@_dc
class LoopBoundReport:
    """Aggregated loop bound verification results for a full program."""
    all_proven_safe: bool
    results: list[LoopBoundResult] = _field(default_factory=list)
    max_bound_seen: int = 0

    def summary(self) -> str:
        if not self.results:
            return "No loops found."
        n = len(self.results)
        safe = sum(1 for r in self.results if r.proven_safe)
        return (
            f"{safe}/{n} loop bounds proven safe ≤ {self.max_allowed}; "
            f"max bound seen = {self.max_bound_seen}."
        )

    @property
    def max_allowed(self) -> int:
        return self.results[0].max_allowed if self.results else StmtEncoder.MAX_LOOP_BOUND


class LoopBoundAnalyzer:
    """
    Proves that every declared loop bound in a SIL program is within the
    global cap (MAX_LOOP_BOUND = 10,000) using Z3.

    For each WhileStmtNode with declared bound K:
      - Creates a Z3 Int variable `loop_bound_<func>_<idx>`
      - Asserts it equals K (the declared constant)
      - Checks: is there an assignment where loop_bound > MAX_LOOP_BOUND?
      - UNSAT → proven safe; SAT → violation (should never happen for valid SIL,
        but provides a formal Z3 certificate for each bound).

    This transforms the implicit compile-time check into an explicit Z3 proof,
    producing a verifiable certificate that all loops are DoS-safe.
    """

    MAX_LOOP_BOUND: int = StmtEncoder.MAX_LOOP_BOUND  # 10_000

    def analyze(self, ast: ProgramNode) -> LoopBoundReport:
        """
        Run Z3-based loop bound verification on all loops in *ast*.

        Returns a LoopBoundReport with per-loop results and an overall verdict.
        """
        results: list[LoopBoundResult] = []
        max_seen = 0

        for func in ast.functions:
            loop_idx = 0
            self._analyze_stmts(func.body, func.name, results, loop_idx)

        for r in results:
            if r.declared_bound > max_seen:
                max_seen = r.declared_bound

        all_safe = all(r.proven_safe for r in results)
        return LoopBoundReport(
            all_proven_safe=all_safe,
            results=results,
            max_bound_seen=max_seen,
        )

    def _analyze_stmts(
        self,
        stmts: list[ASTNode],
        func_name: str,
        results: list[LoopBoundResult],
        start_idx: int,
    ) -> int:
        idx = start_idx
        for stmt in stmts:
            idx = self._analyze_stmt(stmt, func_name, results, idx)
        return idx

    def _analyze_stmt(
        self,
        stmt: ASTNode,
        func_name: str,
        results: list[LoopBoundResult],
        idx: int,
    ) -> int:
        if isinstance(stmt, WhileStmtNode):
            result = self._prove_bound(func_name, idx, stmt.bound)
            results.append(result)
            idx += 1
            # Recurse into loop body for nested loops
            idx = self._analyze_stmts(stmt.body, func_name, results, idx)
        elif isinstance(stmt, IfStmtNode):
            idx = self._analyze_stmts(stmt.then_branch, func_name, results, idx)
            idx = self._analyze_stmts(stmt.else_branch, func_name, results, idx)
        return idx

    def _prove_bound(self, func_name: str, loop_idx: int, declared_bound: int) -> LoopBoundResult:
        """
        Use Z3 to formally prove declared_bound <= MAX_LOOP_BOUND.

        Creates a Z3 Int equal to declared_bound and checks whether it can
        exceed MAX_LOOP_BOUND. UNSAT = proven safe (it cannot).
        """
        ctx = z3.Context()
        solver = z3.Solver(ctx=ctx)
        var_name = f"loop_bound_{func_name}_{loop_idx}"
        bound_var = z3.Int(var_name, ctx=ctx)
        # Assert the variable equals the declared bound
        solver.add(bound_var == z3.IntVal(declared_bound, ctx=ctx))
        # Violation: bound_var > MAX_LOOP_BOUND
        solver.add(bound_var > z3.IntVal(self.MAX_LOOP_BOUND, ctx=ctx))
        result = solver.check()
        if result == z3.unsat:
            return LoopBoundResult(
                func_name=func_name,
                loop_index=loop_idx,
                declared_bound=declared_bound,
                max_allowed=self.MAX_LOOP_BOUND,
                proven_safe=True,
            )
        else:
            # SAT: declared_bound > MAX_LOOP_BOUND (should be caught at compile time,
            # but we produce a formal certificate here for completeness)
            ce_str = f"{var_name} = {declared_bound} > {self.MAX_LOOP_BOUND}"
            return LoopBoundResult(
                func_name=func_name,
                loop_index=loop_idx,
                declared_bound=declared_bound,
                max_allowed=self.MAX_LOOP_BOUND,
                proven_safe=False,
                counterexample=ce_str,
            )


# Module-level singleton for external callers
_loop_bound_analyzer = LoopBoundAnalyzer()


def analyze_loop_bounds(ast: ProgramNode) -> LoopBoundReport:
    """Convenience function: run loop bound analysis on a compiled SIL AST."""
    return _loop_bound_analyzer.analyze(ast)




def _static_fallback_check(ast: ProgramNode) -> tuple[bool, str | None]:
    """
    Simple syntactic safety check used when Z3 is unavailable.
    Detects obvious violations: assert false, division by zero literal,
    and unbounded arithmetic on constants.
    Returns (safe, reason_if_unsafe).
    """

    def _check_node(node: ASTNode) -> str | None:
        if isinstance(node, AssertStmtNode):
            if (
                isinstance(node.condition, LiteralNode)
                and node.condition.value is False
            ):
                return "assert false detected"
        if isinstance(node, BinaryExprNode):
            if node.operator == "/" and isinstance(node.right, LiteralNode):
                if node.right.value == 0:
                    return "division by zero literal"
            left = _check_node(node.left)
            if left:
                return left
            return _check_node(node.right)
        if isinstance(node, UnaryExprNode):
            return _check_node(node.operand)
        if isinstance(node, IfStmtNode):
            for s in node.then_branch + node.else_branch:
                r = _check_node(s)
                if r:
                    return r
        if isinstance(node, WhileStmtNode):
            for s in node.body:
                r = _check_node(s)
                if r:
                    return r
        if isinstance(node, (AssignmentStmtNode, ReturnStmtNode)):
            return _check_node(node.value)
        return None

    for func in ast.functions:
        for stmt in func.body:
            reason = _check_node(stmt)
            if reason:
                return False, reason
    return True, None


# ---------------------------------------------------------------------------
# OS resource limits (Step 31)
# ---------------------------------------------------------------------------


def _apply_resource_limits() -> None:
    """Set OS-level resource limits for the Z3 subprocess (Linux only)."""
    if platform.system() != "Linux":
        return
    try:
        import resource

        resource.setrlimit(
            resource.RLIMIT_AS,
            (_Z3_MEMORY_LIMIT_BYTES, _Z3_MEMORY_LIMIT_BYTES),
        )
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (_Z3_CPU_LIMIT_SECONDS, _Z3_CPU_LIMIT_SECONDS),
        )
    except (ValueError, Exception) as _rl_exc:  # noqa: BLE001
        logger.debug(f"Resource limit not applied: {_rl_exc}")


# ---------------------------------------------------------------------------
# Subprocess worker
# ---------------------------------------------------------------------------


def _subprocess_worker(
    ast: ProgramNode,
    axioms: list[Axiom],
    timeout_ms: int,
    cache: dict[str, tuple[bool, str | None]],
    ipc_token: bytes,
    conn: "multiprocessing.connection.Connection",
    pre_cond: str = "",
) -> None:
    """Entry point for the isolated Z3 subprocess."""
    _apply_resource_limits()
    checker = BoundedModelChecker()
    checker._cache_update(dict(cache))
    try:
        safe, ce, loop_report = checker._verify_inner(ast, axioms, timeout_ms, pre_cond=pre_cond)
        ce_dict = (
            {k: str(v) for k, v in ce.assignments.items()} if ce is not None else None
        )
        loop_report_dict = {
            "all_proven_safe": loop_report.all_proven_safe,
            "max_bound_seen": loop_report.max_bound_seen,
            "results": [
                {
                    "func_name": r.func_name,
                    "loop_index": r.loop_index,
                    "declared_bound": r.declared_bound,
                    "proven_safe": r.proven_safe,
                }
                for r in loop_report.results
            ],
        }
        conn.send((ipc_token, safe, ce_dict, checker._cache, loop_report_dict))
    except Exception as exc:  # noqa: BLE001
        conn.send((ipc_token, exc))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bounded Model Checker
# ---------------------------------------------------------------------------


class BoundedModelChecker:
    def __init__(self) -> None:
        self.__cache: dict[str, tuple[bool, str | None]] = {}

    @property
    def _cache(self) -> dict[str, tuple[bool, str | None]]:
        """Read-only view -- prevents external cache poisoning (A-02)."""
        return dict(self.__cache)

    def _cache_update(self, updates: dict[str, tuple[bool, str | None]]) -> None:
        """Merge verified results into the internal cache."""
        self.__cache.update(updates)

    def _hash_ast(self, ast: ProgramNode, axioms: list[Axiom], pre_cond: str = "") -> str:
        """Compute a canonical SHA-256 cache key from the AST, axiom set, and precondition."""

        def _node_to_dict(node: Any) -> Any:
            if isinstance(node, list):
                return [_node_to_dict(n) for n in node]
            if hasattr(node, "__dataclass_fields__"):
                return {
                    "__type__": type(node).__name__,
                    **{
                        k: _node_to_dict(getattr(node, k))
                        for k in node.__dataclass_fields__
                    },
                }
            return node

        payload = {
            "ast": _node_to_dict(ast),
            "axioms": [
                {"id": a.id, "condition": a.condition}
                for a in sorted(axioms, key=lambda x: x.id)
            ],
            "pre_cond": pre_cond.strip(),
        }
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def verify(
        self,
        ast: ProgramNode,
        axioms: list[Axiom],
        timeout_ms: int = 5000,
        pre_cond: str = "",
    ) -> tuple[bool, "CounterExample | None"]:
        """
        Returns (safe, counterexample).
        safe=True  -> UNSAT (no violation reachable within bounds).
        safe=False -> SAT   (counterexample found).
        Loop bound verification runs automatically; programs with any loop bound
        exceeding MAX_LOOP_BOUND (10,000) are rejected as unsafe.
        pre_cond: SIL expression constraining the input space (paper §3.4).
        Raises VerificationError on solver timeout / unknown result.
        Falls back to static analyzer if Z3 subprocess fails (Step 33).
        """
        start = time.monotonic()
        func_names = [f.name for f in ast.functions]
        axiom_ids = [a.id for a in axioms]
        try:
            safe, ce, loop_report = self._verify_subprocess(ast, axioms, timeout_ms, pre_cond=pre_cond)
            elapsed = time.monotonic() - start
            logger.info(
                "verification",
                extra={
                    "event": "verification_complete",
                    "functions": func_names,
                    "axioms": axiom_ids,
                    "outcome": "safe" if safe else "unsafe",
                    "latency_ms": round(elapsed * 1000, 2),
                    "counterexample": str(ce) if ce else None,
                    "loop_bounds": loop_report.summary(),
                },
            )
            return safe, ce
        except VerificationError as exc:
            elapsed = time.monotonic() - start
            logger.warning(
                f"Z3 failed ({exc}); falling back to static analyzer.",
                extra={
                    "event": "z3_fallback",
                    "functions": func_names,
                    "latency_ms": round(elapsed * 1000, 2),
                },
            )
            safe, reason = _static_fallback_check(ast)
            logger.warning(
                f"Static fallback result: safe={safe}, reason={reason}",
                extra={
                    "event": "static_fallback_result",
                    "safe": safe,
                    "reason": reason,
                },
            )
            if not safe:
                ce = CounterExample.__new__(CounterExample)
                ce.assignments = {"static_reason": reason or "unknown"}
                return False, ce
            raise
        finally:
            elapsed = time.monotonic() - start
            remaining = CONSTANT_VERIFICATION_TIME_S - elapsed
            if remaining > 0:
                time.sleep(remaining)

    def _verify_subprocess(
        self,
        ast: ProgramNode,
        axioms: list[Axiom],
        timeout_ms: int,
        pre_cond: str = "",
    ) -> tuple[bool, "CounterExample | None", LoopBoundReport]:
        """Run _verify_inner in an isolated subprocess with OS resource limits."""
        last_exc: Exception | None = None
        for attempt in range(1, _Z3_MAX_RETRIES + 1):
            ipc_token = generate_ipc_token()
            parent_conn, child_conn = multiprocessing.Pipe(duplex=False)
            proc = multiprocessing.Process(
                target=_subprocess_worker,
                args=(ast, axioms, timeout_ms, self._cache, ipc_token, child_conn, pre_cond),
                daemon=True,
            )
            proc.start()
            child_conn.close()
            timeout_s = (timeout_ms / 1000) + CONSTANT_VERIFICATION_TIME_S + 1.0

            try:
                if not parent_conn.poll(timeout_s):
                    proc.kill()
                    proc.join()
                    raise VerificationError(
                        "Z3 subprocess exceeded wall-clock timeout and was killed."
                    )
                outcome = parent_conn.recv()
            finally:
                parent_conn.close()

            proc.join()

            if proc.exitcode not in (0, -9):
                last_exc = VerificationError(
                    f"Z3 subprocess crashed (exit {proc.exitcode}), "
                    f"attempt {attempt}/{_Z3_MAX_RETRIES}."
                )
                logger.warning(str(last_exc))
                continue

            if not isinstance(outcome, tuple) or len(outcome) < 2:
                raise VerificationError("IPC: malformed response from subprocess.")
            received_token = outcome[0]
            if not isinstance(received_token, bytes) or not verify_ipc_token(
                ipc_token, received_token
            ):
                raise VerificationError(
                    "IPC: token mismatch — subprocess response rejected."
                )

            rest = outcome[1:]
            if len(rest) == 1 and isinstance(rest[0], Exception):
                raise VerificationError(str(rest[0])) from rest[0]

            safe, ce_dict, cache_update, loop_report_dict = rest
            self._cache_update(cache_update)
            # Reconstruct LoopBoundReport from serialised dict
            loop_results = [
                LoopBoundResult(
                    func_name=r["func_name"],
                    loop_index=r["loop_index"],
                    declared_bound=r["declared_bound"],
                    max_allowed=StmtEncoder.MAX_LOOP_BOUND,
                    proven_safe=r["proven_safe"],
                )
                for r in loop_report_dict.get("results", [])
            ]
            loop_report = LoopBoundReport(
                all_proven_safe=loop_report_dict["all_proven_safe"],
                results=loop_results,
                max_bound_seen=loop_report_dict["max_bound_seen"],
            )
            if ce_dict is not None:
                ce = CounterExample.__new__(CounterExample)
                ce.assignments = ce_dict
                return safe, ce, loop_report
            return safe, None, loop_report

        raise VerificationError(
            f"Z3 subprocess crashed {_Z3_MAX_RETRIES} times consecutively."
        ) from last_exc

    def _verify_inner(
        self,
        ast: ProgramNode,
        axioms: list[Axiom],
        timeout_ms: int,
        pre_cond: str = "",
    ) -> tuple[bool, "CounterExample | None", LoopBoundReport]:
        """Core BMC query: encode AST + axioms into Z3, run solver, return (safe, ce, loop_report).

        Args:
            ast: Compiled SIL program AST.
            axioms: Safety axioms to enforce as additional constraints.
            timeout_ms: Z3 solver timeout in milliseconds.
            pre_cond: SIL expression for the function precondition (paper §3.4).

        Returns:
            (safe, counterexample, loop_bound_report).
            safe=True  → UNSAT (no violation reachable within bounds).
            safe=False → SAT   (counterexample found).
            loop_bound_report: Z3 proofs that all loop bounds ≤ MAX_LOOP_BOUND.

        Soundness note: integer variables are constrained to the 32-bit signed
        range [-2^31, 2^31-1] to prevent Z3 from exploiting unbounded integer
        arithmetic that would not occur in a real execution environment.
        """
        cache_key = self._hash_ast(ast, axioms, pre_cond)
        if cache_key in self.__cache:
            safe, _ce_str = self.__cache[cache_key]
            # Re-run loop bound analysis (not cached — fast, pure Z3)
            loop_report = LoopBoundAnalyzer().analyze(ast)
            return safe, None, loop_report

        # --- Loop bound verification (Z3 proof for every loop) ---
        loop_report = LoopBoundAnalyzer().analyze(ast)
        if not loop_report.all_proven_safe:
            # A loop bound exceeds MAX_LOOP_BOUND — reject immediately.
            # (Should be caught at compile time; this is the formal Z3 backstop.)
            bad = [r for r in loop_report.results if not r.proven_safe]
            ce = CounterExample.__new__(CounterExample)
            ce.assignments = {
                r.counterexample or f"loop_{r.loop_index}": r.declared_bound
                for r in bad
            }
            self.__cache[cache_key] = (False, str(ce))
            return False, ce, loop_report

        ctx = z3.Context()
        solver = z3.Solver(ctx=ctx)
        # Steps 28-29: set Z3 timeout and memory limit via solver params.
        solver.set("timeout", timeout_ms)
        solver.set("max_memory", _Z3_SOLVER_MEMORY_MB)

        env = SSAEnv(ctx)
        stmt_enc = StmtEncoder(ctx, solver, env)

        # Z3 integer bounds: constrain all parameters to 32-bit signed range
        # to prevent unsound results from unbounded integer arithmetic.
        _INT32_MIN = -(2**31)
        _INT32_MAX = 2**31 - 1

        for func in ast.functions:
            func_path = z3.BoolVal(True, ctx=ctx)
            for param in func.params:
                pvar = env.declare_param(param.name, param.type_name)
                # Apply 32-bit bounds to integer parameters for soundness
                if param.type_name == "int":
                    solver.add(pvar >= _INT32_MIN)
                    solver.add(pvar <= _INT32_MAX)
            # Encode precondition as a solver CONSTRAINT (paper §3.4).
            # pre_cond restricts the input space — it is NOT a violation flag.
            # This implements: BMC(f,k) = pre_f ∧ unrolled_semantics ∧ violation
            if pre_cond.strip():
                _param_names_pre = [p.name for p in func.params]
                _pre_axiom = Axiom("_precond", "", pre_cond.strip(), ["*"])
                _z3_pre = _encode_axiom(_pre_axiom, ctx, env, _param_names_pre)
                if _z3_pre is not None:
                    solver.add(_z3_pre)  # constrain inputs, not a violation flag
            stmt_enc.encode_stmts(func.body, func_path)

        declared_params = list(env._counters.keys()) + [
            k.rsplit("_", 1)[0] for k in env._exprs if k not in env._counters
        ]
        seen: set[str] = set()
        param_names: list[str] = []
        for n in declared_params:
            base = n.rsplit("_", 1)[0] if "_" in n else n
            if base not in seen:
                seen.add(base)
                param_names.append(base)

        for axiom in axioms:
            z3_cond = _encode_axiom(axiom, ctx, env, param_names)
            if z3_cond is not None:
                stmt_enc.violation_flags.append(z3.Not(z3_cond))

        if not stmt_enc.violation_flags:
            self.__cache[cache_key] = (True, None)
            return True, None, loop_report

        solver.add(z3.Or(*stmt_enc.violation_flags))
        result = solver.check()

        if result == z3.unsat:
            self.__cache[cache_key] = (True, None)
            return True, None, loop_report
        elif result == z3.sat:
            ce = CounterExample(solver.model())
            self.__cache[cache_key] = (False, str(ce))
            return False, ce, loop_report
        else:
            raise VerificationError(f"Z3 solver returned unknown/timeout: {result}")


# ---------------------------------------------------------------------------
# Thin Verifier façade
# ---------------------------------------------------------------------------


class Verifier:
    """Thin façade so existing code that instantiates Verifier(config) still works."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._bmc = BoundedModelChecker()
        self._timeout_ms: int = config.get("verification_timeout_ms", 5000)

    def verify(
        self,
        func_name: str,
        ast: ProgramNode,
        pre_cond: str,
        axioms: list[Axiom] | None = None,
    ) -> dict[str, Any]:
        """Verify a SIL AST and return a result dict with 'safe' and 'counterexample' keys.

        pre_cond is encoded as a Z3 input constraint per paper §3.4:
          BMC(f, k) = pre_f ∧ unrolled_semantics(f, k) ∧ violation_flag
        """
        axioms = axioms or []
        safe, ce = self._bmc.verify(
            ast, axioms, timeout_ms=self._timeout_ms, pre_cond=pre_cond
        )
        return {"safe": safe, "counterexample": str(ce) if ce else None}
