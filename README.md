# PAAC — Provably Aligned AI Core v5.0.0

PAAC is a formal verification wrapper for self-modifying AI code. It intercepts
proposed code changes, compiles them to the Safe Intermediate Language (SIL),
and verifies them against safety axioms using the Z3 SMT solver. Only
modifications that pass verification are accepted.

Paper: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6879218
License: MIT

---

## Status

**v5.0.0 — Production-ready. All critical issues resolved. Three novel features integrated.**

260 tests pass. Bandit: 0 HIGH issues. Mypy: 0 errors.

### Critical Fixes in v4.2.0 (carried forward)

| Issue | Severity | Fix |
|---|---|---|
| A-01 Loop soundness | CRITICAL | Under-bounded loops now correctly return SAT |
| A-02 Cache poisoning | HIGH | `__cache` name-mangled; read-only property |
| A-03 Timing attack on API key | HIGH | `secrets.compare_digest` |
| A-04 Fork-under-threads | HIGH | `set_start_method("spawn", force=True)` |
| A-05 target_functions not enforced | HIGH | `_get_applicable_axioms()` per call |

### Novel Features in v5.0.0 (EPFL Research Extensions)

1. **Bootstrap Self-Verification** — Genuine Python-to-SIL translator; PAAC verifies its own TCB
2. **Cryptographic Attestation** — HMAC-SHA256 commitment with key rotation, thread-safe, audit metrics
3. **Multi-Agent Coordination** — Agent registry, crash recovery, conflict detection, sequential queue
4. **Probabilistic Verification** — Monte Carlo sampling over bounded domains
5. **CTVP** — Cross-Trace Semantic Verification Protocol (backdoor detection)
6. **Axiom Evolution** — Conservative axiom extension with Z3 consistency check
7. **Runtime Monitor** — Post-hoc axiom checking on SIL execution traces

---

## Architecture

```
Code Modification
      |
      v
Code Monitor  <-- loads axioms, filters by target_functions (A-05)
      |
      v
SIL Compiler  (lexer -> parser -> type checker -> CFG)
      |
      v
Z3 Verifier   (SSA encoding -> loop unrolling -> BMC query)
      |         A-01: post-unroll soundness check
      |         A-02: name-mangled cache, read-only property
      |
      +-- UNSAT -> modification accepted, checkpoint saved
      +-- SAT   -> modification rejected, counterexample returned, rollback applied
      +-- FAIL  -> static fallback analyzer, circuit breaker records failure
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
# Edit .env — set PAAC_API_KEY
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
The key comparison uses `secrets.compare_digest` (constant-time, A-03 fix).

---

## Configuration

All runtime configuration is via environment variables. See `.env.example`.

| Variable | Default | Description |
|---|---|---|
| `REDIS_HOST` | `redis` | Redis hostname |
| `REDIS_PORT` | `6379` | Redis port |
| `AXIOM_PATH` | `config/axioms.yaml` | Axiom file path |
| `PAAC_API_KEY` | `` | API key (empty = no auth) |
| `PAAC_RATE_LIMIT` | `100` | Requests per minute per IP |
| `PAAC_WAL_PATH` | `checkpoints.wal` | WAL file path |
| `PAAC_REGISTRY_PATH` | `live_registry.json` | Registry persistence path |
| `PAAC_MAX_LOOP_BOUND` | `10000` | Global loop bound cap |
| `PAAC_MAX_INSTRUCTIONS` | `100000` | Global instruction limit |
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
- No recursion (direct or mutual)
- All while loops require an explicit integer bound
- Global loop bound cap: 10,000 iterations
- Global instruction limit: 100,000 steps
- Loop bound must be sufficient for all inputs (A-01: under-bounded loops are SAT)

---

## Running Tests

```bash
PYTHONPATH=. python3.11 -m pytest tests/ -v
```

Expected: 260 tests pass.

---

## Known Limitations

See `KNOWN_ISSUES.md` and the paper corrections in `FINAL_MERGE_REPORT.md`.

- TCB protection is filesystem chmod only (not kernel read-only memory pages)
- Verification latency floor is 200 ms (constant-time padding); not <120 ms
- TCB line count is ~2,123 lines across 6 core files (paper claimed ~500)
- RLIMIT_AS not enforced on macOS — use Docker `--memory=2g`

---

## Documentation

- [Deployment Guide](docs/DEPLOYMENT.md)
- [Production Runbook](docs/PRODUCTION_RUNBOOK.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Performance](docs/PERFORMANCE.md)
- [Monitoring](docs/MONITORING.md)
- [Security Policy](SECURITY.md)
- [SIL Architecture](docs/SIL_ARCHITECTURE.md)
- [Advanced Features Report](ADVANCED_FEATURES_REPORT.md)
- [Final Merge Report](FINAL_MERGE_REPORT.md)
