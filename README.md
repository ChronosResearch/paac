# PAAC — Provably Aligned AI Core v5.0.0

PAAC is a formal verification wrapper for self-modifying AI code. It intercepts
proposed code changes, compiles them to the Safe Intermediate Language (SIL),
and verifies them against safety axioms using the Z3 SMT solver. Only
modifications that pass verification are accepted.

Paper: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6879218
License: MIT

---

## Status

**v5.0.0 — Research prototype – ready for evaluation.**

355 tests pass. Bandit: 0 HIGH/MEDIUM issues. Mypy: 0 errors.

> See [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for current limitations.

### Critical Fixes in v4.2.0 (carried forward)

| Issue | Severity | Fix |
|---|---|---|
| A-01 Loop soundness | CRITICAL | Under-bounded loops now correctly return SAT |
| A-02 Cache poisoning | HIGH | `__cache` name-mangled; read-only property |
| A-03 Timing attack on API key | HIGH | `secrets.compare_digest` |
| A-04 Fork-under-threads | HIGH | `set_start_method("spawn", force=True)` |
| A-05 target_functions not enforced | HIGH | `_get_applicable_axioms()` per call |

### Critical Fixes in v5.0.0

| Issue | Severity | Fix |
|---|---|---|
| C-01 Duplicate loop violation flag | CRITICAL | Removed duplicate `still_running` append in `StmtEncoder` |
| H-01 `eval()` in runtime monitor | HIGH | Replaced with SIL compiler+runtime evaluator |
| H-02 Duplicate parameter names | HIGH | Added compile-time duplicate-param detection |
| H-03 Missing return statement | HIGH | Added compile-time warning for missing `return` |
| H-04 Incomplete `.env.example` | HIGH | Added all security-relevant variables |

### Novel Features in v5.0.0

1. **Bootstrap Self-Verification** — Python-to-SIL translator; PAAC verifies its own TCB
2. **Cryptographic Attestation** — HMAC-SHA256 commitment with key rotation, thread-safe
3. **Multi-Agent Coordination** — Agent registry, crash recovery, conflict detection
4. **Proof-Carrying Modification (PCM)** — Agents submit formal proofs; checker runs in <10ms
5. **PCM Certificate System** — HMAC-SHA256 certificates for every accepted proof
6. **Axiom Coverage Metric** — Measures which axioms are actively evaluated per program
7. **CEGAR Axiom Repair** — Counterexample-guided automatic axiom strengthening
8. **Differential Verification** — Proves new versions are conservative extensions of old
9. **Axiom Mutation Testing** — Robustness score via mutation operators
10. **Probabilistic Verification** — Monte Carlo sampling over bounded domains
11. **Runtime Monitor** — Post-hoc axiom checking on SIL execution traces

---

## Architecture

```
Code Modification (+ optional PCM proof)
      |
      v
Code Monitor  <-- loads axioms, filters by target_functions (A-05)
      |
      +-- PCM mode? --> ProofChecker (pure Python, <10ms)
      |                      |
      |                      +-- ACCEPT --> generate PCMCertificate --> audit log
      |                      +-- REJECT --> rollback
      |
      +-- Standard mode --> SIL Compiler (lexer -> parser -> type checker -> CFG)
                                  |
                                  v
                            Z3 Verifier (SSA encoding -> loop unrolling -> BMC)
                                  |
                                  +-- UNSAT -> accepted, checkpoint saved
                                  +-- SAT   -> rejected, counterexample, rollback
                                  +-- FAIL  -> static fallback, circuit breaker
```

---

## Quick Start

### Docker (recommended)

```bash
docker build -t paac:v5.0.0 -f docker/Dockerfile .
docker run --rm --memory=2g -e PAAC_API_KEY=changeme paac:v5.0.0 \
  python3.11 -m pytest tests/ -v
```

### Docker Compose

```bash
cp .env.example .env
# Edit .env — set PAAC_API_KEY, PAAC_CERT_KEY, PAAC_ATTEST_KEY
docker-compose -f docker/docker-compose.yml up --build
```

### Local

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python3.11 -m pytest tests/ -v
```

---

## CLI

```bash
# Verify a SIL file
PYTHONPATH=. python3.11 -m src.cli verify examples/safe.sil

# Generate a PCM proof
PYTHONPATH=. python3.11 -m src.cli pcm-generate examples/safe.sil --out proof.json

# Verify a PCM proof (no Z3, <10ms)
PYTHONPATH=. python3.11 -m src.cli pcm-verify proof.json

# Submit a modification with proof (generates certificate)
PYTHONPATH=. python3.11 -m src.cli pcm-submit examples/safe.sil proof.json \
  --agent-id my-agent --cert-out cert.json

# Query the PCM audit log
PYTHONPATH=. python3.11 -m src.cli pcm-audit

# Measure axiom coverage
PYTHONPATH=. python3.11 -m src.cli coverage --path examples/

# Run CEGAR axiom repair
PYTHONPATH=. python3.11 -m src.cli repair --axiom-id no_negative_balance

# Differential verification
PYTHONPATH=. python3.11 -m src.cli diff-verify --old examples/v1.sil --new examples/v2.sil
```

---

## API

| Endpoint | Method | Description |
|---|---|---|
| `/verify` | POST | Submit a code modification for verification |
| `/health` | GET | Service health (healthy/degraded/unhealthy) |
| `/metrics` | GET | Prometheus metrics |
| `/self-verify` | POST | Bootstrap self-verification of the TCB |
| `/attest/{id}` | GET | Retrieve attestation record by modification ID |
| `/attest/verify` | POST | Verify an attestation commitment |
| `/agents` | GET | List registered agents and their status |

All `/verify` requests require `X-API-Key` header when `PAAC_API_KEY` is set.

---

## Configuration

All runtime configuration is via environment variables. See `.env.example`.

| Variable | Default | Description |
|---|---|---|
| `REDIS_HOST` | `redis` | Redis hostname |
| `PAAC_API_KEY` | `` | API key (empty = no auth) |
| `PAAC_CERT_KEY` | *(insecure default)* | HMAC key for PCM certificates |
| `PAAC_ATTEST_KEY` | *(ephemeral)* | HMAC key for attestation |
| `PAAC_PCM_MODE` | `false` | Require proofs with every modification |
| `PAAC_PCM_LOG` | `pcm_audit.jsonl` | PCM certificate audit log path |
| `PAAC_RATE_LIMIT` | `100` | Requests per minute per IP |
| `PAAC_MAX_LOOP_BOUND` | `10000` | Global loop bound cap |
| `PAAC_WATCHDOG_TIMEOUT` | `60` | Watchdog stall timeout (seconds) |

---

## SIL Language Reference

```
func function_name(param: type, ...) -> return_type {
    statements
}
```

Types: `int`, `bool`, `string`, `array`

Statements: assignment, `if`/`else`, `while (...) bound N { }`, `return`, `assert`

Restrictions:
- No recursion (direct or mutual) — detected at compile time
- No duplicate parameter names — detected at compile time
- All while loops require an explicit integer bound
- Global loop bound cap: 10,000 iterations
- Global instruction limit: 100,000 steps

---

## Running Tests

```bash
PYTHONPATH=. python3.11 -m pytest tests/ -v
```

Expected: **355 tests pass**.

---

## Known Limitations

See `KNOWN_ISSUES.md` for the full list.

- TCB protection is filesystem chmod only (not kernel read-only memory pages)
- Verification latency floor is 200 ms (constant-time padding)
- Loop bound must be manually specified (no automated inference)
- SIL cannot express heap, pointers, or concurrency

---

## Documentation

- [Deployment Guide](docs/DEPLOYMENT.md)
- [PCM Architecture](docs/PCM_ARCHITECTURE.md)
- [Proof Language Spec](docs/PROOF_LANGUAGE.md)
- [Production Runbook](docs/PRODUCTION_RUNBOOK.md)
- [Security Policy](SECURITY.md)
- [Audit Findings](AUDIT_FINDINGS.md)
