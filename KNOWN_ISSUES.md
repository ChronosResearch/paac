# Known Issues — v5.0.0

## Compiler

### KI-002: Duplicate SIL parameter names — FIXED in v5.0.0
The SIL type checker now detects duplicate parameter names at compile time and
raises `SILError`. Previously, the second parameter silently shadowed the first.
Status: **Fixed**.

### KI-003: Missing return statement — WARNING added in v5.0.0
A SIL function that falls off the end without a `return` statement now emits a
`SyntaxWarning` at compile time. The verifier still encodes the function body
correctly. A hard error is planned for a future release.
Status: Warning added. Hard error is future work.

## Verification

### KI-004: Loop bound must be sufficient for all reachable inputs (Medium)
The BMC pipeline unrolls loops exactly K times (the declared `bound`). If the
loop requires more than K iterations for some input, the A-01 post-unroll check
classifies the program as UNSAFE (SAT). There is no automated bound inference.
The developer must choose a bound large enough to cover all reachable inputs.
Automated loop bound inference is future work.
Status: Open.

### KI-005: Constant-time padding floor is 200ms (Low)
The verification latency floor is 200ms (constant-time padding). This is
intentional to prevent timing-based inference of verification results, but it
means the API cannot respond faster than 200ms even for trivial programs.
Status: By design. Documented.

## Security

### R-1: Z3 subprocess memory limits not enforced on macOS (Medium)
`resource.setrlimit(RLIMIT_AS, ...)` is set in the Z3 subprocess but is not
enforced by the macOS kernel. On Linux it is enforced.
Mitigation: deploy with `docker run --memory=2g`.
Status: Open. Platform limitation.

### R-2: TCB protection is filesystem chmod only (Medium)
The Code Monitor and Verifier are chmod'd read-only at startup on Linux. A
process running as root can still overwrite them. Kernel-level memory protection
(mprotect) would require rewriting the runtime in C.
Mitigation: run as non-root user (enforced in Docker image) with `--read-only`.
Status: Open. Acknowledged limitation.

### R-3: IPC channel is local pipe only (Low)
The Z3 subprocess communicates via a local OS pipe with a per-call HMAC token.
For multi-host deployments, mutual TLS would be required.
Status: Open. Acceptable for single-host deployments.

### R-4: Redis fallback uses volatile in-memory checkpoint store (Medium)
If Redis is unavailable, checkpoints are stored in memory and lost on restart.
The WAL provides durability for the most recent checkpoint per function.
Mitigation: ensure Redis is highly available with `appendonly yes`.
Status: Open.

## Architecture

### R-6: CFG builder stores branch conditions in a dedicated field (Low)
`SILToIRCompiler` stores branch conditions in `BasicBlock.branch_condition`
(not in `statements`). This is correct but means any future CFG-based analysis
must check both fields. The verifier uses the AST directly and is unaffected.
Status: Open. Low priority.

### R-7: PAAC core is Python, not formally verifiable C (Info)
The paper claims the TCB can be formally verified with Verifiable C or Frama-C.
The current implementation is Python, which is not amenable to those tools.
Status: Acknowledged. Out of scope.

## PCM

### KI-006: PCM proof generator uses Z3 internally (Info)
The `ProofGenerator` calls `BoundedModelChecker._verify_inner` (which uses Z3)
to determine whether a program is safe before generating the proof. The
`ProofChecker` itself does not use Z3 and runs in <10ms. The generator is a
separate, offline tool.
Status: By design. Documented.

### KI-007: Default HMAC key is insecure (High — mitigated)
The default `PAAC_CERT_KEY` value (`paac-default-cert-key-change-in-prod`) is
hardcoded and publicly known. Any deployment using the default key produces
certificates that can be forged by anyone who knows the key.
Mitigation: **always** set `PAAC_CERT_KEY` to a strong random value in production.
Generate with: `python3 -c "import secrets; print(secrets.token_hex(32))"`
Status: Mitigated by documentation and `.env.example`. Operator responsibility.

## Static Analysis

### KI-001: `safety check` requires API key (Low)
The `safety` CLI tool (PyUp) requires a paid API key as of v3.0. Use `pip-audit`
as a free alternative:
```bash
pip install pip-audit
pip-audit -r requirements.txt
```
Status: Open. No known CVEs in the pinned dependency set at time of release.
