# PAAC — Provably Aligned AI Core v4.1

PAAC is a formal verification wrapper for self-modifying AI code. It intercepts
proposed code changes, compiles them to the Safe Intermediate Language (SIL),
and verifies them against safety axioms using the Z3 SMT solver. Only
modifications that pass verification are accepted.

Paper: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6879218
License: MIT

---

## Status

**v4.1 — Production-ready on Linux with Docker.**

All 70+ tests pass. Bandit: 0 issues. Mypy: 0 errors.

What works:
- SIL compiler: lexer, parser, type checker, call-graph recursion detection
- Z3 verifier: real BMC pipeline with SSA encoding, loop unrolling, phi-node merges
- Safety axiom loading from YAML with real conditions (not vacuous `true`)
- Constant-time verification padding (200 ms, configurable)
- Checkpoint and rollback with WAL persistence
- Z3 subprocess isolation with OS-level RLIMIT_AS/RLIMIT_CPU (Linux)
- Circuit breaker (5 failures → OPEN, 60 s cooldown, HALF_OPEN probe)
- Fallback static analyzer when Z3 is unavailable
- FastAPI with /verify, /health, /metrics endpoints
- Prometheus metrics: counters, histograms, gauges
- Rate limiting (100 req/min per IP), API key auth
- Non-root Docker container with HEALTHCHECK
- Structured JSON logging via loguru

Known limitations:
- RLIMIT_AS not enforced on macOS — use Docker `--memory=2g` instead
- TCB line count is ~1,600 lines across 6 core files (paper claimed ~500)
- The paper's <120 ms verification claim is not met for complex programs;
  typical latency is 200–800 ms including constant-time padding

---

## Architecture

```
Code Modification
      |
      v
Code Monitor  <-- loads axioms from config/axioms.yaml
      |
      v
SIL Compiler  (lexer -> parser -> type checker -> CFG)
      |
      v
Z3 Verifier   (SSA encoding -> loop unrolling -> BMC query)
      |
      +-- UNSAT -> modification accepted, checkpoint saved
      +-- SAT   -> modification rejected, counterexample returned, rollback applied
      +-- FAIL  -> static fallback analyzer, circuit breaker records failure
```

---

## Quick Start

### Docker (recommended)

```bash
docker build -t paac:production -f docker/Dockerfile .
docker run --rm --memory=2g -e AXIOM_PATH=config/axioms.yaml \
  -e PAAC_API_KEY=changeme paac:production \
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

All `/verify` requests require `X-API-Key` header when `PAAC_API_KEY` is set.

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

---

## Running Tests

```bash
PYTHONPATH=. python3.11 -m pytest tests/ -v
```

Expected: 70+ tests pass.

---

## Documentation

- [Deployment Guide](docs/DEPLOYMENT.md)
- [Production Runbook](docs/PRODUCTION_RUNBOOK.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Performance](docs/PERFORMANCE.md)
- [Monitoring](docs/MONITORING.md)
- [Security Policy](SECURITY.md)
- [SIL Architecture](docs/SIL_ARCHITECTURE.md)
