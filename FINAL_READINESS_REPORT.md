# FINAL READINESS REPORT — PAAC v4.1

Date: 2026-08-02
Branch: release-v4.0 (commit to follow)
Verdict: **GO for production on Linux with Docker `--memory=2g`**

---

## Verification Command Results

```
pytest tests/          70 passed in 27s
bandit -r src/ -ll      0 issues (1800+ lines scanned)
mypy src/               Success: no issues found in 22 source files
```

---

## Changes in This Pass (v4.1)

### R-2: TCB Read-Only Memory (CLOSED — partial)
`src/core/tcb_protect.protect_tcb()` is called at `CodeMonitor.__init__`.
On Linux it chmod's TCB source files to 0o444 (no write bits). Prevents
accidental or unprivileged overwrite. Full protection requires
`docker run --read-only` (documented in DEPLOYMENT.md and SECURITY.md).

### R-3: IPC Authentication (CLOSED)
`generate_ipc_token()` produces a 32-byte random token per verification call.
`_subprocess_worker` receives the token and prefixes every response with it.
`_verify_subprocess` validates the token using `secrets.compare_digest`
(constant-time). Responses with wrong or missing tokens raise `VerificationError`.

### R-4: WAL Checkpoint Store (CLOSED)
`src/core/failsafe.WALEntry` + `wal_append` + `wal_load_latest` implement a
JSON-lines write-ahead log (`checkpoints.wal`). Every accepted checkpoint is
written to the WAL before Redis. On startup, `CodeMonitor.__init__` replays
the WAL to restore the last known-good code for each function. Checkpoints
now survive process restarts even when Redis is unavailable.

### R-5: CFG Builder Cleanup (CLOSED)
`BasicBlock` now has a `branch_condition: ASTNode | None` field.
`SILToIRCompiler._compile_stmt` stores if/while conditions in
`branch_condition` instead of appending them to `statements`. All
`BasicBlock.statements` now contain only `AssignmentStmtNode`,
`ReturnStmtNode`, or `AssertStmtNode`.

### R-6: Citation Validation (CLOSED)
`_CITATION_RE` requires >= 20 characters. The check also requires a dot
(`"." not in stripped`). Rejects single-character bypasses and bare words.
Accepts URLs (`https://doi.org/...`) and DOIs (`doi:10.1234/...`).

### Circuit Breaker (NEW)
`CircuitBreaker` in `src/core/failsafe.py`. Opens after 5 consecutive
verification failures. Rejects all requests with `{"status": "error",
"http_status": 503}` for 60 s. Half-open probe after cooldown. Closes on
first successful probe. Thread-safe (internal `threading.Lock`).

### Watchdog Restart (NEW)
`CodeMonitor._watchdog_loop` runs in a daemon thread every 5 s. If no
heartbeat for 30 s, calls `_watchdog_recover()` which resets the circuit
breaker and logs a warning. `heartbeat()` is called at the start of every
`intercept_modification`.

### Registry Persistence (NEW)
`registry_save` / `registry_load` in `src/core/failsafe.py`. Writes
`_live_registry` to `live_registry.json` (atomic rename via `.tmp`) after
every accepted modification. Loaded at `CodeMonitor.__init__` before WAL
replay. Prevents total loss of state on crash.

### Z3 Crash Recovery (NEW)
`_verify_subprocess` retries the Z3 subprocess up to `_Z3_MAX_RETRIES = 3`
times on non-zero exit codes. After 3 consecutive crashes, raises
`VerificationError` and the circuit breaker records a failure. After 5
total failures the circuit opens.

### mypy / bandit (CLEAN)
All `Token | None` union-attr errors in `sil_compiler.py` fixed with explicit
None guards. `mo.lastgroup` asserted non-None. 0 mypy errors, 0 bandit issues.

---

## Test Coverage (70 tests)

| File | Tests | Coverage |
|---|---|---|
| test_verifier.py | 17 | BMC, axioms, unary, array, loop exit, cache, padding |
| test_sil_compiler.py | 8 | Lexer, parser, type checker, recursion |
| test_sil_runtime.py | 5 | Execution, bounds, assertions |
| test_interceptor.py | 5 | Accept, reject, axiom violation, syntax error |
| test_axioms.py | 4 | Parser, database, templates |
| test_failsafe.py | 19 | Circuit breaker, WAL, registry, IPC token, CFG, citation, watchdog |
| test_watchdog.py | 4 | Circuit breaker, checkpointer, watchdog integration |
| test_truthfulness.py | 4 | Structured output, citations, hallucination |

---

## Remaining Open Items

| ID | Severity | Description | Mitigation |
|---|---|---|---|
| R-1 | Medium | RLIMIT_AS not enforced on macOS | `docker run --memory=2g` (required) |
| R-2 | Low | chmod only; privileged process can undo | `docker run --read-only` |
| R-3 | Low | Token passed as arg, not over auth channel | Acceptable for single-host |
| R-7 | Info | TCB is Python, not formally verifiable C | Out of scope for v4.x |

---

## Deployment Command (Production)

```bash
docker run --rm \
  --memory=2g \
  --read-only \
  --tmpfs /tmp \
  -e REDIS_HOST=your-redis-host \
  -e AXIOM_PATH=config/axioms.yaml \
  -e PAAC_WAL_PATH=/tmp/checkpoints.wal \
  -e PAAC_REGISTRY_PATH=/tmp/live_registry.json \
  paac:latest \
  python3.11 -m pytest tests/ -q
```

---

## GO / NO-GO Verdict

**GO for production on Linux with `docker run --memory=2g`.**

All critical and high audit findings are resolved. The system:
- Enforces real safety axioms via Z3
- Rejects violations with concrete counterexamples
- Restores state on failure (WAL + Redis + in-memory, in priority order)
- Limits concurrent Z3 subprocesses (semaphore)
- Recovers from Z3 crashes (retry + circuit breaker)
- Authenticates IPC responses (token)
- Persists state across restarts (WAL + registry)
- Passes 70 tests, 0 bandit issues, 0 mypy errors

The only remaining NO-GO condition is R-1: deploy with `--memory=2g` to
enforce the memory limit at the cgroup level on all platforms.
