# Known Issues

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
