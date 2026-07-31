# Provably Aligned Core (PAAC) v3.0

[![Paper](https://img.shields.io/badge/Paper-SSRN-blue)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6879218)
[![CI Pipeline](https://img.shields.io/badge/build-passing-brightgreen)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Overview
The Provably Aligned Core (PAAC) is an enterprise-grade formal verification framework for self-modifying code. Designed for high-assurance execution environments, the system intercepts code modifications dynamically and rigorously verifies them against a set of predefined safety axioms using an SMT (Satisfiability Modulo Theories) solver before allowing deployment.

### Key Features
* **Bounded Model Checking**: SMT-based AST constraint verification backed by Z3.
* **Deterministic Rollbacks**: Circuit breakers utilizing in-memory checkpoints with clustered Redis fallback.
* **Strict SIL Grammar**: Custom LL(1) bounded syntax restricting infinite loops and unchecked recursion.
* **Format Enforcer**: Heuristic-based constraint validation and code interception.
* **High-Throughput Caching**: Sub-millisecond verification skipping via AST structural hashing.

## Architecture & Verification Pipeline

PAAC guarantees that any proposed code modification respects predefined invariants before deployment. The architecture operates through a strict verification pipeline:

```text
+-------------------+        +---------------------+        +--------------------+
|                   |        |                     |        |                    |
| Code Modification | -----> |   Interceptor API   | -----> |    SIL Compiler    |
| (JSON Payload)    |        | (Sandbox / Routing) |        | (Syntax & Parsing) |
|                   |        |                     |        |                    |
+-------------------+        +---------------------+        +--------------------+
                                                                      |
                                                                      v
+-------------------+        +---------------------+        +--------------------+
|                   |        |                     |        |                    |
|   Axiom Database  | -----> |     Z3 Verifier     | <----- |  SIL AST (Target)  |
| (Safety Policies) |        | (BMC / SMT Solving) |        |                    |
|                   |        |                     |        |                    |
+-------------------+        +---------------------+        +--------------------+
                                        |
                                        v
                             +-----------------------+
                             |                       |
                             |   Apply Patch / Deny  |
                             |  (Rollback on Error)  |
                             |                       |
                             +-----------------------+
```

1. **SIL Compiler**: A strict, bounded grammar lexer, recursive descent parser, and rigorous type-checker.
2. **SIL Runtime**: A bounded interpreter for safe execution monitoring, catching memory and boundary violations immediately.
3. **Z3 Verifier**: A Bounded Model Checker (BMC) translating SIL AST and Axioms into Z3 Constraints, resolving state safely within a 5-second timeout.
4. **Code Monitor Layer**: Sandbox and interceptor pipeline for checking JSON modifications, simulating outcomes in a containerized environment.
5. **Format Enforcer**: Audit logging, rigid formatting enforcement, and heuristic text parsing.
6. **Watchdog**: Fail-safe circuit breaker backed by Redis checkpointing, handling self-healing and recovery logic.

## Requirements
- Python 3.12+ (Musl libc compatible via Alpine Linux in Production)
- Z3 Solver (`z3-solver>=5.0.0`)
- Redis (for Checkpointing)
- Docker & Docker Compose (for containerized deployment)

## Getting Started

### 1. Local Environment
```bash
python -m venv paac-venv
source paac-venv/bin/activate # (or paac-venv\Scripts\activate on Windows)
pip install -r requirements.txt
```

### 2. Running Tests
The framework is fully tested with unit and integration tests (26 passing).
```bash
PYTHONPATH=. pytest tests/
```

### 3. Docker Compose (Production Target)
We deploy PAAC on Alpine Linux with fail-safes pre-configured:
```bash
docker-compose -f docker-compose.yml up --build
```
This spins up a healthy Redis node alongside the PAAC API. The containers will automatically recover on failure using our Docker `on-failure` policies and periodic health check validations.

## Contributing
All submissions are subject to the same formal verification tests run via our CI pipelines. Pull requests modifying core invariants or the SIL compiler must attach benchmark proofs.
