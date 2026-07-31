# Provably Aligned Core (PAAC) v3.0

## Overview
The Provably Aligned Core (PAAC) is a formal verification framework for self-modifying code. The system intercepts code modifications and verifies them against safety axioms using an SMT solver.

## Architecture

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

1. **SIL Compiler**: A strict, bounded grammar lexer/parser/type-checker.
2. **SIL Runtime**: A bounded interpreter for safe execution monitoring.
3. **Z3 Verifier**: A Bounded Model Checker (BMC) translating SIL AST and Axioms into Z3 Constraints.
4. **Code Monitor Layer**: Sandbox and interceptor pipeline for checking modifications.
5. **Truthfulness Enforcer**: Audit logging and rigorous format checking.
6. **Watchdog**: Fail-safe circuit breaker backed by Redis checkpointing.

## Requirements
- Python 3.12+
- Z3 Solver (`z3-solver`)
- Redis (for Checkpointing)
- Docker (for deployment)

## Getting Started

### 1. Local Environment
```bash
python -m venv paac-venv
source paac-venv/bin/activate # (or paac-venv\Scripts\activate on Windows)
pip install -r requirements.txt
```

### 2. Running Tests
```bash
pytest tests/
```

### 3. Docker Compose (Production Target)
```bash
docker-compose -f docker/docker-compose.yml up --build
```
