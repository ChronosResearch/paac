# PAAC: Provably Aligned AI Core v8.0 Prototype

**398 tests passing, 2 expected failures · 5 axioms, all effective · Ed25519 asymmetric attestation · Real AST-based BMC · Bounded Loop Verification · 43 mutants · 2 confirmed decomposition vulnerabilities, open**

Read this before the rest of the file. Every figure above is measured, and two of
them are worse than a reader would assume.

**Suite: 398 passed, 2 xfailed, exit 0** (verified, 219.46s, Windows,
Python 3.11.9). The earlier claim of "386 tests passing" was never measured; when
first run the real figure was 400 collected with **5 failing**. The two expected
failures are deliberate and must not be "fixed" by deleting them: they pin the
two open decomposition vulnerabilities below, so the defence cannot land without
someone removing the markers.

**"5 axioms, all effective" is new, and it was not true until recently.** Three of
the five never fired at all: `result_bounded` was structurally dead because the
verifier discarded return values, and `no_exit` and `no_network` only applied to
code that happened to declare the sentinel variables they name. Axioms that could
not be encoded were silently dropped, and the verifier then reported the function
safe having checked nothing. The same defect made all four of PAAC's *self*
verification axioms inert. Both are fixed; see `AUDIT_FINDINGS.md` C-03 and C-04.

**Two confirmed decomposition vulnerabilities are open.** A sequence of
modifications, each individually accepted by the verifier, can compose into a
violation of a safety axiom. Both were synthesised by Z3 and confirmed end to end
through the production entry point and the real runtime. Call-site preconditions
are unenforced (D-01), and replacing a function does not re-verify its callers
(D-02). The defence is designed but not built. Full write-up, threat model, and
the boundary of what the result does and does not establish:
[`docs/DECOMPOSITION.md`](docs/DECOMPOSITION.md).

PAAC is a deterministic safety wrapper for self-modifying AI agents. It intercepts every proposed code modification, compiles it to the Safe Intermediate Language (SIL), and verifies it against safety axioms using Z3 SMT-based bounded model checking. Only modifications that produce an UNSAT result are accepted.

Paper: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6879218  
License: Apache-2.0. Copyright 2026 Shashank Kumar. See `LICENSE` and `NOTICE`.

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

**Real AST-based BMC**, not string matching or pattern heuristics:

- SIL source → `SILLexer` → `SILParser` → `ProgramNode` AST
- `SILTypeChecker`: duplicate params, undefined variables, type mismatches, no-return warnings
- Call-graph DFS cycle detection (no recursion, direct or mutual)
- `SSAEnv`: full SSA form with phi-node merges at if/else join points
- `StmtEncoder`: loop unrolling up to declared bound (global cap: 10,000 iterations)
- `ExprEncoder`: translates every SIL operator to a Z3 expression
- All integer parameters constrained to 32-bit signed range `[-2³¹, 2³¹-1]` for soundness
- `pre_cond` encoded as a Z3 solver assertion (input constraint, not a violation flag), implementing the paper §3.4 BMC formula exactly
- Axiom encoding uses the live `SSAEnv` so body-assigned sentinel variables (`exit_called`, `network_calls`) resolve to their current SSA values

### Bounded Loop Verification (v7.0: DoS Prevention)

The cap is enforced at three layers, and **two of the three carry the guarantee.**
The parse-time check and the runtime check are load-bearing. The Z3 step is a
per-loop certificate rather than a proof: it asserts that a literal the parser has
already constrained to be at most the cap exceeds the cap, so it is unsatisfiable
by construction. It says nothing about termination or actual iteration counts, and
it does not infer bounds. Describing that layer as what prevents the denial of
service, as earlier revisions did, attributes the guarantee to the one layer that
does not carry it.

- `LoopBoundAnalyzer` creates a Z3 Int equal to the declared bound and checks `bound > MAX_LOOP_BOUND` (UNSAT = proven safe)
- Produces a `LoopBoundReport` with per-loop `LoopBoundResult` entries, a verifiable certificate for every loop
- Three-layer enforcement:
  1. **Parse time** (`SILParser`): rejects `bound > 10,000` or `bound ≤ 0` immediately
  2. **Z3 proof** (`LoopBoundAnalyzer`): formal UNSAT certificate per loop before BMC
  3. **Runtime** (`SILRuntime`): enforces cap during execution as final backstop
- `_verify_inner` returns `(safe, counterexample, LoopBoundReport)`, loop proof travels with every verification result
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
Six SIL stubs mirror the shape of six core TCB functions, each verified against
`SELF_AXIOMS` (structural invariants: timeout positive, loop bound positive, safe
flag non-negative, cache key non-empty).

**The shipped stubs are tautologies, so this currently establishes very little
about the TCB.** Each has the shape `if timeout_ms >= 1 { assert timeout_ms >= 1; }`,
so the assertion is implied by its own guard and Z3 returns UNSAT syntactically
rather than because anything about `verifier.py` was checked. Until the C-04 fix all
four self-axioms were additionally being dropped, so this path reported success
while checking almost nothing, and a claims document cited it as verified. The drop
is fixed; the tautology stands. What the module genuinely provides is a working
Python-to-SIL translation path and a place to attach real obligations.

- CLI: `--self-verify`
- REST: `POST /self-verify`
- 6 stubs verified, all UNSAT

### 2. Proof-Carrying Modification: PCM (§4.2)
The agent submits a formal proof alongside every code modification. PAAC verifies the proof (not the code) using an independent AST-based proof checker, no Z3 invoked.

- Proof checker uses Python `ast` module for independent expression evaluation (not string matching)
- Interval arithmetic symbolic environment tracks per-variable bounds
- Target: **< 10 ms per proof** (measured: typically 1–3 ms)
- Proof language: `Assume`, `Assign`, `Assert`, `ApplyAxiom`, `BranchSafe`, `LoopInvariant`, `Conclude`
- PCM certificates appended to `pcm_audit.jsonl`

### 3. Cryptographic Attestation: Ed25519 (§4.3)
Every accepted modification receives an **Ed25519 asymmetric signature** (not HMAC).
The private key signs, and a holder of the public key can check the signature
without trusting PAAC.

**The shipped `/attest/verify` endpoint does not yet deliver that property.** It
checks a submitted record against the public key embedded in that same record, so
it establishes internal consistency rather than provenance: anyone can mint a record
with their own keypair and have it return `{"valid": true}`. Genuine provenance
checking needs `verify_with_public_key(record, known_pinned_pem)`, which exists and
which no endpoint calls. Note also that PCM certificates
(`src/pcm/certificate.py`) are a separate, symmetric HMAC-SHA256 path with a
publicly known default key, so they give integrity but neither non-repudiation nor
public verifiability.

- Signed payload: `SHA-256(canonical_json(modification_id, program_hash, axiom_hash, result, ce_hash, timestamp, proof_hash, version))`
- `proof_hash`: SHA-256 of the PCM proof JSON, included in the signed payload when PCM mode is active, tampering with the proof invalidates the Ed25519 signature
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

**The enforced TCB is four modules, 2,101 lines.** That is the hardcoded list in
`protect_tcb()` (`src/core/tcb_protect.py`), and it is the only place the boundary
is defined in code. Earlier revisions of this section claimed "~2,400 lines across
six core modules"; the line total was close and the boundary was not.

| Module | Lines | Protected | Responsibility |
|---|---:|:---:|---|
| `verifier.py` | 1,193 | yes | BMC pipeline, SSA encoding, axiom encoding, Z3 driver |
| `code_monitor.py` | 623 | yes | Interception, axiom filtering, precondition gate, rollback |
| `failsafe.py` | 182 | yes | Circuit breaker, WAL, registry persistence |
| `tcb_protect.py` | 103 | yes | TCB file protection, IPC token |
| `sil_compiler.py` | 705 | **no** | Lexer, parser, call-graph cycle check, type checker, CFG |
| `sil_runtime.py` | 166 | **no** | Runtime execution, instruction and loop limits |

Counts include blank and comment lines, measured at commit `a78745d` with
`(Get-Content <file>).Count`.

**`sil_compiler.py` is outside the protected set, and it performs the recursion
check and the loop-bound checks the rest of the safety argument depends on.**
Anything that trusts SIL compilation is trusting code this mechanism does not
protect. Two further qualifications on the protection itself: it is `chmod`, not
kernel-level immutability, despite a module docstring that says otherwise
(`R-2` in [KNOWN_ISSUES.md](KNOWN_ISSUES.md)); and it returns early on non-Linux
hosts, so on Windows, where every figure in this README was measured, it does
nothing.

---

## Quick Start

### Docker (recommended)

```bash
docker build -t paac:v8.0 -f docker/Dockerfile .
docker run --rm --memory=2g -e PAAC_API_KEY=changeme paac:v8.0
```

### Local

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python3.11 -m pytest tests/ -v
```

Expected: **398 passed, 2 xfailed**, in roughly 3 to 4 minutes.

Both `xfailed` results are correct and must not be "fixed" by deleting the tests.
They are `test_paac_should_reject_schema_a_composition` and
`test_paac_should_reject_schema_c_composition` in `tests/test_decomposition.py`,
each marked `xfail(strict=True)`. They describe the behaviour PAAC ought to have
once the composition defence exists, and they fail today because it does not.
Because they are strict, they turn into *failures* the moment the defence lands,
which forces whoever builds it to come back and convert them.

To reproduce the decomposition findings on their own:

```bash
PYTHONPATH=. python -m pytest tests/test_decomposition.py -q
PYTHONPATH=. python -c "from src.decomp import synthesise_all; [print(r.summary()) for r in synthesise_all()]"
```

If you see a `ModuleNotFoundError` for `fastapi`, install the declared
dependencies first with `pip install -r requirements.txt`. Several of them
(`fastapi`, `pydantic`, `uvicorn`, `prometheus-client`) are required for
`src/main.py` to import at all, and one test imports it.

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
| `PAAC_API_KEY` | *(empty, no auth)* | API authentication key |
| `PAAC_ATTEST_PRIVATE_KEY` | *(ephemeral)* | PEM-encoded Ed25519 private key for attestation signing |
| `PAAC_ATTEST_PUBLIC_KEY` | *(derived)* | PEM-encoded Ed25519 public key for verification |
| `PAAC_CERT_KEY` | *(insecure default)* | HMAC key for PCM certificates, change before deployment |
| `PAAC_PCM_MODE` | `false` | Require a formal proof with every modification |
| `PAAC_PCM_LOG` | `pcm_audit.jsonl` | PCM certificate audit log path |
| `REDIS_HOST` | `redis` | Redis hostname (falls back to WAL if unavailable) |
| `PAAC_RATE_LIMIT` | `100` | Requests per minute per IP |
| `PAAC_MAX_LOOP_BOUND` | `10000` | Global loop bound cap (parse + Z3 + runtime) |
| `PAAC_WATCHDOG_TIMEOUT` | `60` | Watchdog stall timeout (seconds) |

---

## Operational Features

- **Watchdog**: two-thread design (liveness stamps every second, monitor checks every 5 s), no false alarms during idle
- **Circuit breaker**: 5 failures → OPEN, 60 s cooldown, automatic reset
- **WAL**: JSON-lines write-ahead log, atomic registry save, crash-resilient rollback
- **Redis fallback**: degrades to in-memory WAL with warning when Redis is unavailable
- **Rate limiting**: 100 req/min/IP (configurable)
- **Prometheus metrics**: counters, histograms, gauges for verifications, attestations, circuit breaker state
- **Constant-time response**: 200 ms floor on all verification responses (timing side-channel resistance, §3.5)
- **Z3 subprocess isolation**: each verification runs in a separate process with OS resource limits (1 GB AS, 5 s CPU on Linux), authenticated IPC token, 3-retry crash recovery

---

## Known Limitations

Ordered by how much each limits the safety claim.

- **Composition is unguarded.** Two confirmed decomposition witnesses, zero
  rejected. Call sites do not discharge callee preconditions (D-01) and replacing a
  function does not re-verify its callers (D-02). This is the binding limitation and
  everything below it is smaller. See [`docs/DECOMPOSITION.md`](docs/DECOMPOSITION.md)
- **The precondition still comes from the agent.** A satisfiability gate now rejects
  unsatisfiable ones, which closed a total verifier bypass (C-02). It does not change
  the fact that an obligation on the *caller* is supplied by the callee's author
- SIL does not support heap allocation, pointer aliasing, recursion, or concurrency,
  so it cannot express most real agent code. It is also why the decision procedure is
  tractable
- Loop bounds must be declared manually; no automated inference. BMC is sound only
  when the declared bound is at least the iterations needed. An under-bounded loop is
  classified unsafe, which is the safe direction
- Self-verification stubs are tautologies (see §4.1 above), so the bootstrap check
  establishes very little about the TCB
- The bounded-loop Z3 step is a certificate, not a proof; the DoS guarantee comes from
  the parser and the runtime
- `/attest/verify` proves consistency rather than provenance until an expected public
  key is pinned. PCM certificates are symmetric HMAC with an insecure default key
- The PCM proof checker has never been differentially tested against the Z3 verifier,
  which is the one test that would substantiate its soundness
- Compiler gaps: division by zero is undetected; a missing `return` is a warning and
  not even that for `-> bool` functions; string literals encode to unconstrained
  integers; array type and bounds are unchecked
- The enforced TCB excludes `sil_compiler.py`, and its protection is filesystem
  `chmod` only, a no-op off Linux
- With `PAAC_API_KEY` unset the API key check is skipped entirely and every endpoint
  is unauthenticated, including `/self-verify`, which triggers synchronous work
- The audit log path is resolved at import time against the working directory, so the
  record of accepted and rejected modifications lands wherever the process was started
- Postconditions are collected on `CodeModification` and never passed to the verifier
- Ed25519 provides integrity and non-repudiation; it does not provide zero-knowledge
  proofs (future: SNARKs)
- Z3 memory limits and TCB protection are enforced on Linux only. Every figure in this
  README was measured on Windows

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

Shashank Kumar, shashankchoudhary792@gmail.com  
Repository: https://github.com/ChronosResearch/paac
