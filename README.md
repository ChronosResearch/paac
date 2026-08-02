# PAAC — Provably Aligned AI Core

PAAC is a prototype implementation of a formal verification wrapper for
self-modifying code. It intercepts proposed code changes, compiles them to a
restricted intermediate language, and verifies them against a set of safety
axioms using the Z3 SMT solver. Only modifications that pass verification are
accepted.

This is a research prototype. It is not production-ready. See the status
section below for what works and what does not.

Paper: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6879218
License: MIT

---

## Status

The system is CONDITIONALLY GO for development and internal testing.
It is NOT production-ready until Z3 subprocess isolation is hardened with
container-level memory limits. See DEPLOYMENT.md for details.

What works:
- SIL compiler: lexer, parser, type checker, call-graph recursion detection
- Z3 verifier: real BMC pipeline with SSA encoding and loop unrolling
- Safety axiom loading from YAML
- Constant-time verification padding (200 ms)
- Checkpoint and rollback
- Subprocess isolation for Z3 with OS-level RLIMIT_AS and RLIMIT_CPU

What is not implemented:
- OS-level read-only memory protection for the PAAC core
- IPC authentication between the monitor and verifier
- Formal verification of the PAAC core itself
- Array bounds checking in the type system
- Bounded recursion support in SIL

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
```

The Inner Agent submits code in the Safe Intermediate Language (SIL). SIL is
a restricted language with bounded integers, booleans, bounded while loops,
no recursion, and no dynamic memory allocation. These restrictions make the
verification problem decidable.

---

## Safety Axiom Categories

Axioms are defined in `config/axioms.yaml` in three categories:

- **Behavioral**: constraints on what the code may output or call
  (e.g., no network access, no calls to exit())
- **Integrity**: constraints preventing modification of the PAAC core itself
- **Resource**: bounds on memory and execution time

Axiom conditions are written as SIL boolean expressions and compiled to Z3
constraints at verification time.

---

## Quick Start

### Docker (recommended)

```bash
docker run --rm \
  -e REDIS_HOST=localhost \
  -e AXIOM_PATH=config/axioms.yaml \
  --memory=2g \
  paac:latest \
  python3.11 -m pytest tests/
```

### Docker Compose

```bash
cp .env.example .env
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

## Configuration

All runtime configuration is via environment variables. See `.env.example`.

| Variable | Default | Description |
|---|---|---|
| `REDIS_HOST` | `redis` | Redis hostname for checkpoint storage |
| `REDIS_PORT` | `6379` | Redis port |
| `AXIOM_PATH` | `config/axioms.yaml` | Path to axiom definition file |
| `VERIFICATION_TIMEOUT_MS` | `5000` | Z3 solver timeout per query |

---

## SIL Language Reference

SIL programs consist of one or more function definitions:

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
- The runtime enforces a global loop bound cap of 10,000 iterations
- The runtime enforces a global instruction limit of 100,000 steps

Example:

```
func clamp(x: int, lo: int, hi: int) -> int {
    if x < lo {
        return lo;
    }
    if x > hi {
        return hi;
    }
    return x;
}
```

---

## Running Tests

```bash
PYTHONPATH=. python3.11 -m pytest tests/ -v
```

Expected: 24 tests pass.

---

## Known Limitations

See SECURITY.md for the full threat model and guarantee boundaries.
See DEPLOYMENT.md for deployment prerequisites.
See KNOWN_ISSUES.md for the current issue list with severities.

The most significant open issue is R-1: Z3 runs in a subprocess with
RLIMIT_AS and RLIMIT_CPU set, but these limits are not enforced on all
platforms (macOS restricts RLIMIT_AS). For production deployments, run the
PAAC service inside a container with `--memory=2g` set at the Docker level.
