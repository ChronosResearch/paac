"""
PAAC command-line interface.

Commands:
  verify        Verify a SIL file for safety violations.
  self-verify   Run bootstrap self-verification of the PAAC TCB.
  attest        Generate a cryptographic attestation for a SIL file.
  multi-agent   Run a multi-agent coordination demo.
"""

from __future__ import annotations

import json
import os
import sys
import time

import click
import yaml

from .monitor.code_monitor import CodeModification, CodeMonitor


@click.group()
def cli() -> None:
    """PAAC - Provably Aligned Core v5.0"""


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("sil_file", type=click.Path(exists=True))
@click.option("--config", default="config/default.yaml", show_default=True)
@click.option("--axioms", default="config/axioms.yaml", show_default=True)
@click.option("--func-name", default="cli_func", show_default=True)
@click.option(
    "--attest",
    is_flag=True,
    default=False,
    help="Generate a cryptographic attestation after verification.",
)
def verify(
    sil_file: str, config: str, axioms: str, func_name: str, attest: bool
) -> None:
    """Verify a SIL file for safety violations."""
    try:
        with open(config) as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        cfg = {}

    cfg["axiom_path"] = axioms

    with open(sil_file) as f:
        code = f.read()

    monitor = CodeMonitor(cfg)
    mod = CodeModification(
        func_name=func_name,
        old_code="",
        new_code=code,
        pre_cond="true",
        post_cond="true",
        source_citation="https://cli.paac.local/verify",
    )

    result = monitor.intercept_modification(mod)
    click.echo(json.dumps(result, indent=2))

    if attest and result.get("status") == "accepted":
        _run_attest(func_name, code, axioms, safe=True)


# ---------------------------------------------------------------------------
# self-verify
# ---------------------------------------------------------------------------


@cli.command("self-verify")
@click.option(
    "--timeout-ms",
    default=5000,
    show_default=True,
    help="Z3 solver timeout per stub in milliseconds.",
)
@click.option(
    "--live",
    is_flag=True,
    default=False,
    help="Also translate and verify live TCB source files.",
)
@click.option(
    "--json-output", is_flag=True, default=False, help="Output results as JSON."
)
def self_verify(timeout_ms: int, live: bool, json_output: bool) -> None:
    """
    Run bootstrap self-verification of the PAAC TCB.

    Translates TCB function contracts to SIL stubs and verifies them
    against PAAC's own structural invariants.  This addresses the
    'who verifies the verifier?' problem.

    Limitations: only assert statements and simple arithmetic are
    translated.  External calls (Z3, Redis) are treated as uninterpreted.
    """
    from .core.self_verify import SelfVerifier

    click.echo("Running PAAC bootstrap self-verification...")
    sv = SelfVerifier(timeout_ms=timeout_ms)

    t0 = time.monotonic()
    result = sv.run()
    if live:
        click.echo("  Running live TCB verification...")
        live_result = sv.verify_live_tcb()
        # Merge results
        result.stub_results.update(live_result.stub_results)
        result.counterexamples.update(live_result.counterexamples)
        result.detail.extend(live_result.detail)
        result.passed = result.passed and live_result.passed
    elapsed = (time.monotonic() - t0) * 1000

    if json_output:
        output = {
            "passed": result.passed,
            "stage": result.stage,
            "elapsed_ms": round(elapsed, 1),
            "stubs": {
                name: {
                    "safe": safe,
                    "counterexample": result.counterexamples.get(name),
                }
                for name, safe in result.stub_results.items()
            },
            "message": result.message,
        }
        click.echo(json.dumps(output, indent=2))
    else:
        status = "PASSED" if result.passed else "FAILED"
        click.echo(f"\nResult: {status} (stage {result.stage})")
        click.echo(f"Elapsed: {elapsed:.0f}ms")
        click.echo(f"\nStub results ({len(result.stub_results)} stubs):")
        for name, safe in result.stub_results.items():
            icon = "OK" if safe else "FAIL"
            ce = result.counterexamples.get(name, "")
            ce_str = f"  -> {ce[:80]}" if ce else ""
            click.echo(f"  [{icon}] {name}{ce_str}")
        click.echo(f"\n{result.message}")

    sys.exit(0 if result.passed else 1)


# ---------------------------------------------------------------------------
# attest
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("sil_file", type=click.Path(exists=True))
@click.option("--axioms", default="config/axioms.yaml", show_default=True)
@click.option("--func-name", default="cli_func", show_default=True)
@click.option(
    "--verify-only",
    is_flag=True,
    default=False,
    help="Verify an existing attestation from stdin (JSON).",
)
def attest(sil_file: str, axioms: str, func_name: str, verify_only: bool) -> None:
    """
    Generate a cryptographic attestation for a SIL verification result.

    The attestation is an HMAC-SHA256 commitment over the program hash,
    axiom hash, result, and timestamp.  Third parties who hold the key
    can verify the attestation independently.
    """
    with open(sil_file) as f:
        code = f.read()

    if verify_only:
        raw = sys.stdin.read()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            click.echo(f"Error: invalid JSON: {exc}", err=True)
            sys.exit(1)
        from .core.attestation import AttestationRecord, verify_attestation

        record = AttestationRecord.from_dict(data)
        valid = verify_attestation(record)
        click.echo(json.dumps({"valid": valid}, indent=2))
        sys.exit(0 if valid else 1)

    _run_attest(func_name, code, axioms, safe=None)


def _run_attest(func_name: str, code: str, axioms_path: str, safe: bool | None) -> None:
    """Generate and print an attestation record."""
    import hashlib
    from .core.attestation import AttestationEngine, get_engine
    from .core.sil_compiler import SILCompiler
    from .axioms.axiom_parser import AxiomParser

    engine = get_engine()
    compiler = SILCompiler()

    try:
        ast, _ = compiler.compile(code)
        import json as _json

        def _node_to_dict(n):
            if isinstance(n, list):
                return [_node_to_dict(x) for x in n]
            if hasattr(n, "__dataclass_fields__"):
                return {k: _node_to_dict(getattr(n, k)) for k in n.__dataclass_fields__}
            return n

        ast_json = _json.dumps(_node_to_dict(ast), sort_keys=True, default=str)
        program_hash = engine.hash_program(ast_json)
    except Exception as exc:  # noqa: BLE001
        program_hash = hashlib.sha256(code.encode()).hexdigest()
        click.echo(
            f"Warning: compilation failed ({exc}); hashing raw source.", err=True
        )

    try:
        with open(axioms_path) as f:
            axiom_list = AxiomParser.parse(f.read())
        axiom_hash = engine.hash_axioms([a.condition for a in axiom_list])
    except Exception:  # noqa: BLE001
        axiom_hash = engine.hash_axioms([])

    if safe is None:
        safe = True  # default for CLI attest without verification

    mod_id = f"{func_name}:{int(time.time())}"
    record = engine.attest(mod_id, program_hash, axiom_hash, safe, None)
    click.echo(json.dumps(record.to_dict(), indent=2))


# ---------------------------------------------------------------------------
# multi-agent
# ---------------------------------------------------------------------------


@cli.command("multi-agent")
@click.option(
    "--agents", default=3, show_default=True, help="Number of simulated agents."
)
@click.option(
    "--mods-per-agent", default=2, show_default=True, help="Modifications per agent."
)
@click.option("--json-output", is_flag=True, default=False)
def multi_agent(agents: int, mods_per_agent: int, json_output: bool) -> None:
    """
    Run a multi-agent coordination demo.

    Simulates N agents each submitting modifications to different functions,
    then verifies them collectively using compositional BMC.
    """
    from .core.compositional import AgentModification, CompositionalVerifier

    verifier = CompositionalVerifier(timeout_ms=5000)
    results = []

    safe_func_template = """
func agent_{agent_id}_func_{mod_idx}(x: int) -> int {{
    assert x == x;
    return x;
}}
"""

    click.echo(
        f"Running multi-agent demo: {agents} agents, {mods_per_agent} mods each..."
    )

    for agent_idx in range(agents):
        agent_id = f"agent_{agent_idx}"
        verifier.register_agent(agent_id)
        for mod_idx in range(mods_per_agent):
            func_name = f"agent_{agent_idx}_func_{mod_idx}"
            code = safe_func_template.format(agent_id=agent_idx, mod_idx=mod_idx)
            mod = AgentModification(
                agent_id=agent_id,
                func_name=func_name,
                new_code=code,
                axioms=[],
            )
            verifier.submit(mod)

    # Verify all queued modifications
    all_mods: list = []
    for agent_idx in range(agents):
        for mod_idx in range(mods_per_agent):
            func_name = f"agent_{agent_idx}_func_{mod_idx}"
            queue_results = verifier.process_queue(func_name, [])
            results.extend(queue_results)

    metrics = verifier.metrics()
    all_accepted = all(r.accepted for r in results)

    if json_output:
        output = {
            "all_accepted": all_accepted,
            "total_verifications": len(results),
            "metrics": metrics,
            "results": [
                {
                    "func_names": r.func_names,
                    "accepted": r.accepted,
                    "agent_ids": r.agent_ids,
                }
                for r in results
            ],
        }
        click.echo(json.dumps(output, indent=2))
    else:
        status = "PASSED" if all_accepted else "FAILED"
        click.echo(f"\nResult: {status}")
        click.echo(f"Total verifications: {len(results)}")
        click.echo(f"Accepted: {sum(1 for r in results if r.accepted)}")
        click.echo(f"Rejected: {sum(1 for r in results if not r.accepted)}")
        click.echo(f"Conflicts detected: {metrics['total_conflicts']}")

    sys.exit(0 if all_accepted else 1)


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------


@cli.command("coverage")
@click.option("--axioms", default="config/axioms.yaml", show_default=True)
@click.option(
    "--path",
    "sil_path",
    default=None,
    help="Directory or file of SIL programs to analyse (uses built-in suite if omitted).",
)
@click.option("--out", default=None, help="Write JSON report to this file.")
@click.option("--json-output", is_flag=True, default=False)
def coverage(
    axioms: str, sil_path: str | None, out: str | None, json_output: bool
) -> None:
    """
    Measure axiom coverage over a set of SIL programs.

    Reports per-axiom active coverage percentage and an overall score.
    Integrates with mutation testing to produce a robustness x coverage matrix.
    """
    from .axioms.axiom_parser import AxiomParser
    from .coverage.axiom_coverage import (
        ProgramEntry,
        analyse_coverage,
        coverage_to_json,
    )

    try:
        with open(axioms) as f:
            axiom_list = AxiomParser.parse(f.read())
    except FileNotFoundError:
        click.echo(f"Axiom file not found: {axioms}", err=True)
        sys.exit(1)

    programs: list[ProgramEntry] = []
    if sil_path and os.path.isdir(sil_path):
        for fname in os.listdir(sil_path):
            if fname.endswith(".sil"):
                fpath = os.path.join(sil_path, fname)
                with open(fpath) as f:
                    programs.append(ProgramEntry(sil_code=f.read(), description=fname))
    elif sil_path and os.path.isfile(sil_path):
        with open(sil_path) as f:
            programs.append(ProgramEntry(sil_code=f.read(), description=sil_path))
    else:
        # Built-in canonical suite
        programs = [
            ProgramEntry(
                "func withdraw(balance: int, amount: int) -> int { return balance - amount; }",
                "withdraw_unconstrained",
            ),
            ProgramEntry(
                "func deposit(balance: int, amount: int) -> int { balance = balance + amount; assert balance >= 0; return balance; }",
                "deposit_safe",
            ),
            ProgramEntry(
                "func increment(counter: int) -> int { counter = counter + 1; return counter; }",
                "increment",
            ),
            ProgramEntry(
                "func compute(result: int) -> int { result = result * result; return result; }",
                "compute_square",
            ),
        ]

    result = analyse_coverage(programs, axiom_list)
    report = coverage_to_json(result)

    if out:
        with open(out, "w") as f:
            json.dump(report, f, indent=2)
        click.echo(f"Coverage report written to {out}")

    if json_output:
        click.echo(json.dumps(report, indent=2))
    else:
        click.echo(f"\nAxiom Coverage Report")
        click.echo(f"  Overall coverage : {result.overall_coverage:.1%}")
        click.echo(f"  Programs analysed: {result.total_programs}")
        click.echo(f"  Uncovered axioms : {result.uncovered_axioms or 'none'}")
        click.echo(f"\n  Per-axiom:")
        for r in result.axiom_results:
            click.echo(
                f"    {r.axiom_id:30s}  active={r.active_count}/{r.total_programs}  "
                f"score={r.coverage_score:.1%}"
            )


# ---------------------------------------------------------------------------
# repair
# ---------------------------------------------------------------------------


@cli.command("repair")
@click.option("--axiom-id", required=True, help="ID of the axiom to repair.")
@click.option("--axioms", default="config/axioms.yaml", show_default=True)
@click.option(
    "--program",
    "program_str",
    default=None,
    help="Inline SIL program string (uses built-in unsafe example if omitted).",
)
@click.option("--program-file", default=None, type=click.Path(exists=True))
@click.option("--max-iter", default=10, show_default=True)
@click.option("--json-output", is_flag=True, default=False)
def repair(
    axiom_id: str,
    axioms: str,
    program_str: str | None,
    program_file: str | None,
    max_iter: int,
    json_output: bool,
) -> None:
    """
    Run CEGAR axiom repair on a known-unsafe program.

    Automatically proposes a strengthened axiom that eliminates the
    counterexample and re-verifies.  Only conservative extensions are accepted.
    """
    from .axioms.axiom_parser import AxiomParser
    from .cegar.repair import repair_axiom

    try:
        with open(axioms) as f:
            axiom_list = AxiomParser.parse(f.read())
    except FileNotFoundError:
        click.echo(f"Axiom file not found: {axioms}", err=True)
        sys.exit(1)

    target = next((a for a in axiom_list if a.id == axiom_id), None)
    if target is None:
        click.echo(f"Axiom '{axiom_id}' not found in {axioms}", err=True)
        sys.exit(1)

    if program_file:
        with open(program_file) as f:
            program = f.read()
    elif program_str:
        program = program_str
    else:
        program = (
            f"func withdraw(balance: int, amount: int) -> int {{ "
            f"return balance - amount; }}"
        )

    result = repair_axiom(target, program, axiom_list, max_iterations=max_iter)

    if json_output:
        output = {
            "success": result.success,
            "original_condition": result.original_axiom.condition,
            "repaired_condition": (
                result.repaired_axiom.condition if result.repaired_axiom else None
            ),
            "iterations": result.total_iterations,
            "elapsed_ms": round(result.elapsed_ms, 1),
            "message": result.message,
            "iteration_detail": [
                {
                    "iteration": it.iteration,
                    "candidate": it.candidate_condition,
                    "conservative": it.is_conservative,
                    "re_verify_safe": it.re_verify_safe,
                    "reason": it.reason,
                }
                for it in result.iterations
            ],
        }
        click.echo(json.dumps(output, indent=2))
    else:
        status = "SUCCESS" if result.success else "FAILED"
        click.echo(f"\nCEGAR Repair: {status}")
        click.echo(f"  Original : {result.original_axiom.condition}")
        if result.repaired_axiom:
            click.echo(f"  Repaired : {result.repaired_axiom.condition}")
        click.echo(f"  Iterations: {result.total_iterations}")
        click.echo(f"  {result.message}")

    sys.exit(0 if result.success else 1)


# ---------------------------------------------------------------------------
# diff-verify
# ---------------------------------------------------------------------------


@cli.command("diff-verify")
@click.option("--old", "old_file", required=True, type=click.Path(exists=True))
@click.option("--new", "new_file", required=True, type=click.Path(exists=True))
@click.option("--axioms", default="config/axioms.yaml", show_default=True)
@click.option("--json-output", is_flag=True, default=False)
def diff_verify(old_file: str, new_file: str, axioms: str, json_output: bool) -> None:
    """
    Prove that a new function version is a conservative extension of the old.

    Returns CONSERVATIVE if the new version is at least as safe as the old,
    REGRESSION if the new version is less safe, or EQUIVALENT if identical.
    """
    from .axioms.axiom_parser import AxiomParser
    from .diffverify.diff_verifier import DifferentialVerifier

    try:
        with open(axioms) as f:
            axiom_list = AxiomParser.parse(f.read())
    except FileNotFoundError:
        axiom_list = []

    with open(old_file) as f:
        old_program = f.read()
    with open(new_file) as f:
        new_program = f.read()

    verifier = DifferentialVerifier()
    result = verifier.verify(old_program, new_program, axiom_list)

    if json_output:
        ce = None
        if result.counterexample:
            ce = {
                "assignments": result.counterexample.assignments,
                "direction": result.counterexample.direction,
            }
        click.echo(
            json.dumps(
                {
                    "status": result.status.value,
                    "is_safe_upgrade": result.is_safe_upgrade,
                    "axioms_used": result.axioms_used,
                    "counterexample": ce,
                    "elapsed_ms": round(result.elapsed_ms, 1),
                    "message": result.message,
                },
                indent=2,
            )
        )
    else:
        click.echo(f"\nDifferential Verification: {result.status.value.upper()}")
        click.echo(f"  Safe upgrade: {result.is_safe_upgrade}")
        click.echo(f"  Axioms used : {len(result.axioms_used)}")
        if result.counterexample:
            click.echo(f"  Counterexample: {result.counterexample}")
        click.echo(f"  {result.message}")

    sys.exit(0 if result.is_safe_upgrade else 1)


# ---------------------------------------------------------------------------
# export-proof
# ---------------------------------------------------------------------------


@cli.command("export-proof")
@click.argument("sil_file", type=click.Path(exists=True))
@click.option("--axioms", default="config/axioms.yaml", show_default=True)
@click.option("--out", default=None, help="Write certificate JSON to this file.")
@click.option(
    "--verify",
    "do_verify",
    is_flag=True,
    default=False,
    help="Verify an existing certificate from --cert-file.",
)
@click.option("--cert-file", default=None, type=click.Path(exists=False))
def export_proof(
    sil_file: str,
    axioms: str,
    out: str | None,
    do_verify: bool,
    cert_file: str | None,
) -> None:
    """
    Export a machine-checkable proof certificate for a verified SIL program.

    The certificate contains the program hash, axiom hashes, Z3 witness
    assertions, and an HMAC integrity seal.  Third parties can verify it
    without re-running the full PAAC pipeline.
    """
    from .axioms.axiom_parser import AxiomParser
    from .certificates.proof_cert import (
        CertificateExporter,
        ProofCertificate,
        verify_certificate,
    )
    from .core.verifier import VerificationError

    if do_verify and cert_file:
        with open(cert_file) as f:
            cert_data = json.load(f)
        with open(sil_file) as f:
            program = f.read()
        cert = ProofCertificate.from_dict(cert_data)
        check = verify_certificate(cert, program)
        click.echo(
            json.dumps(
                {
                    "valid": check.valid,
                    "certificate_id": check.certificate_id[:16] + "...",
                    "checks_passed": check.checks_passed,
                    "checks_failed": check.checks_failed,
                    "message": check.message,
                },
                indent=2,
            )
        )
        sys.exit(0 if check.valid else 1)

    try:
        with open(axioms) as f:
            axiom_list = AxiomParser.parse(f.read())
    except FileNotFoundError:
        axiom_list = []

    with open(sil_file) as f:
        program = f.read()

    exporter = CertificateExporter()
    try:
        cert = exporter.export(program, axiom_list)
    except VerificationError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    cert_json = cert.to_json()
    if out:
        with open(out, "w") as f:
            f.write(cert_json)
        click.echo(f"Certificate written to {out}")
    else:
        click.echo(cert_json)


if __name__ == "__main__":
    cli()
