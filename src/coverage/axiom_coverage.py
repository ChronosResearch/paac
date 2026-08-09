"""
src/coverage/axiom_coverage.py
-------------------------------
Axiom Coverage Metric.

An axiom is "covered" by a SIL program if the axiom's condition is
*applicable* to that program (shares at least one variable with the
program's parameter/variable set) AND the verifier actually evaluates
it (i.e., it is not skipped as inapplicable).

Coverage levels:
  - APPLICABLE : axiom variables appear in the program
  - ACTIVE     : axiom was encoded into the Z3 query (not skipped)
  - VIOLATED   : axiom was the reason for a SAT result (tight coverage)

Coverage score = |ACTIVE axioms| / |total axioms| across all programs.

The module instruments _verify_inner via a thin wrapper that records
which axioms were encoded for each (program, axiom) pair.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import z3
from loguru import logger

from src.axioms.axiom_parser import Axiom
from src.core.sil_compiler import ProgramNode, SILCompiler
from src.core.verifier import (
    BoundedModelChecker,
    SSAEnv,
    StmtEncoder,
    VerificationError,
    _encode_axiom,
)
_COMPILER = SILCompiler()

# ---------------------------------------------------------------------------
# Coverage levels
# ---------------------------------------------------------------------------

LEVEL_NONE = "none"  # axiom not applicable to this program
LEVEL_APPLICABLE = "applicable"  # axiom variables present but not encoded
LEVEL_ACTIVE = "active"  # axiom was encoded into Z3 query
LEVEL_VIOLATED = "violated"  # axiom was the binding constraint in a SAT result


@dataclass
class AxiomCoverageRecord:
    """Coverage record for one (axiom, program) pair."""

    axiom_id: str
    program_description: str
    level: str  # LEVEL_* constant
    variables_matched: list[str] = field(default_factory=list)


@dataclass
class AxiomCoverageResult:
    """Aggregated coverage result for one axiom across all programs."""

    axiom_id: str
    condition: str
    total_programs: int
    applicable_count: int  # programs where axiom variables appear
    active_count: int  # programs where axiom was encoded
    violated_count: int  # programs where axiom caused rejection
    records: list[AxiomCoverageRecord] = field(default_factory=list)

    @property
    def applicable_pct(self) -> float:
        """Fraction of programs where axiom is applicable."""
        return (
            self.applicable_count / self.total_programs if self.total_programs else 0.0
        )

    @property
    def active_pct(self) -> float:
        """Fraction of programs where axiom was actively evaluated."""
        return self.active_count / self.total_programs if self.total_programs else 0.0

    @property
    def coverage_score(self) -> float:
        """Primary coverage metric: active / total."""
        return self.active_pct


@dataclass
class SuiteCoverageResult:
    """Suite-level coverage across all axioms and programs."""

    axiom_results: list[AxiomCoverageResult]
    total_programs: int
    elapsed_ms: float = 0.0

    @property
    def overall_coverage(self) -> float:
        """Mean active coverage across all axioms."""
        if not self.axiom_results:
            return 0.0
        return sum(r.coverage_score for r in self.axiom_results) / len(
            self.axiom_results
        )

    @property
    def uncovered_axioms(self) -> list[str]:
        """Axioms with zero active coverage."""
        return [r.axiom_id for r in self.axiom_results if r.active_count == 0]


# ---------------------------------------------------------------------------
# Variable extraction helpers
# ---------------------------------------------------------------------------

_KEYWORDS = {
    "and",
    "or",
    "not",
    "true",
    "false",
    "if",
    "else",
    "while",
    "return",
    "assert",
    "func",
    "bound",
    "int",
    "bool",
    "string",
    "array",
}


def _extract_vars_from_condition(condition: str) -> set[str]:
    """Extract variable names from an axiom condition string."""
    tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", condition)
    return {t for t in tokens if t not in _KEYWORDS}


def _extract_vars_from_ast(ast: ProgramNode) -> set[str]:
    """Extract all variable/parameter names from a compiled SIL AST."""
    from src.core.sil_compiler import (
        AssignmentStmtNode,
        IdentifierNode,
        FuncDefNode,
        IfStmtNode,
        WhileStmtNode,
        ReturnStmtNode,
        AssertStmtNode,
        BinaryExprNode,
        UnaryExprNode,
        CallExprNode,
        ArrayAccessNode,
    )

    names: set[str] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, FuncDefNode):
            for p in node.params:
                names.add(p.name)
            for s in node.body:
                _walk(s)
        elif isinstance(node, AssignmentStmtNode):
            names.add(node.target)
            _walk(node.value)
        elif isinstance(node, IdentifierNode):
            names.add(node.name)
        elif isinstance(node, (IfStmtNode,)):
            _walk(node.condition)
            for s in node.then_branch + node.else_branch:
                _walk(s)
        elif isinstance(node, WhileStmtNode):
            _walk(node.condition)
            for s in node.body:
                _walk(s)
        elif isinstance(node, (ReturnStmtNode, AssertStmtNode)):
            _walk(node.value if hasattr(node, "value") else node.condition)
        elif isinstance(node, BinaryExprNode):
            _walk(node.left)
            _walk(node.right)
        elif isinstance(node, UnaryExprNode):
            _walk(node.operand)
        elif isinstance(node, CallExprNode):
            for a in node.args:
                _walk(a)
        elif isinstance(node, ArrayAccessNode):
            _walk(node.index)

    for func in ast.functions:
        _walk(func)
    return names


# ---------------------------------------------------------------------------
# Instrumented verifier
# ---------------------------------------------------------------------------


class InstrumentedBMC(BoundedModelChecker):
    """
    BoundedModelChecker subclass that records which axioms were encoded
    during _verify_inner, enabling coverage measurement.
    """

    def __init__(self) -> None:
        super().__init__()
        self._encoded_axiom_ids: list[str] = []
        self._violated_axiom_ids: list[str] = []

    def _verify_inner_instrumented(
        self,
        ast: ProgramNode,
        axioms: list[Axiom],
        timeout_ms: int = 5000,
    ) -> tuple[bool, Any, list[str], list[str]]:
        """
        Run _verify_inner and return (safe, ce, encoded_ids, violated_ids).

        encoded_ids: axiom IDs that were successfully encoded into Z3.
        violated_ids: axiom IDs that contributed to a SAT result.
        """
        encoded_ids: list[str] = []
        violated_ids: list[str] = []

        ctx = z3.Context()
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", timeout_ms)
        solver.set("max_memory", 1024)

        env = SSAEnv(ctx)
        stmt_enc = StmtEncoder(ctx, solver, env)

        for func in ast.functions:
            func_path = z3.BoolVal(True, ctx=ctx)
            for param in func.params:
                env.declare_param(param.name, param.type_name)
            stmt_enc.encode_stmts(func.body, func_path)

        # Collect param names
        declared = list(env._counters.keys()) + [
            k.rsplit("_", 1)[0] for k in env._exprs if k not in env._counters
        ]
        seen: set[str] = set()
        param_names: list[str] = []
        for n in declared:
            base = n.rsplit("_", 1)[0] if "_" in n else n
            if base not in seen:
                seen.add(base)
                param_names.append(base)

        # Encode axioms and track which ones succeed
        axiom_z3_map: dict[str, z3.BoolRef] = {}
        for axiom in axioms:
            z3_cond = _encode_axiom(axiom, ctx, env, param_names)
            if z3_cond is not None:
                encoded_ids.append(axiom.id)
                axiom_z3_map[axiom.id] = z3_cond
                stmt_enc.violation_flags.append(z3.Not(z3_cond))

        if not stmt_enc.violation_flags:
            return True, None, encoded_ids, violated_ids

        solver.add(z3.Or(*stmt_enc.violation_flags))
        result = solver.check()

        if result == z3.unsat:
            return True, None, encoded_ids, violated_ids
        elif result == z3.sat:
            from src.core.verifier import CounterExample

            ce = CounterExample(solver.model())
            # Identify which axioms are violated in the model
            model = solver.model()
            for ax_id, z3_cond in axiom_z3_map.items():
                try:
                    val = model.eval(z3_cond, model_completion=True)
                    if z3.is_false(val):
                        violated_ids.append(ax_id)
                except Exception:  # noqa: BLE001
                    pass
            return False, ce, encoded_ids, violated_ids
        else:
            raise VerificationError(f"Z3 returned unknown: {result}")


# ---------------------------------------------------------------------------
# Coverage analyser
# ---------------------------------------------------------------------------


@dataclass
class ProgramEntry:
    """A SIL program to include in coverage analysis."""

    sil_code: str
    description: str
    axioms: list[Axiom] = field(default_factory=list)


def analyse_coverage(
    programs: list[ProgramEntry],
    axioms: list[Axiom],
    timeout_ms: int = 5000,
) -> SuiteCoverageResult:
    """
    Run coverage analysis for a set of axioms over a set of SIL programs.

    For each (program, axiom) pair, determine the coverage level:
      - ACTIVE   if the axiom was encoded into the Z3 query
      - APPLICABLE if axiom variables appear in the program but axiom was skipped
      - NONE     otherwise

    Returns a SuiteCoverageResult with per-axiom and suite-level metrics.
    """
    t_start = time.monotonic()
    bmc = InstrumentedBMC()

    # Per-axiom accumulators
    per_axiom: dict[str, AxiomCoverageResult] = {
        ax.id: AxiomCoverageResult(
            axiom_id=ax.id,
            condition=ax.condition,
            total_programs=len(programs),
            applicable_count=0,
            active_count=0,
            violated_count=0,
        )
        for ax in axioms
    }

    for entry in programs:
        try:
            ast, _ = _COMPILER.compile(entry.sil_code)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Coverage: skipping program '{entry.description}': {exc}")
            continue

        prog_vars = _extract_vars_from_ast(ast)

        try:
            _safe, _ce, encoded_ids, violated_ids = bmc._verify_inner_instrumented(
                ast, axioms, timeout_ms
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"Coverage: verification error for '{entry.description}': {exc}"
            )
            encoded_ids, violated_ids = [], []

        for ax in axioms:
            ax_vars = _extract_vars_from_condition(ax.condition)
            matched = list(ax_vars & prog_vars)

            if ax.id in violated_ids:
                level = LEVEL_VIOLATED
                per_axiom[ax.id].violated_count += 1
                per_axiom[ax.id].active_count += 1
                per_axiom[ax.id].applicable_count += 1
            elif ax.id in encoded_ids:
                level = LEVEL_ACTIVE
                per_axiom[ax.id].active_count += 1
                per_axiom[ax.id].applicable_count += 1
            elif matched:
                level = LEVEL_APPLICABLE
                per_axiom[ax.id].applicable_count += 1
            else:
                level = LEVEL_NONE

            per_axiom[ax.id].records.append(
                AxiomCoverageRecord(
                    axiom_id=ax.id,
                    program_description=entry.description,
                    level=level,
                    variables_matched=matched,
                )
            )

    elapsed = (time.monotonic() - t_start) * 1000
    return SuiteCoverageResult(
        axiom_results=list(per_axiom.values()),
        total_programs=len(programs),
        elapsed_ms=elapsed,
    )


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------


def coverage_to_json(result: SuiteCoverageResult) -> dict:
    """Serialise a SuiteCoverageResult to a JSON-compatible dict."""
    return {
        "overall_coverage": round(result.overall_coverage, 4),
        "total_programs": result.total_programs,
        "uncovered_axioms": result.uncovered_axioms,
        "elapsed_ms": round(result.elapsed_ms, 1),
        "per_axiom": [
            {
                "axiom_id": r.axiom_id,
                "condition": r.condition,
                "total_programs": r.total_programs,
                "applicable_count": r.applicable_count,
                "active_count": r.active_count,
                "violated_count": r.violated_count,
                "coverage_score": round(r.coverage_score, 4),
                "applicable_pct": round(r.applicable_pct, 4),
            }
            for r in result.axiom_results
        ],
    }
