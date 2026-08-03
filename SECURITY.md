# PAAC Security Policy — v5.0.0

## Supported Versions

| Version | Supported |
|---|---|
| v5.0.0 (branch 5.1) | ✅ Active |
| v4.2.0 (release-v4.0 branch) | ✅ Security fixes only |
| < v4.1 | ❌ End of life |

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

2. **Under-bounded loops (A-01 — fixed in v4.2.0)**: After unrolling K
   iterations, the verifier now adds a violation flag if the loop condition is
   still true. Programs whose loops cannot exit within the declared bound are
   correctly classified as UNSAFE (SAT).

3. **Unbounded computation**: All loops require explicit bounds. The runtime
   enforces a global instruction limit (100,000 steps) and loop bound cap
   (10,000 iterations).

4. **Recursion**: Direct and mutual recursion are rejected at compile time via
   call-graph cycle detection.

5. **Resource exhaustion**: Z3 runs in a subprocess with RLIMIT_AS (1 GB) and
   RLIMIT_CPU (5 s) on Linux. Docker `--memory=2g` provides an additional layer.
   The subprocess uses the `spawn` start method (A-04 — fixed in v4.2.0) to
   avoid fork-under-threads instability.

6. **IPC spoofing**: A random 32-byte token is generated per verification call.
   The subprocess echoes it back; mismatches are rejected (constant-time
   comparison via `secrets.compare_digest`).

7. **API timing attacks (A-03 — fixed in v4.2.0)**: API key comparison uses
   `secrets.compare_digest` to prevent timing-based key enumeration.

8. **Cache poisoning (A-02 — fixed in v4.2.0)**: The internal verification
   cache is name-mangled (`__cache`) and exposed only as a read-only property.
   External code cannot inject false-safe entries.

9. **Axiom scope leakage (A-05 — fixed in v4.2.0)**: Axioms are filtered by
   `target_functions` before each verification call. An axiom targeting
   `withdraw` is never applied to `deposit`.

10. **TCB tampering**: TCB source files are chmod'd read-only at startup on Linux.

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

## Security Controls (v5.0.0 Status)

| Control | Status | Notes |
|---|---|---|
| Real Z3 BMC pipeline | ✅ Complete | SSA, loop unrolling, phi-node merges |
| Real axiom conditions | ✅ Complete | `balance >= 0`, `counter >= 0`, etc. |
| Axiom encoding raises on failure | ✅ Complete | Never silently skipped |
| **Loop soundness (A-01)** | ✅ **Fixed v4.2.0** | Under-bounded loops now correctly SAT |
| **Cache poisoning (A-02)** | ✅ **Fixed v4.2.0** | `__cache` name-mangled, read-only property |
| **Constant-time API key (A-03)** | ✅ **Fixed v4.2.0** | `secrets.compare_digest` |
| **Spawn start method (A-04)** | ✅ **Fixed v4.2.0** | `set_start_method("spawn")` |
| **target_functions enforced (A-05)** | ✅ **Fixed v4.2.0** | `_get_applicable_axioms()` |
| Z3 subprocess isolation | ✅ Complete | RLIMIT_AS + RLIMIT_CPU (Linux) |
| IPC token authentication | ✅ Complete | 32-byte random, constant-time compare |
| Z3 crash retry (3x) | ✅ Complete | Falls back to static analyzer |
| Static fallback analyzer | ✅ Complete | Catches assert false, div-by-zero |
| Circuit breaker | ✅ Complete | 5 failures → OPEN, 60s cooldown |
| WAL persistence | ✅ Complete | JSON-lines, atomic registry save |
| Rollback on rejection | ✅ Complete | Restores last verified checkpoint |
| Constant-time padding | ✅ Complete | 200 ms floor |
| TCB file protection | ✅ Complete | chmod 0o444 on Linux (filesystem only) |
| API key authentication | ✅ Complete | X-API-Key header |
| Rate limiting | ✅ Complete | 100 req/min per IP |
| Input sanitization | ✅ Complete | Rejects non-printable characters |
| Non-root Docker container | ✅ Complete | `paac` user |
| Docker HEALTHCHECK | ✅ Complete | /health endpoint |
| Structured audit log | ✅ Complete | audit.log, append-only |
| **Bootstrap Self-Verification (v5.0.0)** | ✅ **New v5.0.0** | Python-to-SIL translator; TCB stubs verified |
| **Cryptographic Attestation (v5.0.0)** | ✅ **New v5.0.0** | HMAC-SHA256, key rotation, thread-safe |
| **Multi-Agent Coordination (v5.0.0)** | ✅ **New v5.0.0** | Agent registry, crash recovery, conflict detection |

---

## Known Limitations

See `KNOWN_ISSUES.md` for the full list with severities and mitigations.

The most significant open limitation is that RLIMIT_AS is not enforced on macOS.
Mitigation: deploy with `docker run --memory=2g`.

TCB protection is filesystem-level chmod only (not kernel read-only memory pages).
A process running as root can still overwrite TCB files. Mitigation: run as
non-root user (enforced in Docker image) and deploy with `--read-only` filesystem.
