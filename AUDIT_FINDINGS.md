# PAAC Audit Findings

**Date:** 2026-08-03
**Version:** v5.0.0
**Auditor:** Senior Release Engineer
**Scope:** Full codebase — src/, tests/, config/, docs/, docker/

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Total files audited | 52 |
| Critical issues | 1 |
| High issues | 4 |
| Medium issues | 7 |
| Low issues | 11 |
| Overall verdict | **CONDITIONAL PASS** — all critical/high issues fixed in Phase 2 |

---

## Critical Issues (Must Fix)

| ID | File | Issue | Severity | Fix |
|----|------|-------|----------|-----|
| C-01 | `src/core/verifier.py` | `StmtEncoder._encode_stmt` adds the post-loop `still_running` violation flag **twice** (lines 218–228 are a verbatim duplicate). This causes Z3 to receive a redundant `Or(...)` clause, doubling the violation weight and potentially producing spurious SAT results for loop-heavy programs. | CRITICAL | Remove the duplicate block (second `still_running` append). |

---

## High Issues

| ID | File | Issue | Severity | Fix |
|----|------|-------|----------|-----|
| H-01 | `src/core/runtime_monitor.py:103` | `eval(py_cond, {"__builtins__": {}}, dict(env))` — restricted `eval` with user-controlled `condition` string. Bandit B307. Even with empty builtins, crafted conditions can raise or leak. | HIGH | Replace with a safe expression evaluator that walks the SIL AST directly instead of calling `eval`. |
| H-02 | `src/core/sil_compiler.py` | `SILTypeChecker` does not detect duplicate parameter names (KI-002). `func f(x: int, x: int)` compiles silently; the second `x` shadows the first in the SSA environment, producing unsound verification results. | HIGH | Add a duplicate-parameter check in `_check_function`. |
| H-03 | `src/core/sil_compiler.py` | `SILTypeChecker` does not require a `return` statement (KI-003). A function that falls off the end returns `None` at runtime but the verifier encodes no return value, silently missing post-condition checks. | HIGH | Warn (not error) when no `ReturnStmtNode` is found in a function body. |
| H-04 | `.env.example` | Missing critical environment variables: `PAAC_API_KEY`, `PAAC_CERT_KEY`, `PAAC_PCM_LOG`, `PAAC_ATTEST_KEY`. Operators deploying from the example file will run with empty API key (no auth) and default HMAC keys. | HIGH | Add all security-relevant variables with placeholder values and comments. |

---

## Medium Issues

| ID | File | Issue | Severity | Fix |
|----|------|-------|----------|-----|
| M-01 | `src/pcm/certificate.py` | `import re` placed at the bottom of the file (line 290) after all code. Violates PEP 8 and causes confusion about module-level state. | MEDIUM | Move `import re` to the top of the file. |
| M-02 | `src/core/sil_runtime.py:44` | `import src.core.sil_runtime as _rt` inside `_tick()` — a module self-import on every tick call. Adds overhead and is a code smell. | MEDIUM | Read `MAX_INSTRUCTIONS` at module level or pass it as a parameter. |
| M-03 | `src/cegar/repair.py` | Unused imports: `ProgramNode`, `CounterExample`. Ruff F401. | MEDIUM | Remove unused imports. |
| M-04 | `src/coverage/axiom_coverage.py` | Unused import: `ExprEncoder`. Ruff F401. | MEDIUM | Remove unused import. |
| M-05 | `src/diffverify/diff_verifier.py` | Unused imports: `field`, `ExprEncoder`, `VerificationError`. Ruff F401. | MEDIUM | Remove unused imports. |
| M-06 | `src/pcm/proof_generator.py` | Unused imports: `field`, `ProgramNode`. Ruff F401. | MEDIUM | Remove unused imports. |
| M-07 | `src/mutation/report.py` | Unused imports: `asdict`, `MutantResult`. Ruff F401. | MEDIUM | Remove unused imports. |

---

## Low Issues

| ID | File | Issue | Severity | Fix |
|----|------|-------|----------|-----|
| L-01 | `src/cli.py` | `all_mods` variable assigned but never used (Ruff F841). | LOW | Remove unused variable. |
| L-02 | `src/core/self_verify.py` | `pad` variable assigned but never used in `_translate_stmt` (Ruff F841). `Any` imported but unused (Ruff F401). | LOW | Remove unused variable and import. |
| L-03 | `src/pcm/proof_checker.py` | `step_covered` variable assigned but never used in `Conclude` handler (Ruff F841). | LOW | Remove unused variable. |
| L-04 | `src/mutation/axiom_mutator.py` | `field` imported but unused (Ruff F401). | LOW | Remove unused import. |
| L-05 | `src/certificates/proof_cert.py` | `asdict`, `ExprEncoder` imported but unused (Ruff F401). | LOW | Remove unused imports. |
| L-06 | `docs/DEPLOYMENT.md` | Version header says "v4.2.0" — not updated for v5.0.0. Missing PCM configuration section. | LOW | Update version and add PCM/certificate env vars. |
| L-07 | `README.md` | Test count says "260 tests pass" — actual count is 355. | LOW | Update to reflect actual count. |
| L-08 | `config/default.yaml` | No PCM configuration section (`pcm_mode`, `pcm_audit_log`, `paac_cert_key`). | LOW | Add PCM config block. |
| L-09 | `src/core/verifier.py` | `_loop_exit_path` field on `StmtEncoder` is set but the `encode_stmts` loop only uses it via `current_path` reassignment — the logic is correct but the field name is misleading. | LOW | Rename to `_post_loop_path` for clarity. |
| L-10 | `tests/test_v5_features.py` | Unused imports: `hashlib`, `Axiom`, `SELF_AXIOMS`, `DiffStatus`, `run_axiom_mutation`. Ruff F401/I001. | LOW | Remove unused imports. |
| L-11 | `tests/test_mutation_testing.py` | Unused imports: `MutatedAxiom`, `MutantResult`. Ruff F401. | LOW | Remove unused imports. |

---

## Informational

| ID | File | Note |
|----|------|------|
| I-01 | `src/core/verifier.py` | `CONSTANT_VERIFICATION_TIME_S = 0.200` is hardcoded. The config file has `constant_verification_time_padding_s` but it is never read. Acceptable for now; document the discrepancy. |
| I-02 | `src/main.py` | `_rate_counters` is an unbounded `defaultdict` — under sustained load from many unique IPs it will grow without bound. Acceptable for a research prototype; add a note. |
| I-03 | `src/core/failsafe.py` | `rollback()` logs intent but does not actually replay history. Documented as future work. |
| I-04 | `docker/Dockerfile` | `pip install --only-binary=:all: z3-solver` then `pip install -r requirements.txt` — z3-solver is installed twice. Minor inefficiency. |
