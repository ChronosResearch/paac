# PAAC Security Policy — v4.1

## Threat Model

PAAC assumes the Inner Agent is adversarial. It may:

- Submit SIL code that violates safety axioms (mitigated: real Z3 axiom enforcement)
- Submit mutual recursion to bypass termination check (mitigated: call-graph DFS)
- Submit unrecognised characters to obfuscate intent (mitigated: lexer catch-all ERROR)
- Submit a large loop bound to exhaust CPU (mitigated: MAX_LOOP_BOUND=10,000 + subprocess RLIMIT_CPU)
- Craft a Z3 formula that exhausts memory (mitigated: subprocess RLIMIT_AS + docker --memory=2g)
- Flood the system with concurrent requests (mitigated: threading.Semaphore(4))
- Cause repeated verification failures to degrade service (mitigated: CircuitBreaker)

## Guarantees Provided (v4.1)

- Every modification is compiled through the SIL type checker before Z3 is invoked.
- Every modification is verified by Z3 against real safety axioms (not stubs).
- Unsafe modifications are rejected with a concrete counterexample.
- Verification response time is padded to a constant 200 ms on all exit paths.
- The verification cache uses SHA-256 over canonical JSON (collision-resistant).
- Z3 runs in a subprocess with RLIMIT_AS (1 GB) and RLIMIT_CPU (5 s) on Linux.
- Z3 subprocess crashes trigger automatic retry (up to 3 attempts) before the
  circuit breaker opens.
- On verification failure, the last verified checkpoint is restored from Redis,
  WAL, or in-memory store (in that priority order).
- Checkpoints are written to a write-ahead log (checkpoints.wal) before Redis,
  so they survive process restarts even when Redis is unavailable.
- The live function registry is persisted to live_registry.json after every
  accepted modification and loaded on startup.
- A circuit breaker opens after 5 consecutive verification failures, rejecting
  all new modifications for 60 s. After cooldown, one probe is allowed; success
  closes the circuit.
- A watchdog thread checks for heartbeats every 5 s. If no heartbeat is received
  for 30 s, the circuit breaker is reset and service resumes.
- IPC between the monitor and Z3 subprocess uses a per-call random 32-byte token
  (constant-time comparison). Responses without a matching token are rejected.
- TCB source files are marked read-only (chmod 0o444) on Linux at startup.
- Source citations must be >= 20 characters and contain a dot (URL/DOI heuristic).
- All verification attempts, counterexamples, and rollbacks are written to audit.log.

## Remaining Gaps

- **R-1 (partial)**: RLIMIT_AS is not enforced on macOS. Mitigation: deploy with
  `docker run --memory=2g`. This is the only NO-GO condition for production.

- **R-2 (partial)**: TCB source files are chmod'd read-only at startup. This
  prevents accidental overwrite but does not prevent a privileged process from
  chmod'ing them back. Full mitigation: `docker run --read-only`.

- **R-3 (partial)**: IPC token authenticates the subprocess response but the
  token is passed as a constructor argument (not over a separate authenticated
  channel). A process with access to /proc/<pid>/mem could read it. Acceptable
  for single-host deployments.

- **R-4 (resolved)**: WAL provides durable checkpoint storage independent of
  Redis. Checkpoints survive process restarts.

- **R-5 (resolved)**: Citation validation requires >= 20 chars with a dot.

- **Physical side-channels**: Power analysis, EM emissions, and cache-timing
  attacks are out of scope.

- **Axiom completeness**: PAAC enforces whatever axioms are provided. Incomplete
  axiom sets allow uncovered behaviours to pass. Axiom design is the operator's
  responsibility.

- **Neural network verification**: PAAC verifies SIL code, not model weights.

## Reporting Vulnerabilities

Contact: shashankchoudhary792@gmail.com

90-day responsible disclosure. Acknowledgement within 5 business days.
