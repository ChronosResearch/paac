# PAAC — Provably Aligned AI Core v6.1

**Status:** Research prototype — ready for evaluation.

PAAC is a formal verification wrapper for self-modifying AI agents. It intercepts
proposed code modifications, compiles them to the Safe Intermediate Language (SIL),
and verifies them against safety axioms using the Z3 SMT solver. Only modifications
that pass verification are accepted.

Paper: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6879218
License: All rights reserved — Shashank Kumar

---

## Overview

PAAC sits between an AI agent and its own codebase. Every proposed modification is
compiled to SIL and checked against a set of safety axioms before it is applied.
Modifications that violate an axiom are rejected with a counterexample. Accepted
modifications receive a cryptographic certificate and are recorded in an audit log.

---

## Features

**Core**
- SSA-encoded bounded model checking (BMC) with Z3
- Safe Intermediate Language (SIL) — lexer, parser, type checker, CFG builder
- Compile-time checks: no recursion, no duplicate parameters, bounded loops
- Constant-time verification response (200 ms floor — intentional, not a performance claim)
- Runtime monitor — post-hoc axiom checking on SIL execution traces
- Bootstrap self-verification — PAAC verifies its own trusted computing base

**Novel**
- Proof-Carrying Modification (PCM) — agent submits a formal proof; PAAC checks the proof, not the code, in under 10 ms
- Cryptographic certificates — every accepted modification is HMAC-SHA256 signed and auditable
- Axiom mutation testing — systematic mutation operators; 100% robustness score on the default axiom set
- Axiom coverage metric — quantifies which axioms are exercised by a given SIL program
- CEGAR axiom repair — counterexample-guided automatic axiom strengthening
- Differential verification — proves a new code version is a conservative extension of the old one
- Probabilistic verification — Monte Carlo sampling over bounded domains

**Operational**
- Watchdog, circuit breaker, write-ahead log (WAL), Redis fallback
- Cryptographic attestation with HMAC-SHA256 and key rotation
- Multi-agent registry with crash recovery and conflict detection
- Rate limiting, API key authentication, Prometheus metrics

---

## Quick Start

### Docker (recommended)

```bash
docker build -t paac:v6.1 -f docker/Dockerfile .
docker run --rm --memory=2g -e PAAC_API_KEY=changeme paac:v6.1 \
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

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/verify` | POST | Submit a code modification for verification |
| `/health` | GET | Service health (healthy / degraded / unhealthy) |
| `/metrics` | GET | Prometheus metrics |
| `/self-verify` | POST | Bootstrap self-verification of the TCB |
| `/attest/{id}` | GET | Retrieve attestation record by modification ID |
| `/attest/verify` | POST | Verify an attestation commitment |
| `/agents` | GET | List registered agents and their status |

All `/verify` requests require the `X-API-Key` header when `PAAC_API_KEY` is set.

---

## Configuration

All runtime configuration is via environment variables. See `.env.example` for
generation instructions.

| Variable | Default | Description |
|---|---|---|
| `PAAC_API_KEY` | *(empty — no auth)* | API authentication key |
| `PAAC_CERT_KEY` | *(insecure default)* | HMAC key for PCM certificates — must be changed |
| `PAAC_ATTEST_KEY` | *(ephemeral)* | HMAC key for attestation records |
| `PAAC_PCM_MODE` | `false` | Require a proof with every modification |
| `PAAC_PCM_LOG` | `pcm_audit.jsonl` | PCM certificate audit log path |
| `REDIS_HOST` | `redis` | Redis hostname |
| `PAAC_RATE_LIMIT` | `100` | Requests per minute per IP |
| `PAAC_MAX_LOOP_BOUND` | `10000` | Global loop unrolling cap |
| `PAAC_WATCHDOG_TIMEOUT` | `60` | Watchdog stall timeout (seconds) |

---

## Running Tests

```bash
PYTHONPATH=. python3.11 -m pytest tests/ -v
```

Expected: **355 tests pass.**

---

## Known Limitations

See [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for the full list.

- Verification response floor is 200 ms (constant-time padding — by design)
- Loop bounds must be specified manually; no automated inference
- SIL does not support heap allocation, pointers, or concurrency
- TCB protection is filesystem chmod only, not kernel-level memory protection
- Z3 memory limits are not enforced on macOS (Linux only)
- Default HMAC keys are insecure — must be replaced before any deployment

---

## Documentation

- [Deployment Guide](docs/DEPLOYMENT.md)
- [PCM Architecture](docs/PCM_ARCHITECTURE.md)
- [Proof Language Spec](docs/PROOF_LANGUAGE.md)
- [Production Runbook](docs/PRODUCTION_RUNBOOK.md)
- [Security Policy](SECURITY.md)
- [Audit Findings](AUDIT_FINDINGS.md)

---

## License

Copyright (c) 2026 Shashank Kumar. All rights reserved.

This software is proprietary and confidential. No license is granted to any
person or entity to use, copy, modify, merge, publish, distribute, sublicense,
or sell copies of the software.

---

## Contact

Shashank Kumar
