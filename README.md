# PAAC — Provably Aligned AI Core v7.0

**386 tests passing · Ed25519 asymmetric attestation · Real AST-based BMC · Bounded Loop Verification · 5 axioms · 43 mutants · 100% robustness**

PAAC is a deterministic safety wrapper for self-modifying AI agents. It intercepts every proposed code modification, compiles it to the Safe Intermediate Language (SIL), and verifies it against safety axioms using Z3 SMT-based bounded model checking. Only modifications that produce an UNSAT result are accepted.

Paper: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6879218  
License: Copyright © 2026 Shashank Kumar. All rights reserved.

---

## Architecture

```
+------------------+     +-----------------+     +---------------------+     +------------------+
|   Inner Agent    | --> |  Code Monitor   | --> | Verification Engine | --> |   Attestation    |
+------------------+     +-----------------+     +---------------------+     +------------------+
                                                          |                           |
                                                          v                           v
                                               +---------------------+     +------------------+
                                               | Safety Property DB  |     |  Ed25519 Cert    |
                                               +---------------------+     |  Store / Export  |
                                                                           +------------------+
```

Every proposed code change is:
1. Compiled to SIL (lexed, parsed, type-checked, CFG-built)
2. SSA-encoded and loop-unrolled into a Z3 BMC query
3. Checked against safety axioms: `BMC(f,k) = pre_f ∧ semantics(f,k) ∧ violation`
4. If UNSAT → accepted, Ed25519-signed attestation record generated
5. If SAT → rejected with counterexample, rollback triggered

---

## Core Verification Engine

**Real AST-based BMC** — not string matching or pattern heuristics:

- SIL source → `SILLexer` → `SILParser` → `ProgramNode` AST
- `SILTypeChecker`: duplicate params, undefined variables, type mismatches, no-return warnings
- Call-graph DFS cycle detection (no recursion, direct or mutual)
- `SSAEnv`: full SSA form with phi-node merges at if/else join points
- `StmtEncoder`: loop unrolling up to declared bound (global cap: 10,000 iterations)
- `ExprEncoder`: translates every SIL operator to a Z3 expression
- All integer parameters constrained to 32-bit signed range `[-2³¹, 2³¹-1]` for soundness
- `pre_cond` encoded as a Z3 solver assertion (input constraint, not a violation flag), implementing the paper §3.4 BMC formula exactly
- Axiom encoding uses the live `SSAEnv` so body-assigned sentinel variables (`exit_called`, `network_calls`) resolve to their current SSA values

### Bounded Loop Verification (v7.0 — DoS Prevention)

Every loop bound is **formally proven by Z3** before BMC runs:

- `LoopBoundAnalyzer` creates a Z3 Int equal to the declared bound and checks `bound > MAX_LOOP_BOUND` (UNSAT = proven safe)
- Produces a `LoopBoundReport` with per-loop `LoopBoundResult` entries — a verifiable certificate for every loop
- Three-layer enforcement:
  1. **Parse time** (`SILParser`): rejects `bound > 10,000` or `bound ≤ 0` immediately
  2. **Z3 proof** (`LoopBoundAnalyzer`): formal UNSAT certificate per loop before BMC
  3. **Runtime** (`SILRuntime`): enforces cap during execution as final backstop
- `_verify_inner` returns `(safe, counterexample, LoopBoundReport)` — loop proof travels with every verification result
- Nested loops and multi-function programs fully supported
- `analyze_loop_bounds(ast)` available as a standalone API

---

## Safety Axioms (5)

| Axiom | Condition | Scope |
|---|---|---|
| `no_negative_balance` | `balance >= 0` | financial functions |
| `counter_in_range` | `counter >= 0` | counter functions |
| `result_bounded` | `result >= 0` | compute functions |
| `no_exit` | `exit_called == 0` | all functions |
| `no_network` | `network_calls == 0` | all functions |

Axiom mutation testing: **43 mutants across 5 axioms, 100% robustness score**. Every mutation of every axiom changes at least one verification outcome. No axiom is vacuous.

---

## Novel Extensions

### 1. Bootstrap Self-Verification (§4.1)
PAAC verifies its own TCB. Six SIL stubs encode the safety contracts of the core TCB functions. Each stub is verified against `SELF_AXIOMS` (structural invariants: timeout positive, loop bound positive, safe flag non-negative, cache key non-empty). If all stubs return UNSAT, PAAC's structural invariants hold for all valid inputs.

- CLI: `--self-verify`
- REST: `POST /self-verify`
- 6 stubs verified, all UNSAT

### 2. Proof-Carrying Modification — PCM (§4.2)
The agent submits a formal proof alongside every code modification. PAAC verifies the proof (not the code) using an independent AST-based proof checker — no Z3 invoked.

- Proof checker uses Python `ast` module for independent expression evaluation (not string matching)
- Interval arithmetic symbolic environment tracks per-variable bounds
- Target: **< 10 ms per proof** (measured: typically 1–3 ms)
- Proof language: `Assume`, `Assign`, `Assert`, `ApplyAxiom`, `BranchSafe`, `LoopInvariant`, `Conclude`
- PCM certificates appended to `pcm_audit.jsonl`

### 3. Cryptographic Attestation — Ed25519 (§4.3)
Every accepted modification receives an **Ed25519 asymmetric signature** (not HMAC). The private key signs; any holder of the public key can verify without trusting PAAC.

- Signed payload: `SHA-256(canonical_json(modification_id, program_hash, axiom_hash, result, ce_hash, timestamp, proof_hash, version))`
- `proof_hash`: SHA-256 of the PCM proof JSON, included in the signed payload when PCM mode is active — tampering with the proof invalidates the Ed25519 signature
- Key rotation supported: old attestations remain verifiable with the old public key
- Thread-safe, < 5 ms per attestation
- Set `PAAC_ATTEST_PRIVATE_KEY` (PEM) for persistent keys; ephemeral keypair generated otherwise

### 4. CEGAR Axiom Repair (§4.4)
When verification returns SAT, PAAC extracts the counterexample and proposes a strengthened axiom that eliminates it. The repair is accepted only if it does not reduce the mutation testing robustness score.

### 5. Differential Verification (§4.5)
Proves that a new function version is a conservative extension of the old version: it satisfies all the same axioms and introduces no new violation paths. Returns a formal proof or counterexample.

### 6. Axiom Mutation Testing & Coverage (§4.6)
Systematic mutation operators: negate, weaken_op, strengthen_op, shift_const (±1, ±5), vacuous, noop.

- 43 mutants across 5 axioms
- Robustness score = fraction of non-noop mutants killed
- Vacuous detection: if the vacuous mutant (condition=`true`) survives, robustness = 0%
- Axiom coverage: instruments the verifier to record which axioms fire during verification

---

## Trusted Computing Base (TCB)

~2,400 lines across six core modules:

| Module | Lines | Responsibility |
|---|---|---|
| `verifier.py` | ~780 | BMC pipeline, SSA encoding, Z3 integration |
| `sil_compiler.py` | ~695 | Lexer, parser, type checker, CFG builder |
| `sil_runtime.py` | ~170 | Runtime execution, bounds checking |
| `code_monitor.py` | ~485 | Interception, axiom filtering, rollback |
| `failsafe.py` | ~185 | Circuit breaker, WAL, watchdog |
| `tcb_protect.py` | ~105 | TCB file protection (chmod read-only at startup) |

---

## Quick Start

### Docker (recommended)

```bash
docker build -t paac:v6.1 -f docker/Dockerfile .
docker run --rm --memory=2g -e PAAC_API_KEY=changeme paac:v6.1
```

### Local

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python3.11 -m pytest tests/ -v
```

Expected: **386 tests pass.**

---

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/verify` | POST | Submit a code modification for verification |
| `/health` | GET | Service health (healthy / degraded / unhealthy) |
| `/metrics` | GET | Prometheus metrics |
| `/self-verify` | POST | Bootstrap self-verification of the TCB |
| `/attest/{id}` | GET | Retrieve Ed25519 attestation record by modification ID |
| `/attest/verify` | POST | Verify an attestation commitment |
| `/agents` | GET | List registered agents and their status |

All `/verify` requests require the `X-API-Key` header when `PAAC_API_KEY` is set. Key comparison uses `secrets.compare_digest` (constant-time).

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PAAC_API_KEY` | *(empty — no auth)* | API authentication key |
| `PAAC_ATTEST_PRIVATE_KEY` | *(ephemeral)* | PEM-encoded Ed25519 private key for attestation signing |
| `PAAC_ATTEST_PUBLIC_KEY` | *(derived)* | PEM-encoded Ed25519 public key for verification |
| `PAAC_CERT_KEY` | *(insecure default)* | HMAC key for PCM certificates — change before deployment |
| `PAAC_PCM_MODE` | `false` | Require a formal proof with every modification |
| `PAAC_PCM_LOG` | `pcm_audit.jsonl` | PCM certificate audit log path |
| `REDIS_HOST` | `redis` | Redis hostname (falls back to WAL if unavailable) |
| `PAAC_RATE_LIMIT` | `100` | Requests per minute per IP |
| `PAAC_MAX_LOOP_BOUND` | `10000` | Global loop bound cap (parse + Z3 + runtime) |
| `PAAC_WATCHDOG_TIMEOUT` | `60` | Watchdog stall timeout (seconds) |

---

## Operational Features

- **Watchdog**: two-thread design (liveness stamps every second, monitor checks every 5 s) — no false alarms during idle
- **Circuit breaker**: 5 failures → OPEN, 60 s cooldown, automatic reset
- **WAL**: JSON-lines write-ahead log, atomic registry save, crash-resilient rollback
- **Redis fallback**: degrades to in-memory WAL with warning when Redis is unavailable
- **Rate limiting**: 100 req/min/IP (configurable)
- **Prometheus metrics**: counters, histograms, gauges for verifications, attestations, circuit breaker state
- **Constant-time response**: 200 ms floor on all verification responses (timing side-channel resistance, §3.5)
- **Z3 subprocess isolation**: each verification runs in a separate process with OS resource limits (1 GB AS, 5 s CPU on Linux), authenticated IPC token, 3-retry crash recovery

---

## Known Limitations

- Loop bounds must be declared manually in SIL source; no automated inference
- BMC is sound only when declared bound ≥ actual iteration count needed for termination
- SIL does not support heap allocation, pointer aliasing, or concurrency
- TCB protection is filesystem `chmod` only — not kernel-level memory protection
- Ed25519 provides integrity and non-repudiation; it does not provide zero-knowledge proofs (future: SNARKs)
- Z3 memory limits enforced on Linux only (not macOS)

See [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for the full list.

---

## Documentation

- [SIL Architecture](docs/SIL_ARCHITECTURE.md)
- [PCM Architecture](docs/PCM_ARCHITECTURE.md)
- [Proof Language Spec](docs/PROOF_LANGUAGE.md)
- [Deployment Guide](docs/DEPLOYMENT.md)
- [Production Runbook](docs/PRODUCTION_RUNBOOK.md)
- [Security Policy](SECURITY.md)
- [Audit Findings](AUDIT_FINDINGS.md)

---

## Contact

Shashank Kumar — shashankchoudhary792@gmail.com  
Repository: https://github.com/ChronosResearch/paac
