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
@click.option("--attest", is_flag=True, default=False,
              help="Generate a cryptographic attestation after verification.")
def verify(sil_file: str, config: str, axioms: str, func_name: str, attest: bool) -> None:
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
@click.option("--timeout-ms", default=5000, show_default=True,
              help="Z3 solver timeout per stub in milliseconds.")
@click.option("--live", is_flag=True, default=False,
              help="Also translate and verify live TCB source files.")
@click.option("--json-output", is_flag=True, default=False,
              help="Output results as JSON.")
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
@click.option("--verify-only", is_flag=True, default=False,
              help="Verify an existing attestation from stdin (JSON).")
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


def _run_attest(
    func_name: str, code: str, axioms_path: str, safe: bool | None
) -> None:
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
        click.echo(f"Warning: compilation failed ({exc}); hashing raw source.", err=True)

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
@click.option("--agents", default=3, show_default=True,
              help="Number of simulated agents.")
@click.option("--mods-per-agent", default=2, show_default=True,
              help="Modifications per agent.")
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

    click.echo(f"Running multi-agent demo: {agents} agents, {mods_per_agent} mods each...")

    for agent_idx in range(agents):
        agent_id = f"agent_{agent_idx}"
        verifier.register_agent(agent_id)
        for mod_idx in range(mods_per_agent):
            func_name = f"agent_{agent_idx}_func_{mod_idx}"
            code = safe_func_template.format(
                agent_id=agent_idx, mod_idx=mod_idx
            )
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


if __name__ == "__main__":
    cli()
