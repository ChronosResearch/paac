# PAAC Security Policy — v7.0

## Supported Versions

| Version | Supported |
|---|---|
| v7.0.0 | ✅ Active |
| v6.1.0 | ✅ Security fixes only |
| < v6.1 | ❌ End of life |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email: security@paac-research.example.com

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

2. **Under-bounded loops (A-01 — fixed v4.2.0)**: After unrolling K iterations,
   the verifier adds a violation flag if the loop condition is still true.
   Programs whose loops cannot exit within the declared bound are correctly
   classified as UNSAFE.

3. **Unbounded computation**: All loops require explicit bounds. The runtime
   enforces a global instruction limit (100,000 steps) and loop bound cap
   (10,000 iterations).

4. **Recursion**: Direct and mutual recursion are rejected at compile time via
   call-graph cycle detection.

5. **Duplicate parameter names (H-02 — fixed v5.0.0)**: The type checker now
   rejects functions with duplicate parameter names at compile time.

6. **Resource exhaustion**: Z3 runs in a subprocess with RLIMIT_AS (1 GB) and
   RLIMIT_CPU (5 s) on Linux. Docker `--memory=2g` provides an additional layer.

7. **IPC spoofing**: A random 32-byte token is generated per verification call.
   The subprocess echoes it back; mismatches are rejected (constant-time
   comparison via `secrets.compare_digest`).

8. **API timing attacks (A-03 — fixed v4.2.0)**: API key comparison uses
   `secrets.compare_digest`.

9. **Cache poisoning (A-02 — fixed v4.2.0)**: The internal verification cache
   is name-mangled (`__cache`) and exposed only as a read-only property.

10. **Axiom scope leakage (A-05 — fixed v4.2.0)**: Axioms are filtered by
    `target_functions` before each verification call.

11. **TCB tampering**: TCB source files are chmod'd read-only at startup on Linux.

12. **Proof tampering (PCM)**: PCM certificates are HMAC-SHA256 signed over all
    certificate fields. Any field modification invalidates the signature.
    `hmac.compare_digest` is used for constant-time comparison.

13. **Unsafe eval (H-01 — fixed v5.0.0)**: The runtime axiom evaluator no longer
    uses `eval()`. It compiles the axiom condition through the SIL compiler and
    executes it via the SIL runtime, eliminating the code-injection surface.

14. **Duplicate loop violation (C-01 — fixed v5.0.0)**: The duplicate
    `still_running` violation flag in `StmtEncoder` was removed, preventing
    spurious SAT results for loop-heavy programs.

15. **Bounded Loop Verification (v7.0)**: Every loop bound is formally proven
    by Z3 to be ≤ 10,000 before BMC runs. Three-layer enforcement: parse-time
    rejection, Z3 UNSAT certificate, and runtime cap. Prevents algorithmic DoS
    attacks via crafted loop bounds.

### What PAAC does NOT protect against

1. **Axiom completeness**: PAAC only enforces the axioms in `config/axioms.yaml`.
   An incomplete axiom set may allow unsafe programs.

2. **SIL expressiveness**: Properties requiring quantifiers, heap reasoning, or
   concurrency are out of scope.

3. **Z3 soundness**: PAAC inherits Z3's soundness guarantees.

4. **Side channels beyond timing**: Constant-time padding mitigates timing side
   channels. Other side channels (power, cache) are not addressed.

5. **Kernel/hypervisor attacks**: PAAC does not protect against OS-level attacks.

6. **macOS RLIMIT_AS**: Not enforced by the macOS kernel. Use Docker `--memory=2g`.

---

## PCM Certificate Security

PCM certificates use HMAC-SHA256 over a canonical JSON payload:

```json
{
  "modification_id": "...",
  "code_hash": "<sha256 of SIL source>",
  "proof_hash": "<sha256 of canonical proof JSON>",
  "agent_id": "...",
  "timestamp": "...",
  "axioms_covered": [...]
}
```

Security properties:
- **Integrity**: Any field modification invalidates the HMAC signature.
- **Non-repudiation**: The certificate binds the agent identity to the proof.
- **Auditability**: Certificates are appended to an append-only JSONL log.
- **Third-party verifiability**: Any party with the HMAC key can verify certificates.

Key management:
- Set `PAAC_CERT_KEY` to a hex-encoded 32-byte random value in production.
- The default key (`paac-default-cert-key-change-in-prod`) is insecure and must
  be changed before any production deployment.
- Generate a key: `python3 -c "import secrets; print(secrets.token_hex(32))"`

---

## Security Controls (v5.0.0 Status)

| Control | Status | Notes |
|---|---|---|
| Real Z3 BMC pipeline | ✅ | SSA, loop unrolling, phi-node merges |
| **Duplicate loop flag (C-01)** | ✅ **Fixed v5.0.0** | Removed duplicate `still_running` append |
| **No eval() in runtime (H-01)** | ✅ **Fixed v5.0.0** | SIL compiler+runtime evaluator |
| **Duplicate param detection (H-02)** | ✅ **Fixed v5.0.0** | Compile-time check in type checker |
| **Loop soundness (A-01)** | ✅ **Fixed v4.2.0** | Under-bounded loops correctly SAT |
| **Cache poisoning (A-02)** | ✅ **Fixed v4.2.0** | `__cache` name-mangled |
| **Constant-time API key (A-03)** | ✅ **Fixed v4.2.0** | `secrets.compare_digest` |
| **Spawn start method (A-04)** | ✅ **Fixed v4.2.0** | `set_start_method("spawn")` |
| **target_functions enforced (A-05)** | ✅ **Fixed v4.2.0** | `_get_applicable_axioms()` |
| Z3 subprocess isolation | ✅ | RLIMIT_AS + RLIMIT_CPU (Linux) |
| IPC token authentication | ✅ | 32-byte random, constant-time compare |
| Z3 crash retry (3x) | ✅ | Falls back to static analyzer |
| Static fallback analyzer | ✅ | Catches assert false, div-by-zero |
| Circuit breaker | ✅ | 5 failures → OPEN, 60s cooldown |
| WAL persistence | ✅ | JSON-lines, atomic registry save |
| Rollback on rejection | ✅ | Restores last verified checkpoint |
| Constant-time padding | ✅ | 200 ms floor |
| TCB file protection | ✅ | chmod 0o444 on Linux |
| API key authentication | ✅ | X-API-Key header |
| Rate limiting | ✅ | 100 req/min per IP |
| Input sanitization | ✅ | Rejects non-printable characters |
| Non-root Docker container | ✅ | `paac` user |
| **PCM certificate HMAC (v5.0.0)** | ✅ **New** | HMAC-SHA256, append-only audit log |
| **Bounded Loop Verification (v7.0)** | ✅ **New** | Z3 UNSAT proof per loop, 3-layer enforcement |
| **Bootstrap Self-Verification (v5.0.0)** | ✅ **New** | Python-to-SIL translator |
| **Cryptographic Attestation (v5.0.0)** | ✅ **New** | HMAC-SHA256, key rotation |
| **Multi-Agent Coordination (v5.0.0)** | ✅ **New** | Agent registry, crash recovery |

---

## Disclosure Policy

Security issues are fixed in the next patch release. Critical issues are fixed
within 7 days of confirmation. Reporters are credited in the release notes unless
they request anonymity.
