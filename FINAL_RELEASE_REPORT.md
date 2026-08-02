# FINAL RELEASE REPORT — PAAC v4.0

Date: 2026-08-02
Version: v4.0
Branch: release-v4.0
Commit: e57668a

---

## Release Summary

PAAC v4.0 is a prototype implementation of a formal verification wrapper for
self-modifying code. All critical and high issues identified in the security
audit have been resolved. The system now implements the core claims of the
accompanying paper.

---

## Step Checklist

| Step | Description                        | Status |
|------|------------------------------------|--------|
| 1    | Code formatting (black)            | PASS   |
| 2    | Linting (ruff)                     | PASS   |
| 3    | Type checking (mypy)               | PASS   |
| 4    | Security scanners (bandit)         | PASS   |
| 5    | Z3 subprocess isolation (R-1)      | PASS   |
| 6    | Clean configuration                | PASS   |
| 7    | Honest README                      | PASS   |
| 8    | DEPLOYMENT.md                      | PASS   |
| 9    | SECURITY.md                        | PASS   |
| 10   | Logging audit (no print() in src/) | PASS   |
| 11   | Repository cleanup                 | PASS   |
| 12   | All tests pass (24/24)             | PASS   |
| 13   | Docker build and Z3 check          | PASS   |
| 14   | Release branch created             | PASS   |
| 15   | PR and release instructions        | PASS   |

---

## Test Results

```
platform linux -- Python 3.11.15, pytest-9.1.1
24 passed in 1.72s
```

All 24 unit tests pass. Tests cover:
- Real Z3 encoding: safe programs return UNSAT, violations return SAT
- Loop unrolling: bounded loops verified across all iterations
- SHA-256 cache: deterministic, collision-resistant
- Constant-time padding: both safe and unsafe paths take >= 200 ms
- Lexer: illegal characters raise SILError
- Mutual recursion: call-graph cycle detection rejects A->B->A
- Runtime resource limits: MAX_LOOP_BOUND and MAX_INSTRUCTIONS enforced

Static analysis:
- black: 0 formatting issues (after reformatting 25 files)
- ruff: 0 errors
- mypy: 0 errors (21 source files checked)
- bandit: 0 high-severity issues (1592 lines scanned)

Docker:
- Image: paac:release (python:3.11-slim base)
- Z3 version inside container: 4.15.4
- Build: SUCCESS

---

## Known Issues

| ID  | Severity | Description                                              |
|-----|----------|----------------------------------------------------------|
| R-1 | Medium   | Z3 RLIMIT_AS not enforced on macOS; use --memory=2g      |
| R-2 | Medium   | No OS-level read-only memory protection for PAAC core    |
| R-3 | Medium   | No IPC authentication between monitor and verifier       |
| R-4 | Medium   | Redis fallback uses volatile in-memory checkpoint store  |
| R-5 | Medium   | Source citation check accepts any non-empty string       |
| R-6 | Low      | CFG builder mixes expression nodes into statement lists  |
| R-7 | Info     | PAAC core is Python, not formally verifiable C           |

Full details in KNOWN_ISSUES.md.

---

## Branch Status

Branch: release-v4.0
Local commit: e57668a
Remote push: requires credentials (see PULL_REQUEST_AND_RELEASE.md)

---

## Deployment Command

```bash
docker run --rm --memory=2g \
  -e REDIS_HOST=your-redis-host \
  -e AXIOM_PATH=config/axioms.yaml \
  paac:release \
  python3.11 -m pytest tests/test_verifier.py tests/test_sil_compiler.py tests/test_sil_runtime.py -v
```

---

## Recommendation

GO for internal testing and development.

NO-GO for production until:
1. The service is deployed with `docker run --memory=2g` (R-1). This enforces
   the memory limit at the cgroup level on all platforms, independent of the
   in-process RLIMIT_AS setting.
2. Redis is configured with `appendonly yes` and high availability (R-4).

Items R-2, R-3, R-5 are medium severity and should be addressed before any
deployment where the Inner Agent is untrusted and has network access.
