# PAAC Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| v4.1 (release-v4.0 branch) | ✅ Active |
| v4.0 | ✅ Security fixes only |
| < v4.0 | ❌ End of life |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email: security@chronosresearch.example.com

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (optional)

We will acknowledge within 48 hours and provide a fix timeline within 7 days.

---

## Threat Model

### What PAAC protects against

1. **Unsafe code modifications**: SIL programs that violate safety axioms are
   rejected before execution. The Z3 BMC pipeline provides formal guarantees
   within the bounds of the SIL language.

2. **Unbounded computation**: All loops require explicit bounds. The runtime
   enforces a global instruction limit (100,000 steps) and loop bound cap
   (10,000 iterations).

3. **Recursion**: Direct and mutual recursion are rejected at compile time via
   call-graph cycle detection.

4. **Resource exhaustion**: Z3 runs in a subprocess with RLIMIT_AS (1 GB) and
   RLIMIT_CPU (5 s) on Linux. Docker `--memory=2g` provides an additional layer.

5. **IPC spoofing**: A random 32-byte token is generated per verification call.
   The subprocess echoes it back; mismatches are rejected (constant-time comparison).

6. **TCB tampering**: TCB source files are chmod'd read-only at startup on Linux.

### What PAAC does NOT protect against

1. **Axiom completeness**: PAAC only enforces the axioms defined in
   `config/axioms.yaml`. An incomplete axiom set may allow unsafe programs.

2. **SIL expressiveness**: Not all safety properties can be expressed in SIL.
   Properties requiring quantifiers, heap reasoning, or concurrency are out of scope.

3. **Z3 soundness**: PAAC inherits Z3's soundness guarantees. Z3 bugs could
   produce incorrect results.

4. **Side channels beyond timing**: Constant-time padding mitigates timing
   side channels. Other side channels (power, cache) are not addressed.

5. **Kernel/hypervisor attacks**: PAAC does not protect against attacks at the
   OS or hypervisor level.

6. **macOS RLIMIT_AS**: The kernel does not enforce RLIMIT_AS on macOS.
   Use Docker `--memory=2g` on macOS.

---

## Security Controls (v4.1 Status)

| Control | Status | Notes |
|---|---|---|
| Real Z3 BMC pipeline | ✅ Complete | SSA, loop unrolling, phi-node merges |
| Real axiom conditions | ✅ Complete | `balance >= 0`, `counter >= 0`, etc. |
| Axiom encoding raises on failure | ✅ Complete | Never silently skipped |
| Z3 subprocess isolation | ✅ Complete | RLIMIT_AS + RLIMIT_CPU (Linux) |
| IPC token authentication | ✅ Complete | 32-byte random, constant-time compare |
| Z3 crash retry (3x) | ✅ Complete | Falls back to static analyzer |
| Static fallback analyzer | ✅ Complete | Catches assert false, div-by-zero |
| Circuit breaker | ✅ Complete | 5 failures → OPEN, 60s cooldown |
| WAL persistence | ✅ Complete | JSON-lines, atomic registry save |
| Rollback on rejection | ✅ Complete | Restores last verified checkpoint |
| Constant-time padding | ✅ Complete | 200 ms floor |
| TCB file protection | ✅ Complete | chmod 0o444 on Linux |
| API key authentication | ✅ Complete | X-API-Key header |
| Rate limiting | ✅ Complete | 100 req/min per IP |
| Input sanitization | ✅ Complete | Rejects non-printable characters |
| Non-root Docker container | ✅ Complete | `paac` user |
| Docker HEALTHCHECK | ✅ Complete | /health endpoint |
| Structured audit log | ✅ Complete | audit.log, append-only |
| Prometheus metrics | ✅ Complete | /metrics endpoint |

---

## Known Limitations

See `KNOWN_ISSUES.md` for the full list with severities and mitigations.

The most significant open limitation is that RLIMIT_AS is not enforced on macOS.
Mitigation: deploy with `docker run --memory=2g`.
