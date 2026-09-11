#!/usr/bin/env python3.11
# Copyright 2026 Shashank Kumar
# SPDX-License-Identifier: Apache-2.0
"""
Reproduce every decomposition synthesis result in docs/DECOMPOSITION.md.

    PYTHONPATH=. python3.11 scripts/run_decomposition.py
    PYTHONPATH=. python3.11 scripts/run_decomposition.py --json

This script is the artefact behind the numbers. PLAN_V8 section 9: if nobody can
rerun it, delete it. There is no seed and no sampling, so a rerun on any machine
with the same axiom set should print the same thing; if it does not, that is
itself a finding and should be reported.

Exit status is 0 whatever the outcomes are. A witness is a research result, not
a build failure, and making the script fail on one would create pressure to stop
looking.
"""

from __future__ import annotations

import argparse
import json
import sys

from src.decomp import synthesise_all
from src.decomp.schema import SCHEMAS, SchemaOutcome


def _text_report(results) -> str:
    lines: list[str] = []
    lines.append("PAAC decomposition synthesis")
    lines.append("=" * 72)
    lines.append("")

    for result in results:
        lines.append(f"Schema {result.schema_id}: {result.title}")
        lines.append(f"  outcome  : {result.outcome.value.upper()}")
        low, high = result.hole_range
        if result.outcome is not SchemaOutcome.NOT_EXPRESSIBLE:
            lines.append(f"  holes    : range [{low}, {high}]")
        if result.note:
            lines.append(f"  note     : {result.note}")
        lines.append(f"  boundary : {result.boundary}")

        if result.witness:
            lines.append(f"  assignment: {result.witness.holes}")
            lines.append(f"  claim    : {result.witness.expected_violation}")
            lines.append(f"  sequence : {len(result.witness.modifications)} modifications")
            for i, mod in enumerate(result.witness.modifications, 1):
                lines.append(f"    [{i}] {mod.func_name}, pre: {mod.pre_cond or 'none'}")

        if result.confirmation:
            conf = result.confirmation
            lines.append("  confirmation against the real system:")
            for step in conf.steps:
                verdict = "ACCEPTED" if step.accepted else "REJECTED"
                lines.append(f"    verifier: {step.func_name}: {verdict} ({step.detail})")
            lines.append(f"    runtime : {conf.runtime_detail}")
        lines.append("")

    # The metric, with its denominator, per PLAN_V8 section 6.
    total = len([r for r in results if r.outcome is not SchemaOutcome.NOT_EXPRESSIBLE])
    witnesses = len([r for r in results if r.outcome is SchemaOutcome.WITNESS])
    defended = len([r for r in results if r.outcome is SchemaOutcome.DEFENDED])
    spurious = len([r for r in results if r.outcome is SchemaOutcome.SPURIOUS])
    null = len([r for r in results if r.outcome is SchemaOutcome.NO_WITNESS])

    lines.append("Summary")
    lines.append("-" * 72)
    lines.append(f"  schemas declared        : {len(SCHEMAS)}")
    lines.append(f"  schemas searched        : {total}")
    lines.append(f"  confirmed witnesses     : {witnesses}")
    lines.append(f"  attacks defended        : {defended}")
    lines.append(f"  no witness in schema    : {null}")
    lines.append(f"  spurious candidates     : {spurious}")
    lines.append("")
    lines.append(
        "  Read these as counts over the declared schemas only. They are not a "
        "statement about decomposition attacks in general, and a schema that "
        "found nothing bounds only itself."
    )
    return "\n".join(lines)


def _json_report(results) -> str:
    payload = []
    for result in results:
        entry = {
            "schema": result.schema_id,
            "title": result.title,
            "outcome": result.outcome.value,
            "hole_range": list(result.hole_range),
            "boundary": result.boundary,
            "note": result.note,
        }
        if result.witness:
            entry["holes"] = result.witness.holes
            entry["claim"] = result.witness.expected_violation
            entry["modifications"] = [
                {
                    "func_name": m.func_name,
                    "pre_cond": m.pre_cond,
                    "code": m.code,
                }
                for m in result.witness.modifications
            ]
        if result.confirmation:
            entry["confirmation"] = {
                "all_steps_accepted": result.confirmation.all_steps_accepted,
                "runtime_violated": result.confirmation.runtime_violated,
                "runtime_detail": result.confirmation.runtime_detail,
                "steps": [
                    {
                        "func_name": s.func_name,
                        "accepted": s.accepted,
                        "detail": s.detail,
                    }
                    for s in result.confirmation.steps
                ],
            }
        payload.append(entry)
    return json.dumps({"results": payload}, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=10_000,
        help="Per-query solver timeout. Recorded with any UNKNOWN result.",
    )
    args = parser.parse_args(argv)

    results = synthesise_all(timeout_ms=args.timeout_ms)
    print(_json_report(results) if args.json else _text_report(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
