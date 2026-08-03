# PCM Architecture — Proof-Carrying Modification

**Version:** 1.0
**Module:** `src/pcm/`

---

## Overview

Proof-Carrying Modification (PCM) is a protocol in which an agent submits a
formal proof of safety alongside every code modification. PAAC verifies the
proof (not the code) and generates a cryptographic certificate for every
accepted modification.

The key property: **proof checking is fast** (<10ms, no Z3) while **proof
generation is thorough** (uses Z3 internally). The agent bears the cost of
proof generation; PAAC bears only the cost of proof checking.

---

## Components

```
Agent
  |
  | (SIL code + PPL proof)
  v
ProofChecker          <-- pure Python, <10ms, no Z3
  |
  +-- REJECT --> error response, rollback
  |
  +-- ACCEPT
        |
        v
  generate_certificate  <-- HMAC-SHA256 over (code_hash, proof_hash, agent_id, ...)
        |
        v
  CertificateStore      <-- append-only JSONL audit log
        |
        v
  CodeMonitor           <-- applies modification to live registry
```

---

## Proof Language (PPL)

Proofs are JSON objects. See [PROOF_LANGUAGE.md](PROOF_LANGUAGE.md) for the
full specification.

A minimal valid proof:

```json
{
  "version": "1.0",
  "function": "withdraw",
  "axioms": ["no_negative_balance"],
  "preconditions": { "balance": "balance >= 0" },
  "steps": [
    { "type": "Assume", "var": "balance", "constraint": "balance >= 0" },
    { "type": "Assume", "var": "amount",  "constraint": "amount >= 0" },
    { "type": "Assert", "condition": "balance >= 0", "justification": "by Assume" },
    { "type": "ApplyAxiom", "axiom_id": "no_negative_balance", "condition": "balance >= 0" },
    { "type": "Conclude", "result": "safe", "covered_axioms": ["no_negative_balance"] }
  ],
  "conclusion": "safe"
}
```

---

## ProofChecker

**File:** `src/pcm/proof_checker.py`

The checker maintains a `SymbolicEnv` — a mapping from variable names to known
integer bounds (lower, upper, exact). It processes each proof step in order:

| Step | Action |
|------|--------|
| `Assume` | Add constraint to env |
| `Assign` | Update env with new expression (interval arithmetic) |
| `Assert` | Check condition is entailed by env; reject if not |
| `ApplyAxiom` | Verify axiom condition is entailed; mark axiom covered |
| `BranchSafe` | Record branch analysis (both branches must be safe) |
| `LoopInvariant` | Record invariant; verify bound is positive |
| `Conclude` | Verify all declared axioms are covered; result must be "safe" |

**Entailment** uses lightweight interval arithmetic:
- `x >= k` in env entails `x >= j` when `k >= j`
- Exact-match on assumed constraint strings
- Tautologies (`x == x`, `true`)
- Negation rewriting (`not (x < 0)` → `x >= 0`)

**Performance:** The checker is O(n) in the number of proof steps with no
external calls. Typical proofs check in 0.1–2ms.

**Size limit:** 64 KB per proof (enforced before parsing).

---

## ProofGenerator

**File:** `src/pcm/proof_generator.py`

The generator takes a SIL program and axiom list and produces a PPL proof:

1. Compile the SIL program to an AST.
2. Call `BoundedModelChecker._verify_inner` (uses Z3) to determine safety.
3. Walk the AST and emit proof steps for each statement.
4. For each applicable axiom, emit an `Assume` + `ApplyAxiom` step pair.
5. Emit a `Conclude` step.

The generator is rule-based (not an LLM). It produces proofs that the
`ProofChecker` can verify deterministically.

**Proof validity guarantee:**
- For safe programs (Z3 returns UNSAT), the generator produces a valid proof
  that the checker accepts.
- For unsafe programs (Z3 returns SAT), the generator produces a proof with
  `conclusion: "unsafe"` — the checker rejects it.

---

## Certificate System

**File:** `src/pcm/certificate.py`

Every accepted proof generates a `PCMCertificate`:

```json
{
  "version": "pcm-1.0",
  "modification_id": "<unique id>",
  "code_hash": "<sha256 of SIL source>",
  "proof_hash": "<sha256 of canonical proof JSON>",
  "agent_id": "<submitting agent identity>",
  "timestamp": "<ISO-8601>",
  "axioms_covered": ["<axiom_id>", ...],
  "paac_signature": "<hmac-sha256 of above fields>"
}
```

The HMAC is computed over a canonical JSON payload (sorted keys, no whitespace)
using the key from `PAAC_CERT_KEY`. The signature covers all fields except
`paac_signature` itself.

**Third-party verification:** Any party with the HMAC key can verify a
certificate by recomputing the signature and comparing with
`hmac.compare_digest` (constant-time).

**Audit log:** Certificates are appended to an append-only JSONL file
(`pcm_audit.jsonl` by default). Existing entries are never modified or deleted.

---

## CodeMonitor Integration

**File:** `src/monitor/code_monitor.py`

When `pcm_mode=True` in the config, `intercept_modification` delegates to
`_intercept_pcm`:

1. Check that `mod.proof` is not None (reject if missing).
2. Build `ProofChecker` with applicable axioms.
3. Call `checker.check(mod.proof)`.
4. If rejected: record failure, rollback, return error.
5. If accepted: generate certificate, save to store, apply modification.

The PCM path bypasses Z3 entirely. The agent is responsible for generating a
valid proof; PAAC is responsible for verifying it quickly.

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `pcm-generate <sil_file>` | Generate a PPL proof for a SIL file |
| `pcm-verify <proof_file>` | Verify a PPL proof (no Z3, <10ms) |
| `pcm-submit <sil_file> <proof_file>` | Submit modification + proof, get certificate |
| `pcm-audit` | Query the certificate audit log |

---

## Security Properties

| Property | Mechanism |
|----------|-----------|
| Proof integrity | Proof hash (SHA-256) in certificate |
| Code integrity | Code hash (SHA-256) in certificate |
| Certificate integrity | HMAC-SHA256 over all fields |
| Non-repudiation | Agent ID bound to certificate |
| Auditability | Append-only JSONL log |
| Timing safety | `hmac.compare_digest` for constant-time comparison |
| No code injection | Proof checker uses no `eval()` |

---

## Performance

| Operation | Typical latency |
|-----------|----------------|
| Proof checking | 0.1 – 2ms |
| Certificate generation | <1ms |
| Certificate verification | <1ms |
| Proof generation (with Z3) | 200ms – 5s |

The 10ms proof-checking budget is enforced by the acceptance criteria. The
checker is benchmarked in `tests/test_pcm.py`.
