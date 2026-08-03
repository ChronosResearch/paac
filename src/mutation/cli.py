"""
src/mutation/cli.py
--------------------
CLI entry point for axiom mutation testing.

Usage:
    PYTHONPATH=. python3.11 -m src.mutation.cli [--axiom-file PATH] [--out-dir DIR]

Outputs:
    <out-dir>/axiom_mutation_results.json
    <out-dir>/axiom_mutation_results.csv
    <out-dir>/AXIOM_MUTATION_REPORT.md
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from src.axioms.axiom_parser import Axiom, AxiomParser
from src.mutation.mutation_runner import run_all_axioms
from src.mutation.report import compute_suite_metrics, to_csv, to_json, to_markdown

# Default axioms used when no file is provided — the canonical PAAC axiom set
# plus additional axioms that exercise all mutation operators.
_DEFAULT_AXIOMS = [
    Axiom(
        id="no_negative_balance",
        description="Account balance must remain non-negative.",
        condition="balance >= 0",
        target_functions=["withdraw", "deposit", "transfer"],
    ),
    Axiom(
        id="counter_in_range",
        description="Counter must be non-negative.",
        condition="counter >= 0",
        target_functions=["increment", "decrement", "reset_counter"],
    ),
    Axiom(
        id="result_bounded",
        description="Computed result must not exceed 1000000.",
        condition="result >= 0",
        target_functions=["compute", "calculate"],
    ),
    Axiom(
        id="amount_positive",
        description="Transaction amount must be strictly positive.",
        condition="amount > 0",
        target_functions=["withdraw", "deposit"],
    ),
    Axiom(
        id="index_nonneg",
        description="Array index must be non-negative.",
        condition="index >= 0",
        target_functions=["get_elem", "set_elem"],
    ),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="PAAC Axiom Mutation Testing — quantitative robustness analysis"
    )
    parser.add_argument(
        "--axiom-file",
        default=None,
        help="Path to axioms YAML file (default: built-in canonical axiom set)",
    )
    parser.add_argument(
        "--out-dir",
        default=".",
        help="Directory to write reports (default: current directory)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )
    args = parser.parse_args(argv)

    # Load axioms
    if args.axiom_file:
        with open(args.axiom_file) as fh:
            axioms = AxiomParser.parse(fh.read())
        if not axioms:
            print(f"ERROR: No axioms found in '{args.axiom_file}'", file=sys.stderr)
            return 1
    else:
        axioms = _DEFAULT_AXIOMS

    if not args.quiet:
        print(f"[PAAC Mutation Testing] Running on {len(axioms)} axioms...")
        print(f"  Axioms: {[a.id for a in axioms]}")

    t0 = time.monotonic()
    results = run_all_axioms(axioms)
    elapsed = time.monotonic() - t0

    metrics = compute_suite_metrics(results)

    if not args.quiet:
        print(f"\n[Results] Completed in {elapsed:.1f}s")
        print(f"  Suite Mutation Score  : {metrics['suite_mutation_score']:.1%}")
        print(f"  Suite Robustness Score: {metrics['suite_robustness_score']:.1%}")
        print(
            f"  Mutants killed        : {metrics['total_killed']}/{metrics['total_mutants']}"
        )
        if metrics["vacuous_axioms"]:
            print(f"  ⚠️  Vacuous axioms     : {metrics['vacuous_axioms']}")
        else:
            print("  No vacuous axioms detected.")
        if metrics["critical_axiom"]:
            print(f"  Critical axiom        : {metrics['critical_axiom']}")

    # Write reports
    os.makedirs(args.out_dir, exist_ok=True)

    json_path = os.path.join(args.out_dir, "axiom_mutation_results.json")
    csv_path = os.path.join(args.out_dir, "axiom_mutation_results.csv")
    md_path = os.path.join(args.out_dir, "AXIOM_MUTATION_REPORT.md")

    with open(json_path, "w") as fh:
        fh.write(to_json(results))
    with open(csv_path, "w") as fh:
        fh.write(to_csv(results))
    with open(md_path, "w") as fh:
        fh.write(to_markdown(results))

    if not args.quiet:
        print("\n[Reports written]")
        print(f"  JSON : {json_path}")
        print(f"  CSV  : {csv_path}")
        print(f"  MD   : {md_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
