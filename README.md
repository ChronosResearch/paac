# Provably Aligned AI Core (PAAC) v3.0

## Overview
The Provably Aligned AI Core (PAAC) is a deterministic safety wrapper designed for self-improving artificial intelligence agents. It mathematically guarantees that all agent-proposed code modifications preserve a predefined set of safety properties using SMT-based formal verification (Z3).

## Architecture
PAAC intercepts code modifications in a Safe Intermediate Language (SIL). 
The engine consists of:
1. **SIL Compiler**: A strict, bounded grammar lexer/parser/type-checker.
2. **SIL Runtime**: A bounded interpreter for safe execution monitoring.
3. **Z3 Verifier**: A Bounded Model Checker (BMC) translating SIL AST + Axioms into Z3 Constraints.
4. **Code Monitor Layer**: Sandbox and interceptor pipeline for checking modifications.
5. **Truthfulness Enforcer**: Heuristic-based hallucination detection and audit logging.
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

## Security
For any potential security issues in the Z3 memory isolation or sandbox escapes, please refer to the `GRANT_SUBMISSION.md` document for theoretical limitations.
