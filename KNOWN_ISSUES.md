# Known Issues

## Compiler Gaps

### KI-002: Duplicate SIL parameter names silently accepted (Low)
The SIL type checker does not detect duplicate parameter names in a function
signature. For example, `func f(x: int, x: int) -> int` compiles without
error. The second parameter silently shadows the first in the SSA environment.
Mitigation: avoid duplicate parameter names. A compile-time check is planned
for a future release.
Status: Open.

### KI-003: Missing return statement silently accepted (Low)
A SIL function that falls off the end without a `return` statement is not
rejected at compile time. The verifier will still encode the function body
correctly, but the absence of a return value is not flagged.
Mitigation: always include an explicit `return` statement. A compile-time
check is planned for a future release.
Status: Open.

## Verification

### KI-004: Loop bound must be sufficient for all reachable inputs (Medium)
The BMC pipeline unrolls loops exactly K times (the declared `bound`). If the
loop requires more than K iterations for some input, the A-01 post-unroll
check will classify the program as UNSAFE (SAT). There is no automated bound
inference — the developer must choose a bound large enough to cover all
reachable inputs. Choosing too small a bound produces a false-positive
unsafety result; choosing too large a bound increases verification time.
Automated loop bound inference (e.g., via widening or template-based
approaches) is future work.
Status: Open.

## Static Analysis

### KI-001: `safety check` requires API key (Low)
The `safety` CLI tool (PyUp) requires a paid API key as of v3.0. Dependency
vulnerability scanning was not run as part of this release. Mitigation: use
`pip-audit` as a free alternative:

```bash
pip install pip-audit
pip-audit -r requirements.txt
```

No known CVEs were found in the pinned dependency set at time of release via
manual review of the PyPI advisories database.

## Security

### R-1: Z3 subprocess memory limits not enforced on all platforms (Medium)
`resource.setrlimit(RLIMIT_AS, ...)` is set in the Z3 subprocess but is not
enforced by the macOS kernel. On Linux it is enforced.
Mitigation: deploy with `docker run --memory=2g`.
Status: Open. Tracked for v4.1.

### R-2: No OS-level read-only memory protection for PAAC core (Medium)
The Code Monitor and Verifier are not mapped into read-only memory segments.
A privileged process on the same host could modify them at runtime.
Mitigation: run PAAC in an isolated container with a read-only filesystem
(`docker run --read-only`).
Status: Open. Requires rewriting the runtime in C with mprotect() calls.

### R-3: No IPC authentication between monitor and verifier (Medium)
The verifier subprocess is spawned directly by the monitor. There is no
cryptographic authentication of the IPC channel.
Mitigation: acceptable for single-host deployments. For multi-host, add
mutual TLS.
Status: Open. Tracked for v5.0.

### R-4: Redis fallback uses volatile in-memory checkpoint store (Medium)
If Redis is unavailable, checkpoints are stored in memory and lost on restart.
Mitigation: ensure Redis is highly available. Use `appendonly yes` in
redis.conf.
Status: Open. A local write-ahead log fallback is planned for v4.1.

### R-5: Source citation validation is not enforced (Medium)
The grounding check verifies only that the citation field is non-empty.
Any non-empty string passes.
Mitigation: implement URL validation and domain whitelist in v4.1.
Status: Open.

## Architecture

### R-6: CFG builder mixes expression nodes into statement lists (Low)
`SILToIRCompiler._compile_stmt()` appends branch conditions as raw expression
nodes into `BasicBlock.statements`. This does not affect the verifier (which
uses the AST directly) but would cause issues in any future CFG-based analysis.
Status: Open. Low priority.

### R-7: PAAC core is Python, not formally verifiable C (Info)
The paper claims the TCB can be formally verified with Verifiable C or Frama-C.
The current implementation is Python, which is not amenable to those tools.
Status: Acknowledged. Out of scope for v4.x.
