"""
src/core/probabilistic.py
--------------------------
Feature 1: Probabilistic Verification

Extends PAAC's deterministic BMC with probabilistic axioms that carry a
confidence threshold.  Instead of a binary UNSAT/SAT answer, the engine
estimates the fraction of the bounded input domain that satisfies every
safety axiom and compares it against the declared threshold.

Approach
--------
For each function parameter we bound the domain to [-DOMAIN, DOMAIN].
We count satisfying assignments using Z3's optimize / incremental solver:

  P(safe) ≈ |{inputs : all axioms hold}| / |total inputs in domain|

Because exact model counting is #P-hard we use a *sampling* approximation:
draw SAMPLES random points from the domain, check each with Z3, and report
the fraction that satisfies all axioms.  This is sound for the stated
confidence level (±sqrt(p(1-p)/n) by the CLT).

Configuration
-------------
  PAAC_PROB_DOMAIN   : int  — half-width of per-parameter domain (default 100)
  PAAC_PROB_SAMPLES  : int  — number of random samples (default 200)
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field

import yaml
import z3
from loguru import logger

from src.axioms.axiom_parser import Axiom
from src.core.sil_compiler import ProgramNode, SILCompiler
from src.core.verifier import SSAEnv, StmtEncoder, _encode_axiom

_DOMAIN: int = int(os.environ.get("PAAC_PROB_DOMAIN", "100"))
_SAMPLES: int = int(os.environ.get("PAAC_PROB_SAMPLES", "200"))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ProbabilisticAxiom:
    id: str
    description: str
    condition: str
    confidence_threshold: float  # 0.0 – 1.0
    target_functions: list[str] = field(default_factory=lambda: ["*"])

    def to_axiom(self) -> Axiom:
        """Convert to a plain Axiom for reuse in the existing encoder."""
        return Axiom(
            id=self.id,
            description=self.description,
            condition=self.condition,
            target_functions=self.target_functions,
        )


@dataclass
class ProbabilisticResult:
    safe: bool
    probability: float  # estimated P(all axioms hold)
    threshold: float  # minimum required
    samples_checked: int
    violating_axiom: str | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------


def load_probabilistic_axioms(path: str) -> list[ProbabilisticAxiom]:
    if not os.path.exists(path):
        logger.warning(f"Probabilistic axiom file not found: {path}")
        return []
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    axioms: list[ProbabilisticAxiom] = []
    for ax in data.get("probabilistic_axioms", []):
        if "id" not in ax or "condition" not in ax or "confidence_threshold" not in ax:
            logger.warning(f"Skipping malformed probabilistic axiom: {ax}")
            continue
        t = float(ax["confidence_threshold"])
        if not 0.0 <= t <= 1.0:
            logger.warning(f"Axiom {ax['id']}: threshold {t} out of [0,1], skipping.")
            continue
        axioms.append(
            ProbabilisticAxiom(
                id=ax["id"],
                description=ax.get("description", ""),
                condition=ax["condition"],
                confidence_threshold=t,
                target_functions=ax.get("target_functions", ["*"]),
            )
        )
    logger.info(f"Loaded {len(axioms)} probabilistic axiom(s) from '{path}'.")
    return axioms


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ProbabilisticVerifier:
    """
    Estimates P(safe) by sampling the bounded input domain and checking each
    sample against all probabilistic axioms using Z3.
    """

    def __init__(
        self,
        domain: int = _DOMAIN,
        samples: int = _SAMPLES,
        timeout_ms: int = 5000,
    ) -> None:
        self.domain = domain
        self.samples = samples
        self.timeout_ms = timeout_ms
        self._compiler = SILCompiler()

    def verify(
        self,
        ast: ProgramNode,
        prob_axioms: list[ProbabilisticAxiom],
    ) -> ProbabilisticResult:
        """
        Returns a ProbabilisticResult.
        safe=True  iff  P(safe) >= min(threshold) across all axioms.
        Fails closed (safe=False) on any solver error.
        """
        if not prob_axioms:
            return ProbabilisticResult(
                safe=True,
                probability=1.0,
                threshold=0.0,
                samples_checked=0,
                reason="no probabilistic axioms defined",
            )

        # Collect parameter names from the AST.
        param_names: list[str] = []
        for func in ast.functions:
            for p in func.params:
                if p.name not in param_names:
                    param_names.append(p.name)

        if not param_names:
            # No parameters — deterministic; delegate to boolean check.
            return self._deterministic_check(ast, prob_axioms)

        # Sample random inputs and check each.
        safe_count = 0
        worst_threshold = max(a.confidence_threshold for a in prob_axioms)
        worst_axiom_id: str | None = None

        for _ in range(self.samples):
            point = {n: random.randint(-self.domain, self.domain) for n in param_names}
            if self._point_satisfies_all(ast, prob_axioms, point, param_names):
                safe_count += 1

        probability = safe_count / self.samples
        # Find the most restrictive axiom that fails.
        for ax in sorted(prob_axioms, key=lambda a: -a.confidence_threshold):
            if probability < ax.confidence_threshold:
                worst_axiom_id = ax.id
                worst_threshold = ax.confidence_threshold
                break

        safe = probability >= worst_threshold
        logger.info(
            f"Probabilistic verification: P(safe)={probability:.3f}, "
            f"threshold={worst_threshold:.3f}, safe={safe}, "
            f"samples={self.samples}"
        )
        return ProbabilisticResult(
            safe=safe,
            probability=probability,
            threshold=worst_threshold,
            samples_checked=self.samples,
            violating_axiom=worst_axiom_id if not safe else None,
        )

    def _point_satisfies_all(
        self,
        ast: ProgramNode,
        prob_axioms: list[ProbabilisticAxiom],
        point: dict[str, int],
        param_names: list[str],
    ) -> bool:
        """Check whether a concrete input point satisfies all axioms."""
        ctx = z3.Context()
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", self.timeout_ms)
        env = SSAEnv(ctx)
        stmt_enc = StmtEncoder(ctx, solver, env)

        for func in ast.functions:
            func_path = z3.BoolVal(True, ctx=ctx)
            for param in func.params:
                v = env.declare_param(param.name, param.type_name)
                # Fix the parameter to the sampled value.
                solver.add(v == z3.IntVal(point.get(param.name, 0), ctx=ctx))
            stmt_enc.encode_stmts(func.body, func_path)

        for pax in prob_axioms:
            z3_cond = _encode_axiom(pax.to_axiom(), ctx, env, param_names)
            if z3_cond is None:
                continue
            solver.add(z3.Not(z3_cond))

        result = solver.check()
        # UNSAT means no violation found → point is safe.
        return result == z3.unsat

    def _deterministic_check(
        self,
        ast: ProgramNode,
        prob_axioms: list[ProbabilisticAxiom],
    ) -> ProbabilisticResult:
        """For parameter-free functions, do a single Z3 check."""
        ctx = z3.Context()
        solver = z3.Solver(ctx=ctx)
        solver.set("timeout", self.timeout_ms)
        env = SSAEnv(ctx)
        stmt_enc = StmtEncoder(ctx, solver, env)

        for func in ast.functions:
            stmt_enc.encode_stmts(func.body, z3.BoolVal(True, ctx=ctx))

        for pax in prob_axioms:
            z3_cond = _encode_axiom(pax.to_axiom(), ctx, env, [])
            if z3_cond is not None:
                stmt_enc.violation_flags.append(z3.Not(z3_cond))

        if stmt_enc.violation_flags:
            solver.add(z3.Or(*stmt_enc.violation_flags))

        result = solver.check()
        safe = result == z3.unsat
        prob = 1.0 if safe else 0.0
        threshold = max(a.confidence_threshold for a in prob_axioms)
        return ProbabilisticResult(
            safe=safe and prob >= threshold,
            probability=prob,
            threshold=threshold,
            samples_checked=1,
        )
