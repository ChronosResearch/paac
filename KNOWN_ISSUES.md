# Known Issues — v6.1

## Compiler

### KI-002: Duplicate SIL parameter names — FIXED in v5.0.0
The SIL type checker detects duplicate parameter names at compile time and raises
`SILError`. Previously, the second parameter silently shadowed the first.
Status: **Fixed.**

### KI-003: Missing return statement — WARNING added in v5.0.0
A SIL function that falls off the end without a `return` statement emits a
`SyntaxWarning` at compile time. A hard error is planned for a future release.
Status: Warning added. Hard error is future work.

## Verification

### KI-004: Loop bound must be sufficient for all reachable inputs (Medium)
The BMC pipeline unrolls loops exactly K times (the declared `bound`). If a loop
requires more than K iterations for some input, the A-01 post-unroll check
classifies the program as UNSAFE. There is no automated bound inference.
Status: Open. Future work.

### KI-005: Constant-time padding floor is 200 ms (Low)
The verification response floor is 200 ms. This is intentional to prevent
timing-based inference of verification results. The API cannot respond faster
than 200 ms regardless of program complexity.
Status: By design. Documented.

## Security

### KI-007: Default HMAC key is insecure (High — mitigated)
The default `PAAC_CERT_KEY` value is hardcoded and publicly known. Any deployment
using the default key produces certificates that can be forged.
Mitigation: always set `PAAC_CERT_KEY` to a strong random value.
Generate with: `python3 -c "import secrets; print(secrets.token_hex(32))"`
Status: Mitigated by documentation and `.env.example`. Operator responsibility.

### R-1: Z3 subprocess memory limits not enforced on macOS (Medium)
`resource.setrlimit(RLIMIT_AS, ...)` is set in the Z3 subprocess but is not
enforced by the macOS kernel. On Linux it is enforced.
Mitigation: deploy with `docker run --memory=2g`.
Status: Open. Platform limitation.

### R-2: TCB protection is filesystem chmod only (Medium)
The Code Monitor and Verifier are chmod'd read-only at startup on Linux. A
process running as root can still overwrite them.
Mitigation: run as non-root user (enforced in Docker image) with `--read-only`.
Status: Open. Acknowledged limitation.

### R-3: IPC channel is local pipe only (Low)
The Z3 subprocess communicates via a local OS pipe with a per-call HMAC token.
Multi-host deployments would require mutual TLS.
Status: Open. Acceptable for single-host deployments.

### R-4: Redis fallback uses volatile in-memory checkpoint store (Medium)
If Redis is unavailable, checkpoints are stored in memory and lost on restart.
The WAL provides durability for the most recent checkpoint per function.
Mitigation: ensure Redis is highly available with `appendonly yes`.
Status: Open.

## Architecture

### R-6: CFG builder stores branch conditions in a dedicated field (Low)
`SILToIRCompiler` stores branch conditions in `BasicBlock.branch_condition`
rather than in `statements`. Any future CFG-based analysis must check both
fields. The verifier uses the AST directly and is unaffected.
Status: Open. Low priority.

### R-7: PAAC core is Python, not formally verifiable C (Info)
The current implementation is Python, which is not amenable to tools such as
Verifiable C or Frama-C.
Status: Acknowledged. Out of scope.

## PCM

### KI-006: PCM proof generator uses Z3 internally (Info)
`ProofGenerator` calls `BoundedModelChecker._verify_inner` (which uses Z3) to
determine whether a program is safe before generating the proof. The
`ProofChecker` itself does not use Z3 and runs in under 10 ms. The generator is
a separate, offline tool.
Status: By design. Documented.

## Static Analysis

### KI-001: `safety check` requires a paid API key (Low)
The `safety` CLI tool (PyUp) requires a paid API key as of v3.0. Use `pip-audit`
as a free alternative:
```bash
pip install pip-audit
pip-audit -r requirements.txt
```
Status: Open. No known CVEs in the pinned dependency set at time of release.
