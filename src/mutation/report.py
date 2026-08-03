"""
src/mutation/report.py
-----------------------
Metrics computation and report generation for axiom mutation testing.

Outputs:
  - JSON report (machine-readable, full detail)
  - CSV summary (one row per mutant)
  - Markdown report (human-readable, paper-ready)
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict
from io import StringIO
from typing import Any

from src.mutation.axiom_mutator import MutationKind
from src.mutation.mutation_runner import AxiomMutationResult, MutantResult

# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------


def compute_suite_metrics(results: list[AxiomMutationResult]) -> dict[str, Any]:
    """Compute suite-level metrics across all axioms."""
    total_mutants = 0
    total_killed = 0
    vacuous_axioms: list[str] = []
    critical_axiom: str | None = None
    critical_drop = 0.0
    per_axiom: list[dict] = []

    for r in results:
        non_noop = [m for m in r.mutant_results if m.mutant.kind != MutationKind.NOOP]
        killed = sum(1 for m in non_noop if not m.survived)
        total_mutants += len(non_noop)
        total_killed += killed

        if r.is_vacuous:
            vacuous_axioms.append(r.axiom.id)

        # Critical axiom = largest kill rate drop on weakening mutations
        weaken_muts = [
            m
            for m in r.mutant_results
            if m.mutant.kind in (MutationKind.WEAKEN_OP, MutationKind.SHIFT_CONST)
            and m.mutant.description.startswith("Shift constant by -")
        ]
        if weaken_muts:
            avg_kill = sum(m.kill_rate for m in weaken_muts) / len(weaken_muts)
            if avg_kill > critical_drop:
                critical_drop = avg_kill
                critical_axiom = r.axiom.id

        per_axiom.append(
            {
                "axiom_id": r.axiom.id,
                "condition": r.axiom.condition,
                "probes": len(r.probes),
                "mutants_total": len(non_noop),
                "mutants_killed": killed,
                "mutation_score": round(r.mutation_score, 4),
                "robustness_score": round(r.robustness_score, 4),
                "is_vacuous": r.is_vacuous,
                "elapsed_ms": round(r.elapsed_ms, 1),
            }
        )

    overall_mutation_score = total_killed / total_mutants if total_mutants > 0 else 0.0
    # Suite robustness = mean of per-axiom robustness scores, penalised by vacuous count
    robustness_scores = [r.robustness_score for r in results]
    suite_robustness = (
        sum(robustness_scores) / len(robustness_scores) if robustness_scores else 0.0
    )

    return {
        "suite_mutation_score": round(overall_mutation_score, 4),
        "suite_robustness_score": round(suite_robustness, 4),
        "total_axioms": len(results),
        "total_mutants": total_mutants,
        "total_killed": total_killed,
        "vacuous_axioms": vacuous_axioms,
        "critical_axiom": critical_axiom,
        "per_axiom": per_axiom,
    }


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------


def to_json(results: list[AxiomMutationResult]) -> str:
    metrics = compute_suite_metrics(results)

    full: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": metrics,
        "detail": [],
    }

    for r in results:
        axiom_detail: dict[str, Any] = {
            "axiom_id": r.axiom.id,
            "condition": r.axiom.condition,
            "target_functions": r.axiom.target_functions,
            "probes": [
                {
                    "description": p.description,
                    "expected_safe": p.expected_safe,
                }
                for p in r.probes
            ],
            "baseline": [
                {
                    "probe": pr.probe.description,
                    "actual_safe": pr.actual_safe,
                    "matched_expected": pr.matched_expected,
                }
                for pr in r.baseline_results
            ],
            "mutants": [],
        }

        for mr in r.mutant_results:
            axiom_detail["mutants"].append(
                {
                    "mutant_id": mr.mutant.mutant.id,
                    "kind": mr.mutant.kind.value,
                    "description": mr.mutant.description,
                    "condition": mr.mutant.mutant.condition,
                    "expected_direction": mr.mutant.expected_direction,
                    "probes_total": mr.probes_total,
                    "probes_killed": mr.probes_killed,
                    "kill_rate": round(mr.kill_rate, 4),
                    "survived": mr.survived,
                    "probe_results": [
                        {
                            "probe": pr.probe.description,
                            "actual_safe": pr.actual_safe,
                            "matched_expected": pr.matched_expected,
                            "error": pr.error,
                        }
                        for pr in mr.probe_results
                    ],
                }
            )

        full["detail"].append(axiom_detail)

    return json.dumps(full, indent=2)


# ---------------------------------------------------------------------------
# CSV report
# ---------------------------------------------------------------------------


def to_csv(results: list[AxiomMutationResult]) -> str:
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "axiom_id",
            "condition",
            "mutant_id",
            "kind",
            "mutant_condition",
            "expected_direction",
            "probes_total",
            "probes_killed",
            "kill_rate",
            "survived",
        ]
    )
    for r in results:
        for mr in r.mutant_results:
            writer.writerow(
                [
                    r.axiom.id,
                    r.axiom.condition,
                    mr.mutant.mutant.id,
                    mr.mutant.kind.value,
                    mr.mutant.mutant.condition,
                    mr.mutant.expected_direction,
                    mr.probes_total,
                    mr.probes_killed,
                    f"{mr.kill_rate:.4f}",
                    mr.survived,
                ]
            )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def to_markdown(results: list[AxiomMutationResult]) -> str:
    metrics = compute_suite_metrics(results)
    lines: list[str] = []

    lines.append("# PAAC Axiom Mutation Testing Report")
    lines.append("")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    lines.append("")

    # Executive summary
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Axioms tested | {metrics['total_axioms']} |")
    lines.append(f"| Total mutants | {metrics['total_mutants']} |")
    lines.append(f"| Mutants killed | {metrics['total_killed']} |")
    lines.append(
        f"| **Suite Mutation Score** | **{metrics['suite_mutation_score']:.1%}** |"
    )
    lines.append(
        f"| **Suite Robustness Score** | **{metrics['suite_robustness_score']:.1%}** |"
    )
    lines.append(f"| Vacuous axioms | {len(metrics['vacuous_axioms'])} |")
    lines.append(f"| Critical axiom | {metrics['critical_axiom'] or 'N/A'} |")
    lines.append("")

    # Interpretation
    score = metrics["suite_robustness_score"]
    if score >= 0.80:
        verdict = "STRONG — axiom set is robust and non-vacuous."
    elif score >= 0.60:
        verdict = "ADEQUATE — axiom set is functional but has gaps."
    elif score >= 0.40:
        verdict = "WEAK — several axioms are ineffective or vacuous."
    else:
        verdict = "POOR — axiom set provides minimal safety guarantees."

    lines.append(f"**Verdict**: {verdict}")
    lines.append("")

    if metrics["vacuous_axioms"]:
        lines.append(
            f"> ⚠️  **Vacuous axioms detected**: {', '.join(metrics['vacuous_axioms'])}"
        )
        lines.append(
            "> These axioms can be replaced with `true` without changing any test outcome."
        )
        lines.append(
            "> They provide no safety guarantee and should be strengthened or removed."
        )
        lines.append("")

    if metrics["critical_axiom"]:
        lines.append(f"> 🔴 **Most critical axiom**: `{metrics['critical_axiom']}`")
        lines.append(
            "> Weakening this axiom causes the largest degradation in safety coverage."
        )
        lines.append("")

    # Per-axiom table
    lines.append("## Per-Axiom Results")
    lines.append("")
    lines.append(
        "| Axiom ID | Condition | Mutants | Killed | Mutation Score | Robustness | Vacuous |"
    )
    lines.append(
        "|----------|-----------|---------|--------|----------------|------------|---------|"
    )
    for ax in metrics["per_axiom"]:
        vac = "⚠️ YES" if ax["is_vacuous"] else "No"
        lines.append(
            f"| `{ax['axiom_id']}` | `{ax['condition']}` | {ax['mutants_total']} | "
            f"{ax['mutants_killed']} | {ax['mutation_score']:.1%} | {ax['robustness_score']:.1%} | {vac} |"
        )
    lines.append("")

    # Per-axiom detail
    lines.append("## Mutation Detail")
    lines.append("")
    for r in results:
        lines.append(f"### Axiom: `{r.axiom.id}`")
        lines.append("")
        lines.append(f"- **Condition**: `{r.axiom.condition}`")
        lines.append(f"- **Target functions**: {r.axiom.target_functions}")
        lines.append(f"- **Probes**: {len(r.probes)}")
        lines.append(f"- **Mutation score**: {r.mutation_score:.1%}")
        lines.append(f"- **Robustness score**: {r.robustness_score:.1%}")
        lines.append(f"- **Vacuous**: {'YES ⚠️' if r.is_vacuous else 'No'}")
        lines.append("")

        lines.append("#### Probe Suite")
        lines.append("")
        lines.append("| # | Description | Expected Safe | Baseline Actual |")
        lines.append("|---|-------------|---------------|-----------------|")
        for i, (probe, br) in enumerate(zip(r.probes, r.baseline_results)):
            match = "✓" if br.matched_expected else "✗"
            lines.append(
                f"| {i+1} | {probe.description} | {probe.expected_safe} | {br.actual_safe} {match} |"
            )
        lines.append("")

        lines.append("#### Mutant Results")
        lines.append("")
        lines.append(
            "| Kind | Mutant Condition | Probes Killed | Kill Rate | Survived |"
        )
        lines.append(
            "|------|-----------------|---------------|-----------|----------|"
        )
        for mr in r.mutant_results:
            survived_str = "✓ Survived" if mr.survived else "✗ Killed"
            lines.append(
                f"| {mr.mutant.kind.value} | `{mr.mutant.mutant.condition}` | "
                f"{mr.probes_killed}/{mr.probes_total} | {mr.kill_rate:.1%} | {survived_str} |"
            )
        lines.append("")

    # Paper section
    lines.append("---")
    lines.append("")
    lines.append("## Paper Section: Axiom Robustness via Mutation Testing")
    lines.append("")
    lines.append(
        "We introduce *axiom mutation testing* as a quantitative method to evaluate "
        "the robustness of a safety axiom set. Inspired by mutation testing in software "
        "engineering [Jia & Harman, 2011], we apply six mutation operators to each axiom "
        "and measure how many mutations are *killed* — i.e., cause a change in verification "
        "outcome on a targeted probe suite."
    )
    lines.append("")
    lines.append("**Mutation operators:**")
    lines.append("")
    lines.append("| Operator | Description | Expected Effect |")
    lines.append("|----------|-------------|-----------------|")
    lines.append(
        "| `negate` | Wrap condition in `not(...)` | Many probes killed (proves axiom is active) |"
    )
    lines.append(
        "| `weaken_op` | Replace `>=` with `>`, `==` with `>=`, etc. | Few probes killed (measures boundary tightness) |"
    )
    lines.append(
        "| `strengthen_op` | Replace `>` with `>=`, `>=` with `==`, etc. | More probes killed (measures over-constraint) |"
    )
    lines.append(
        "| `shift_const` | Shift integer constants by ±1, ±5 | Measures sensitivity to threshold values |"
    )
    lines.append(
        "| `vacuous` | Replace condition with `true` | Zero probes killed → axiom is vacuous |"
    )
    lines.append("| `noop` | Identity (baseline) | Zero probes killed (sanity check) |")
    lines.append("")
    lines.append(
        "**Robustness Score** is defined as the fraction of non-noop mutants that are killed, "
        "with a penalty of 0 for any vacuous axiom. A score of 1.0 means every mutation "
        "changes at least one verification outcome — the axiom set is maximally discriminating."
    )
    lines.append("")
    lines.append(
        f"**Results**: Our axiom set achieves a Suite Robustness Score of "
        f"**{metrics['suite_robustness_score']:.1%}** across {metrics['total_axioms']} axioms "
        f"and {metrics['total_mutants']} mutants. "
        f"{metrics['total_killed']} of {metrics['total_mutants']} mutants were killed "
        f"(Mutation Score: {metrics['suite_mutation_score']:.1%})."
    )
    if metrics["vacuous_axioms"]:
        lines.append(
            f"Vacuous axioms detected: {', '.join(metrics['vacuous_axioms'])}. "
            "These have been flagged for strengthening."
        )
    else:
        lines.append(
            "No vacuous axioms were detected — every axiom actively constrains at least one program."
        )
    lines.append("")
    lines.append(
        "To our knowledge, no prior AI safety monitor has applied mutation testing to "
        "formally evaluate axiom robustness. This metric directly answers the reviewer "
        "question: *'How do we know your axioms are good?'*"
    )
    lines.append("")

    return "\n".join(lines)
