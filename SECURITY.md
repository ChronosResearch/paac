# PAAC Security Policy

## Threat Model

PAAC assumes the Inner Agent is adversarial. Specifically, it may:

- Submit SIL code that violates safety axioms
- Attempt to bypass verification by crafting axiom conditions that are not
  encoded (e.g., conditions outside the three hardcoded strings in earlier
  versions — this is fixed in v4.0)
- Submit SIL code with mutual recursion to bypass the termination check
  (fixed in v4.0 via full call-graph cycle detection)
- Submit SIL code with unrecognised characters to obfuscate intent
  (fixed in v4.0 via lexer catch-all ERROR token)
- Submit a loop with a very large declared bound to exhaust CPU
  (mitigated in v4.0 via MAX_LOOP_BOUND=10,000 and MAX_INSTRUCTIONS=100,000)
- Craft a Z3 formula that exhausts system memory
  (partially mitigated in v4.0 via subprocess RLIMIT_AS; see R-1 below)

## Guarantees Provided

- Every code modification is compiled through the SIL type checker before
  reaching the verifier. Ill-typed code is rejected before Z3 is invoked.
- Every code modification is verified by Z3 against the loaded axiom set
  before being accepted. The verifier uses bounded model checking with SSA
  encoding and loop unrolling.
- Unsafe modifications are rejected with a concrete counterexample extracted
  from the Z3 model.
- Verification response time is padded to a constant 200 ms on all exit paths
  (safe, unsafe, and error) to prevent timing side-channels.
- The verification cache uses SHA-256 over a canonical JSON serialisation of
  the AST and axiom set. Hash collisions do not cause incorrect cache hits.
- The Z3 solver runs in a subprocess with RLIMIT_AS (1 GB) and RLIMIT_CPU
  (5 s) set via resource.setrlimit on Linux.
- On verification failure, the last verified checkpoint is restored.

## Guarantees Not Provided

- **R-1 (partial)**: Z3 subprocess resource limits are not enforced on macOS.
  On Linux, RLIMIT_AS is enforced but a sufficiently crafted formula may still
  cause the subprocess to be killed by the OOM killer before RLIMIT_AS fires.
  Mitigation: deploy with `docker run --memory=2g`.

- **R-2**: The PAAC core (Code Monitor, Verifier) does not reside in OS-level
  read-only memory. A sufficiently privileged process on the same host could
  modify PAAC code at runtime.

- **R-3**: There is no IPC authentication between the Code Monitor and the
  Verifier subprocess. The subprocess is spawned directly by the monitor
  process; it is not accessible from outside the process group.

- **R-4**: If Redis is unavailable, checkpoints fall back to a volatile
  in-memory store. Checkpoint history is lost on process restart.

- **R-5**: Source citation validation checks only that the citation field is
  non-empty. It does not validate URLs or verify that citations resolve to
  real sources.

- **Physical side-channels**: Power analysis, electromagnetic emissions, and
  cache-timing attacks are outside the scope of this system.

- **Axiom completeness**: PAAC enforces whatever axioms are provided. If the
  axiom set is incomplete, dangerous behaviours not covered by axioms will
  pass verification. Axiom design is the responsibility of the operator.

- **Neural network verification**: PAAC verifies SIL code, not neural network
  weights. It does not protect against unsafe behaviour that emerges from
  model weights rather than code modifications.

## Reporting Vulnerabilities

Contact: shashankchoudhary792@gmail.com

Please include:
- A description of the vulnerability
- Steps to reproduce
- The version of PAAC affected
- Any proof-of-concept code

## Disclosure Policy

90-day responsible disclosure. We will acknowledge receipt within 5 business
days and provide a status update within 30 days. If a fix is not available
within 90 days, we will coordinate with the reporter on public disclosure
timing.
