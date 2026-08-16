# PAAC v7.0 — Independent Zero-Trust Security Audit

| | |
|---|---|
| **Audit scope** | Full codebase, configuration, deployment manifests, documentation, and the PAAC v7.0 paper |
| **Commit audited** | `83423c4c1debdd8d7e78aaf0681f7ae0b8f3c2a1` (`main`, "Merge pull request #36 from ChronosResearch/fix-audit-errors") |
| **Method** | Zero-trust: every paper claim traced to code; adversarial probes executed where dependencies allowed |
| **Auditor posture** | Independent. No claim accepted on the basis of documentation alone. |

---

## FINAL VERDICT: **NO-GO**

PAAC v7.0 contains a **real, working, and genuinely well-engineered core**: the SIL
compiler, the Z3 BMC pipeline, the A-01…A-05 security fixes, the circuit breaker,
and the Ed25519 signing primitive all do what the paper says they do, and I
verified them adversarially. That core is publishable work.

However, **three of the paper's seven headline contributions do not hold up under
adversarial examination**, and one of them I broke empirically in five different
ways. Two additional blockers concern reproducibility of the paper's own
evaluation numbers and the security posture of the shipped deployment manifest.

A NO-GO verdict here means: **do not submit the paper with the current claims, and
do not deploy the current `k8s/` manifest.** It does not mean the project is
unsound work. Most blockers are fixable in days, and several are fixable by
correcting prose rather than code.

### Blocking issues

| ID | Severity | Issue | Affected claim |
|---|---|---|---|
| **BLK-1** | Critical | PCM proof checker is unsound; **5 bypasses demonstrated empirically**; proof is never bound to the code | Abstract contribution #3, §4.2 |
| **BLK-2** | Critical | Attestation verification has **no trust anchor** — signatures are checked against the public key carried inside the record being checked | Abstract contribution #2, §4.3 |
| **BLK-3** | Critical | Bootstrap self-verification is **vacuous** — all 6 TCB stubs are tautologies of the form `if P { assert P }` | Abstract contribution #1, §4.1 |
| **BLK-4** | High | Safety axioms are **silently discarded** when the program does not happen to name the sentinel variable; programs with no applicable axiom are declared safe **without invoking Z3** | §3.4 core guarantee |
| **BLK-5** | High | The "43 mutants / 100% robustness" result is **not reproducible** and pairs two different denominators; committed artifacts describe a **different axiom set** | §4.7, §5.2, Table 5.2 |
| **BLK-6** | High | `k8s/deployment.yaml` ships a **v3.0 image with authentication disabled, no resource limits, no securityContext**, and `replicas: 3` against per-process in-memory state | §6.4, §6.2 |

### What I verified as sound

The following claims survived adversarial testing and are accurately described:

- **386 passing tests** — confirmed by CI on the exact audited commit (§Evidence A).
- **SIL compile-time checks** — recursion (direct, 2-cycle, 3-cycle), duplicate
  parameters, loop-bound positivity and cap, undefined variables/functions. All
  probed adversarially; all correctly rejected (§Evidence B).
- **A-01 … A-05** — all five fixes present and correctly implemented.
- **Ed25519 signing** — genuine asymmetric crypto; signed payload matches §4.3 field-for-field.
- **Three-layer loop cap** — all three layers exist and fail closed.
- **Z3 subprocess isolation** — RLIMIT_AS/RLIMIT_CPU, authenticated IPC token, 3-retry recovery.
- **Fail-closed behaviour** — the Z3-failure fallback path refuses to accept on doubt.
- **Circuit breaker** — 5 failures → OPEN, 60 s cooldown, exactly as documented.
- **PCM latency < 10 ms** — measured 0.004–0.02 ms.
- **§7.1 Limitations** — unusually honest. Several real weaknesses are disclosed there.

---

## Audit environment and its one material limitation

PyPI is unreachable from the audit sandbox (HTTP 403 at the egress proxy for both
`pypi.org` and `files.pythonhosted.org`; `pip`, `uv`, and cache-only installs all
fail). `z3-solver`, `lark`, `fastapi`, `pydantic`, `cryptography`, `redis`,
`prometheus-client`, `loguru`, `psutil`, `jsonschema`, `filelock`, and `pyyaml`
are therefore **absent**.

**Consequence, stated plainly: I could not execute the 386-test suite myself.**

I compensated as follows, and I flag which findings are executed versus code-derived:

- **Executed.** `src/core/sil_compiler.py`, `src/pcm/proof_checker.py`,
  `src/pcm/certificate.py`, and `src/mutation/axiom_mutator.py` are pure-stdlib
  (the last needed only a `yaml` stub). I ran real adversarial inputs through
  them. BLK-1, BLK-5, and the compiler results are **empirically demonstrated**,
  with reproduction scripts committed alongside this report.
- **CI-corroborated.** The 386-test claim is verified from the GitHub Actions log
  for the exact audited SHA.
- **Code-derived.** BLK-2, BLK-3, BLK-4, BLK-6 and the Z3-dependent findings are
  read from unambiguous source. Where I could not execute, I say so and quote the
  responsible lines. **BLK-2 in particular is asserted from code only** — it is a
  three-line control-flow fact, but an implementer should confirm it with a live
  `cryptography` install before acting.

---

# Blocking findings in detail

## BLK-1 — Critical. The PCM proof checker is unsound; five bypasses demonstrated

**Claim under test** (Abstract #3; §4.2): *"The agent submits a formal proof
alongside every code modification. PAAC verifies the proof using an independent
AST-based proof checker… Performance: < 10 ms per proof."*

### Root cause 1: the proof is never bound to the code

`src/monitor/code_monitor.py` routes PCM mode **before** any model checking:

```python
if self.pcm_mode:
    # PCM mode: verify the proof, not the code.
    return self._intercept_pcm(mod, applicable)

with _VERIFY_SEMAPHORE:
    safe, counterexample = self.checker.verify(...)   # never reached in PCM mode
```

And `_intercept_pcm` hands the checker **only the proof**:

```python
checker = ProofChecker(axiom_dicts)
check_result = checker.check(mod.proof)     # mod.new_code is never passed
```

`ProofChecker.check(self, proof: dict)` has no access to the program. Confirmed by
grep: `proof_checker.py` contains no reference to `new_code`, `program`,
`ProgramNode`, or `SILCompiler`, and never checks a `program_hash`. **There is no
cryptographic or structural binding between the proof and the code it allegedly
proves.** Z3 is never invoked. In PCM mode the only gate any submission passes is
"does it parse as SIL".

### Root cause 2: the agent may assume its own obligations

`SymbolicEnv.assume()` records the constraint string unconditionally:

```python
def assume(self, var: str, constraint: str) -> None:
    self._assumed.add(constraint.strip())     # unconditional
```

and `entails()` opens with an exact-string fast path:

```python
if condition in self._assumed:
    return True
```

There is no separation between *assumptions* (which a sound system must discharge
against the caller's precondition) and *obligations*. The prover may assume
verbatim whatever it is required to prove.

### Demonstrated exploits

Executed against the real `ProofChecker` seeded with the real five production
axioms from `config/axioms.yaml`. Reproduce with `audit/v7.0/audit_pcm.py`.

| # | Technique | Verdict | Latency |
|---|---|---|---|
| E1 | Empty proof: `{"version":"1.0","axioms":[],"preconditions":{},"steps":[{"type":"Conclude","result":"safe"}],"conclusion":"safe"}` | **ACCEPT** | 0.0043 ms |
| E2 | `Assume` each obligation, then `ApplyAxiom` on all 5 real axioms | **ACCEPT**, reported as covering all 5 | 0.0193 ms |
| E3 | `Assign balance = -500`, then `Assume "balance >= 0"`, then `Assert "balance >= 0"` | **ACCEPT** | 0.0092 ms |
| E4 | `LoopInvariant` as an arbitrary-fact oracle (only `bound <= 0` is checked) | **ACCEPT** | 0.0067 ms |
| E5 | `BranchSafe` with agent-supplied `then_safe: true, else_safe: true` — no branch analysis occurs | **ACCEPT** | 0.0047 ms |
| C1 | *Control:* `Assign -500` + `ApplyAxiom`, no `Assume` laundering | **REJECT** (correct) | 0.0114 ms |

E1 is the most consequential: **a 5-key JSON document accepts any compilable SIL
program.** Note also that `declared_axioms` is read *from the proof*, and
`Conclude` only checks `set(declared_axioms) - covered_axioms`. Declaring
`"axioms": []` therefore discharges nothing — I confirmed a proof declaring zero
axioms is ACCEPTED with `covered_axioms=[]` even though the `ProofChecker` was
constructed with all five. Nothing requires `declared_axioms ⊇ applicable`.

The control case matters: the interval arithmetic **does** work. This is not a
stub. The unsoundness is localised to `Assume`, `LoopInvariant`, `BranchSafe`, and
the empty-axiom-set path.

### On the "< 10 ms" claim

Verified — 0.004–0.02 ms, 500× better than claimed. But the paper frames this as
evidence that verification cost has been *shifted to the agent*. It is faster
because the checker performs almost no work: the cost was not shifted, it was
skipped.

### Exposure

`PAAC_PCM_MODE` is read **zero** times in `src/`, and `CodeMonitor` reads
`config["pcm_mode"]` while `config/default.yaml` defines nested `pcm.enabled`.
**PCM mode cannot be enabled through either documented mechanism** — only
programmatically, as the tests do. So this is *not* remotely reachable in a
default deployment. That lowers the operational risk considerably and I weight it
accordingly. It does not lower the publication risk: §4.2 presents PCM as
implemented, evaluated, and measured.

### Required fixes

1. Bind proof to code: include `program_hash` in the proof, and reject unless it equals `SHA-256(new_code)`.
2. Require `declared_axioms ⊇ [a.id for a in applicable]`.
3. Restrict `Assume` to the modification's declared `pre_cond`; forbid free-form assumption.
4. Discharge `LoopInvariant` (initiation + preservation) instead of trusting the string.
5. Compute `BranchSafe` from the AST; never read it from the proof.
6. Until 1–5 land, either remove PCM from the paper or reframe §4.2 explicitly as an unsound prototype.

---

## BLK-2 — Critical. Attestation verification has no trust anchor

**Claim under test** (§4.3): *"any holder of the public key can verify without
trusting PAAC… Non-repudiation: third parties can verify without shared
secret… Self-contained: PCM certificates embed the public key."*

`src/core/attestation.py`:

```python
def verify(self, record: AttestationRecord) -> bool:
    return self.verify_with_public_key(record, record.public_key_pem)
```

The signature is verified **using the public key carried inside the record being
verified.** `src/main.py` exposes this over HTTP with an attacker-controlled body:

```python
@app.post("/attest/verify")
async def verify_attestation_endpoint(record_data: dict):
    record = AttestationRecord.from_dict(record_data)
    valid = verify_attestation(record)
    return {"valid": valid}
```

An adversary generates their own Ed25519 keypair, constructs any
`AttestationRecord` they like — arbitrary `program_hash`, `result: "UNSAT"`,
arbitrary `axiom_hash` — signs it with their own private key, embeds their own
`public_key_pem`, and `POST /attest/verify` returns `{"valid": true}`. The
engine's own `_public_key` is never consulted. There is no pinning, no key
registry, no certificate chain, no trust root.

This inverts the security property the paper claims. Ed25519 provides
non-repudiation **only when the verifier independently knows the expected public
key.** Self-containment is precisely what destroys the guarantee: the record
authenticates itself.

The correct primitive already exists — `verify_with_public_key(record,
trusted_pem)`. Only the default caller is wrong.

*Evidence basis: code-derived. `cryptography` was unavailable, so I did not
execute a forgery. The control flow is three lines and unambiguous, but confirm
locally before acting.*

**Required fixes**

1. `verify()` must use the engine's trusted key, never `record.public_key_pem`.
2. `/attest/verify` must accept a *key identifier* resolved against a trusted registry, not an inline key.
3. Publish the public key at a separate authenticated endpoint (e.g. `GET /attest/pubkey`).
4. Keep `public_key_pem` in the record for key *identification* only, and document it as non-authoritative.
5. Support multiple trusted keys so rotation continues to work (the rotation mechanism itself is sound).

---

## BLK-3 — Critical. Bootstrap self-verification is vacuous

**Claim under test** (Abstract #1; §4.1): *"PAAC includes a Python-to-SIL
translator that converts the TCB source files into SIL. The self-checking
pipeline verifies six structural invariants."*

All six stubs in `src/core/self_verify.py` have this shape:

```python
"bmc_verify_inner": """
    func bmc_verify_inner(timeout_ms: int) -> int {
        if timeout_ms >= 1 {
            assert timeout_ms >= 1;     # identical to the enclosing condition
        }
        return timeout_ms;
    }
"""
```

The asserted predicate **is the enclosing branch condition.** `if P { assert P }`
is a tautology; it is UNSAT for every `P`, for every program, regardless of any
property of PAAC. `run()` then *also* passes the matching axiom as `pre_cond`,
asserting the same predicate a third time. Nothing about the actual TCB is tested.

Four further problems compound this:

1. **The translator is not in the path.** `run()` uses `stubs = dict(TCB_STUBS)` —
   hardcoded strings. `python_to_sil_stub()` is reachable only via
   `verify_from_python_source()`, which is called by neither `run()`, nor
   `POST /self-verify`, nor startup. The translator exists; the self-verification
   pipeline does not use it.
2. **The translator degrades to tautology anyway** — any parse failure returns
   `_tautological_stub` = `assert x == x`, and all external calls are dropped.
3. **"Six structural invariants" is wrong.** There are 6 *stubs* and 4
   `SELF_AXIOMS`. `bmc_verify_inner` and `verifier_facade` are byte-identical
   modulo name; `stmt_encoder_while` and `monitor_axiom_count` differ only
   `>= 1` vs `>= 0`. So roughly 4 distinct tautologies.
4. **Isolation is bypassed.** `/self-verify` calls `_bmc._verify_inner` directly,
   so these runs get no subprocess sandbox, no RLIMIT, no IPC token, and no
   200 ms padding. The class docstring discloses this.

**This is a regression, not an oversight.** `PAPER_CLAIMS_CHECKLIST.md` recorded
the honest v5 status: *"PARTIAL — Stubs assert conditions that are SAT for
unconstrained inputs. This is correct behavior — the verifier finds boundary
conditions. Full proof requires preconditions on inputs (future work)."* That was
accurate. The subsequent change wrapped each assert in an `if` carrying the
identical condition — converting a truthful SAT into a vacuous UNSAT and turning
a disclosed limitation into an apparent pass. I want to be direct: the earlier
document was the more scientifically defensible artifact.

**Required fixes**

- Make the assertions non-trivial: assert a *consequence* of the precondition, not the precondition (e.g. precondition `timeout_ms >= 1`, assert `timeout_ms * 2 >= 2`).
- Drive `run()` from `python_to_sil_stub()` over real TCB sources, or state plainly in §4.1 that the stubs are hand-written contracts.
- Make translator fallback a hard failure; a tautology must never silently substitute for a proof.
- Reconcile "six invariants" with the 6-stub/4-axiom reality.
- Report which stub↔TCB-function correspondence is actually established, since that is the crux of the contribution.

---

## BLK-4 — High. Axioms are silently discarded; a "safe" verdict can skip Z3

`_encode_axiom()` in `src/core/verifier.py` builds its SIL wrapper parameter list
only from variables present in the live `SSAEnv`. If an axiom references a
variable the program never mentions, the SIL type checker raises
`Undefined variable` — which is on the *inapplicable* list:

```python
_inapplicable_markers = (
    "Undefined variable", "Undefined function", "Type mismatch", "Arity mismatch",
)
if any(m in str(exc) for m in _inapplicable_markers):
    logger.debug(f"Axiom '{axiom.id}' inapplicable to current function: {exc}")
    return None
...
except Exception as exc:
    logger.debug(...)
    return None
```

Consequences:

1. `no_exit` (`exit_called == 0`) and `no_network` (`network_calls == 0`) — both
   `target_functions: ["*"]` — **constrain only programs that voluntarily declare
   those variables.** An adversarial agent simply never names a variable
   `exit_called`, and the axiom evaporates. These are name-conventions, not
   semantic properties. Unavoidable given that SIL has no syscalls — but the paper
   presents them as enforced global safety properties.
2. `Type mismatch` and `Arity mismatch` are treated as "inapplicable" rather than
   as errors, so a *malformed* axiom is silently skipped. The bare
   `except Exception: return None` swallows anything else. This defeats the
   Step-22 intent stated in the function's own docstring ("raises on failure,
   never silently skips").
3. Worst: with no asserts and no applicable axioms, the program is declared safe
   **without ever calling the solver**:

```python
if not stmt_enc.violation_flags:
    self.__cache[cache_key] = (True, None)
    return True, None, loop_report
```

An empty program returns UNSAT-equivalent "safe" having consulted nothing.

**Required fixes**

- Fail closed on an empty violation set, or return an explicit `VACUOUS` status distinct from "safe".
- Treat `Type mismatch` / `Arity mismatch` / unexpected exceptions as hard errors; keep only `Undefined variable`/`Undefined function` as "inapplicable", and log at WARNING with the axiom id.
- Record which axioms were applied in the result and in the attestation payload (see H-3).
- Document sentinel-variable axioms in §3.4 as a *convention* requiring a trusted compiler front-end to inject the sentinels.

---

## BLK-5 — High. The mutation-testing result is not reproducible

**Claim under test** (§4.7, §5.2, Abstract): *"43 mutants across 5 axioms, 100%
robustness score. Every mutation changes at least one verification outcome."*

I ran the real generator against the real axiom set
(`audit/v7.0/audit_mutants.py`):

| Axiom | Condition | Mutants incl. `noop` | excl. `noop` |
|---|---|---|---|
| `no_negative_balance` | `balance >= 0` | 9 | 8 |
| `counter_in_range` | `counter >= 0` | 9 | 8 |
| `result_bounded` | `result >= 0` | 9 | 8 |
| `no_exit` | `exit_called == 0` | 8 | 7 |
| `no_network` | `network_calls == 0` | 8 | 7 |
| **Total** | | **43** | **38** |

So the paper's per-axiom table (9, 9, 9, 8, 8 = 43) is the **including-`noop`**
count. But the score's denominator **excludes** `noop`:

```python
@property
def mutation_score(self) -> float:
    """Fraction of non-noop mutants that were killed."""
```

and every `noop` mutant is recorded `survived=True` **by construction** — the CSV
confirms `kill_rate 0.0000, survived True` for all five. `noop` is the identity
mutation; it *must not* change any outcome.

**Therefore "43 mutants / 100% robustness" pairs a numerator count from one
population with a score from another.** Over 43 the score is at most 38/43 =
**88.4%**. And the sentence "Every mutation changes at least one verification
outcome" is **false for the 5 `noop` mutants the 43 includes.**

Independently, **the committed evidence contradicts the paper.**
`docs/axiom_mutation_results.json`, `docs/axiom_mutation_results.csv`, and
`docs/AXIOM_MUTATION_REPORT.md` (all `generated_at: 2026-08-03`) report
`total_mutants: 40` over a **different axiom set**:

```
no_negative_balance, counter_in_range, result_bounded, amount_positive, index_nonneg
```

`amount_positive` and `index_nonneg` are **not in `config/axioms.yaml`**, which
has `no_exit` and `no_network`. The artifacts were never regenerated after the
axiom set changed. **Paper Table 5.2 cannot be reproduced from any committed
artifact.**

To its credit, `docs/AXIOM_MUTATION_REPORT.md` states the metric correctly
("fraction of non-noop mutants"). The paper dropped the qualifier while inflating
the count.

**Required fixes**

- Regenerate all three artifacts against the current axiom set and commit them.
- Report one consistent population. Recommended: "38 non-`noop` mutants, 100% killed (43 generated, 5 `noop` excluded by construction)".
- Delete or qualify "every mutation changes at least one verification outcome".
- Fix `robustness_score`'s docstring, which claims direction weighting that is **not implemented** (it returns `mutation_score`, or `0.0` if vacuous).
- Add a CI job that regenerates and diffs these artifacts so they cannot drift again.

---

## BLK-6 — High. The shipped Kubernetes manifest is insecure and stale

`k8s/deployment.yaml` in full is 2 objects and ~30 lines. It contains:

| Problem | Detail |
|---|---|
| **Stale image** | `image: paac-core:v3.0` — four major versions behind the audited code |
| **No authentication** | No `PAAC_API_KEY` env → `if _API_KEY:` is False → **auth entirely disabled** |
| **No resource limits** | No `resources.limits` — directly contradicts KNOWN_ISSUES R-1's mitigation (`--memory=2g`) and §6.4 |
| **No securityContext** | No `runAsNonRoot`, `runAsUser`, `readOnlyRootFilesystem`, or capability drops |
| **`replicas: 3` vs in-memory state** | See below |

The replica count is the subtle one. The attestation store, rate-limit counters,
circuit breaker, and `_live_registry` are all **per-process in-memory**:

- `GET /attest/{id}` **404s roughly two times in three** — the record lives in whichever pod served the `POST /verify`. The attestation retrieval endpoint (§6.3) is effectively broken at the shipped replica count.
- Rate limiting is 100/min **per pod** → 300/min actual.
- The circuit breaker needs 5 consecutive failures **per pod** → up to 15 system-wide.
- `_live_registry` diverges across pods.

Related (H-5): there are **two contradictory Dockerfiles**. `docker/Dockerfile`
is good — `python:3.11-slim`, non-root `paac` user, `/health` healthcheck — and is
what §6.4 builds. The root `Dockerfile` is `python:3.12-alpine` with **no `USER`
directive (runs as root)** and `ENTRYPOINT ["python", "src/cli.py"]`. The root
`docker-compose.yml` uses `build: .`, so **the compose path runs uvicorn as
root**, healthchecks `/docs`, and sets no memory limit and no API key.
`docker/docker-compose.yml` is the sound one (memory 2g, cpus 2.0, `/health`,
`appendonly yes`) — but still sets no `PAAC_API_KEY`.

**Required fixes**

- Rewrite the manifest: current image tag, `securityContext` (`runAsNonRoot: true`, `readOnlyRootFilesystem: true`, `drop: [ALL]`), `resources.limits` (memory 2Gi, cpu 2), `PAAC_API_KEY` from a `Secret`, liveness/readiness probes on `/health`.
- Either move attestation storage to Redis, or set `replicas: 1` and document the constraint. Do not ship `replicas: 3` with per-pod state.
- Delete the root `Dockerfile` and root `docker-compose.yml`, or make them thin pointers to `docker/`.
- Set `PAAC_API_KEY` in every compose/manifest, and consider failing startup when it is unset outside an explicit dev mode.

---

# High findings

### H-1. No per-function scope isolation in the BMC encoding
`_verify_inner` creates **one** `SSAEnv` and **one** `StmtEncoder` outside the
`for func in ast.functions` loop, and encodes every function with
`func_path = BoolVal(True)`. All functions share a single SSA namespace, so
same-named variables alias across functions — function B's parameter `x`
continues from function A's final SSA version. Axioms are then encoded **once**,
after the loop, against the merged environment — i.e. against the *last*
function's values, not per-function.

This substantially defeats A-05's scoping. `_get_applicable_axioms` filters by the
modification's declared `func_name`, but `new_code` may contain arbitrarily many
functions. An agent can place risky logic in a differently-named function to dodge
target-scoped axioms such as `no_negative_balance`
(`target_functions: ["withdraw","deposit","transfer"]`).
**Fix:** a fresh `SSAEnv` per function, and per-function axiom encoding scoped by
that function's name.

### H-2. The 200 ms constant-time floor does not cover most response paths
Padding lives only in `BoundedModelChecker.verify()`'s `finally`. It is **not**
applied to compilation errors, `GroundingError` (citation rejection),
`CircuitOpenError`, rate-limit 429, auth 401, Pydantic validation failures, or the
`RecursionError` of M-3 — all of which return in ~1 ms. PCM mode never calls
`verify()` at all, so those responses return in ~0.005 ms.

§3.5/§6.2 and the README claim a 200 ms floor on *all verification responses*.
That is false, and a usable timing oracle remains: an attacker distinguishes
"failed to compile" from "was actually verified" by latency alone.
**Fix:** apply the floor in one place at the HTTP boundary — middleware or a
`/verify` wrapper — covering every exit path.

### H-3. Attestation binds the wrong axiom set
`/verify` computes `axiom_hash = engine.hash_axioms([a.condition for a in monitor.axioms])`
— **all** axioms — while verification enforced only `applicable`. A third party
validating the attestation concludes all five axioms were checked when they were
not. `_intercept_pcm` gets this right and uses `applicable`.
**Fix:** hash the axiom set actually enforced, and include the axiom ids in the signed payload.

### H-4. Roughly seven documented configuration knobs are fictional
Verified by grep across `src/` — read **zero** times:
`PAAC_CONSTANT_TIME_PADDING_S`, `PAAC_CB_FAILURE_THRESHOLD`, `PAAC_CB_COOLDOWN_S`,
`PAAC_Z3_MEMORY_LIMIT_MB`, `PAAC_Z3_CPU_LIMIT_SECONDS`, `PAAC_Z3_MAX_RETRIES`,
`PAAC_MAX_CONCURRENT_VERIFICATIONS`. Every one is a hardcoded constant.
(`AUDIT_FINDINGS.md` I-01 disclosed the padding case; it is still unfixed and the
others are undisclosed.)

Also: `PAAC_PCM_MODE` is never read, and `config/default.yaml` still carries a
**v5.0.0** header plus an `attestation:` block describing the **old HMAC**
`PAAC_ATTEST_KEY` rather than `PAAC_ATTEST_PRIVATE_KEY`. And the README's claim
that `PAAC_MAX_LOOP_BOUND` is the cap for "parse + Z3 + runtime" is wrong —
`sil_compiler.py` and `sil_runtime.py` honour it, but `verifier.py` hardcodes
`MAX_LOOP_BOUND = 10_000`, so the layers can disagree.
**Fix:** wire the knobs to config, or delete them from config and docs. A
configuration surface that silently ignores operator input is a production hazard.

### H-5. Two contradictory Dockerfiles; the compose path runs as root
See BLK-6.

### H-6. TCB protection omits two of the six TCB modules
`protect_tcb()` chmods only four modules:
```python
tcb_modules = ["src.core.verifier", "src.monitor.code_monitor",
               "src.core.tcb_protect", "src.core.failsafe"]
```
**`src.core.sil_compiler` (704 lines) and `src.core.sil_runtime` are left
writable** — including the lexer/parser/type-checker that enforces the
no-recursion and loop-bound guarantees, arguably the second most security-critical
file in the system. §3.5's "TCB source files marked read-only via chmod at
startup" therefore covers 4/6 modules.

Separately, the **module docstring is false**: it claims "Mark TCB source files
immutable (Linux `chattr +i` equivalent via ioctl `FS_IOC_SETFLAGS`)". The
implementation is `os.chmod` only — no ioctl, no `chattr`. The *function*
docstring is honest. Also, `_TCB_PROTECTED = True` is set even when zero files
were protected, so the no-op case never retries.
**Fix:** include all six modules; correct the module docstring; do not latch the
flag on failure.

---

# Medium findings

| ID | Finding |
|---|---|
| **M-1** | **`LoopBoundAnalyzer._prove_bound` is a tautology.** It asserts `bound_var == IntVal(K)` **and** `bound_var > IntVal(10000)`, then checks. UNSAT iff `K <= 10000` — Z3 is comparing two literals. This adds zero verification power over `if K <= 10000`. §4.6 / Abstract #7 call it an "SMT-proven iteration cap" with a "formal UNSAT certificate per loop": technically true, substantively vacuous. It also spawns a fresh `z3.Context` and `Solver` **per loop**. Recommend reframing as a *certificate-emitting* check rather than a proof, or making it prove something real (e.g. that the loop's own condition cannot remain true past the bound). |
| **M-2** | **Verifier-side encoding blowup.** `StmtEncoder` unrolls with `for _iteration in range(declared_bound)` in Python. I confirmed the compiler **accepts two nested loops at `bound 10000` each** → up to 10⁸ encoded statements. It fails closed (RLIMIT/timeout → `VerificationError` → static fallback → re-raise if the fallback says "safe"), so there is no unsafe acceptance — but a single small request can exhaust the 4-slot verify semaphore. §4.6 claims DoS *prevention*; the guarantee protects the *executed program*, not the *verifier*. Recommend bounding total unrolled statements (product of nested bounds), not just per-loop depth. |
| **M-3** | **Uncaught `RecursionError`; no input-size limit anywhere.** 400 nested parentheses — an **835-byte** payload — raises `RecursionError` from the parser. It is not a subclass of `SILError` and is **not** caught by `intercept_modification` (which catches only `CompilationError`/`SILError`, `VerificationError`, `GroundingError`), so it escapes **while the `FileLock` is held**. Measured: depth 300 fine, depth 400 raises. No source-length guard exists (`MAX_SOURCE`, `max_length`, `len(source)`, `MAX_PROGRAM`, `recursionlimit` — no matches in `src/`); `_sanitize_sil` checks only printable ASCII. Cheap remote fault injection. |
| **M-4** | **`FileLock` serialises everything.** `intercept_modification` wraps its whole body in `FileLock(self.lock_path, timeout=60)`, with `_VERIFY_SEMAPHORE = Semaphore(4)` *inside* it — so the semaphore is dead code and throughput is capped near 5 rps by the 200 ms floor. Above that, requests queue and after 60 s raise `filelock.Timeout`, which is **not** in the except clauses → unhandled 500. The rate limit (100/min/IP) permits well over capacity from a handful of IPs. This undercuts the §5.3 "p95 < 1 s under load" claim. |
| **M-5** | **Citation validation is theater.** `_CITATION_RE = re.compile(r".{20,}")` plus `"." in stripped`. The comment claims a "URL / DOI heuristic (Accepts: `https://doi.org/…`, `doi:10…`)". In reality `"aaaaaaaaaaaaaaaaaaa."` passes. Either implement URL/DOI validation or drop the grounding claim. |
| **M-6** | **Audit log created at import; no rotation; attacker-driven WAL growth.** `logging.FileHandler("audit.log")` executes at **module import**, creating a file in CWD — which would crash under the `--read-only` deployment that KNOWN_ISSUES R-2 recommends. No rotation → unbounded growth (contrast `main.py`, which correctly uses `rotation="10 MB"`). Additionally `_restore_state` calls `_save_checkpoint` on **every rejection**, appending to the WAL each time, so repeated rejected submissions inflate the WAL without bound. |
| **M-7** | **Verifier/runtime disagreement.** `MAX_INSTRUCTIONS = 100_000` vs `MAX_LOOP_BOUND = 10_000`. A BMC-certified-safe program with a 10,000-iteration loop and ≥10 body statements exhausts the instruction budget and raises `SILRuntimeError`. "Accepted" does not imply "executable". (The loop cap itself is correct — I verified the runtime loop logic is *not* off-by-one.) |
| **M-8** | **`result_bounded` does not implement its description.** `config/axioms.yaml` describes "Computed result must not exceed 1000000" but the condition is `result >= 0`. No upper bound is enforced anywhere, yet Table 5.2 lists it as a robust axiom. |
| **M-9** | **Auth failures are not rate limited; no `X-Forwarded-For` handling.** `security_middleware` returns 401 *before* `_check_rate_limit`, so wrong-key attempts are unlimited. `ip = request.client.host` with no forwarded-header logic means that behind any ingress or reverse proxy **all clients collapse into one bucket** (a 100/min global DoS); directly exposed, an attacker rotates source IPs. `_rate_counters` remains an unbounded `defaultdict` (I-02, still open). |
| **M-10** | **`/verify` leaks internal exception text.** `raise HTTPException(status_code=500, detail=str(exc))` bypasses the sanitising `panic_hook`, exposing filesystem paths and solver internals. |
| **M-11** | **Attestation store is in-memory and the key is ephemeral by default.** Without `PAAC_ATTEST_PRIVATE_KEY` a fresh keypair is generated per start (warned). `self._store` is an unbounded dict, never persisted or evicted — so `/attest/{id}` 404s after any restart, and the store grows with every acceptance. Figure 1 shows an "Ed25519 Cert Store / Export" component; no store or export exists. |
| **M-12** | **`LoopBoundReport` is dropped by the public API.** The README states the loop proof "travels with every verification result". True internally, but `verify()` returns `(safe, ce)` and only logs the summary; the `Verifier` façade returns `{"safe", "counterexample"}`; `/verify` never surfaces it. The certificate is not observable by callers. |
| **M-13** | **TCB line counts are understated.** §5.4 claims ~2,400 lines. Actual `wc -l`: `verifier.py` **1,013** (claimed ~780, +30%), `sil_compiler.py` 704, `sil_runtime.py` 166, `code_monitor.py` 481, `failsafe.py` 182, `tcb_protect.py` 103 → **2,649**. Also `code_monitor.py` lives at `src/monitor/`, not `src/core/` as the table implies. Total `src/` is 11,481 lines; the "tiny TCB" claim depends on a module boundary that should be stated explicitly. |

---

# Low findings

| ID | Finding |
|---|---|
| **L-1** | `lark>=1.1.9` is an **unused dependency** — `sil_compiler.py` imports no `lark` (hand-written lexer/parser). `src/core/sil_grammar.lark` is dead, and `docs/SIL_GRAMMAR.md` may describe a grammar that is not what's enforced. Needless supply-chain surface. |
| **L-2** | **Stale documentation.** `PAPER_CLAIMS_CHECKLIST.md` still says v5.0.0 / 260 tests / TCB ~2,123 / "Attestation uses HMAC-SHA256" (v7.0 uses Ed25519). `AUDIT_FINDINGS.md` is v5.0.0-era. `config/default.yaml` has a v5.0.0 header. README's Quick Start tags images `paac:v6.1` in a v7.0 README. |
| **L-3** | `registry_save` correctly uses `os.replace` (atomic rename) but does **not** `fsync` the temp file first, so a crash can leave a truncated file on some filesystems — a gap against the "crash-resilient" claim. |
| **L-4** | **CI has no quality gates.** `.github/workflows/ci.yml` runs only `python -m pytest tests/` — no `bandit`, `mypy`, or `ruff`, despite `PAPER_CLAIMS_CHECKLIST.md` asserting "Bandit: 0 HIGH. Mypy: 0 errors" and a `.pre-commit-config.yaml` existing. Those assertions are unenforced. No coverage gate, and no artifact-regeneration check (see BLK-5). |
| **L-5** | `robustness_score`'s docstring claims weighting by expected direction; no weighting is implemented. |
| **L-6** | `SelfVerifier.run()` reports `stage` as only ever 2 or 3; the documented "Stage 1" is never surfaced. |
| **L-7** | Two of six TCB stubs are exact duplicates modulo function name. |
| **L-8** | `AUDIT_FINDINGS.md` I-04 (z3-solver installed twice in `docker/Dockerfile`) is still present. |

---

# Paper claim cross-reference

Legend: **VERIFIED** = confirmed, adversarially where possible · **PARTIAL** = works with material caveats · **OVERCLAIM** = implemented but weaker than described · **NOT SUBSTANTIATED** = evidence absent or contradictory

| § | Claim | Status | Note |
|---|---|---|---|
| Abs. | 386 passing tests | **VERIFIED** | CI on exact SHA; 386 collected, 386 passed, 85.70 s |
| Abs. | Containerized service | **PARTIAL** | `docker/Dockerfile` sound; root Dockerfile/compose run as root (BLK-6/H-5) |
| Abs. | "mathematically guarantees that all code modifications preserve … safety properties" | **OVERCLAIM** | BLK-4 (axioms skippable, Z3-free "safe"), H-1 (no function scoping) |
| §3.2 | No recursion, direct or mutual, via call-graph DFS | **VERIFIED** | Probed 2-cycle and 3-cycle; both rejected with cycle path |
| §3.2 | No duplicate parameter names | **VERIFIED** | Probed; `SILError` raised |
| §3.2 | Loop bounds positive and within 10,000 cap | **VERIFIED** | Probed 0, −1, 10000, 10001, 999999999, missing-bound |
| §3.4 | `BMC(f,k) = pre_f ∧ semantics ∧ violation` | **VERIFIED** | `pre_cond` is a solver constraint, not a violation flag |
| §3.4 | UNSAT ⇒ accept, SAT ⇒ reject with counterexample | **VERIFIED** | Plus fail-closed Z3-failure fallback |
| §3.4 | 32-bit integer soundness bounds | **VERIFIED** | Applied to int params |
| §3.5 | Constant-time padding to 200 ms | **PARTIAL** | H-2: not applied on compile/grounding/auth/rate-limit/PCM paths |
| §3.5 | TCB files chmod read-only at startup | **PARTIAL** | H-6: 4 of 6 modules; docstring claims ioctl/chattr |
| §3.5 | All modification paths routed through Code Monitor | **VERIFIED** | Single `intercept_modification` entry point |
| §3.5 | SMT-proven loop iteration cap (10,000) | **OVERCLAIM** | M-1: the Z3 query is a literal-vs-literal tautology |
| §4.1 | Bootstrap structural invariant checking, 6 invariants | **NOT SUBSTANTIATED** | BLK-3: 6 tautological stubs, 4 axioms, translator unused |
| §4.1 | Python-to-SIL translator converts TCB sources | **OVERCLAIM** | Exists, but not in the self-verification path |
| §4.2 | PCM: agent submits proof; PAAC verifies it | **NOT SUBSTANTIATED** | BLK-1: 5 bypasses; no code↔proof binding |
| §4.2 | PCM proof checking < 10 ms | **VERIFIED** | 0.004–0.02 ms measured (trivially — see BLK-1) |
| §4.2 | Independent AST-based checker, no Z3 | **VERIFIED** | Uses Python `ast`; no Z3 import |
| §4.3 | Ed25519 signature over the specified payload | **VERIFIED** | Field-for-field match with §4.3 |
| §4.3 | Integrity: tampering invalidates the signature | **PARTIAL** | True for field tampering; false if the embedded key is replaced (BLK-2) |
| §4.3 | Non-repudiation without shared secret | **NOT SUBSTANTIATED** | BLK-2: no trust anchor; `/attest/verify` accepts forgeries |
| §4.3 | Key rotation; old attestations still verifiable | **VERIFIED** | `rotate_key` + `verify_with_public_key` |
| §4.3 | Attestation < 5 ms | **NOT MEASURED** | `cryptography` unavailable; Ed25519 signing is ≪5 ms, so plausible |
| §4.4 | CEGAR refinement gated on robustness score | **PARTIAL** | Implemented; not executed (needs Z3) |
| §4.5 | Differential verification of conservative extensions | **PARTIAL** | Sound encoding ("old safe ∧ new unsafe" → UNSAT); not executed |
| §4.6 | Three-layer loop enforcement (parse / Z3 / runtime) | **VERIFIED** | All three exist and fail closed; Z3 layer is vacuous (M-1) |
| §4.6 | "No agent code can execute a loop > 10,000 iterations" | **VERIFIED** | Parse + runtime both enforce; M-7 notes runtime is *stricter* |
| §4.7 | 43 mutants, 100% robustness, no vacuous axiom | **NOT SUBSTANTIATED** | BLK-5: mismatched denominators; artifacts describe a different axiom set |
| §5.2 | Per-axiom mutation table | **NOT SUBSTANTIATED** | BLK-5: not reproducible from any committed artifact |
| §5.3 | 200 ms constant-time floor | **PARTIAL** | H-2 |
| §5.3 | p95 < 1 s under load | **NOT SUBSTANTIATED** | M-4: `FileLock` serialisation caps throughput near 5 rps |
| §5.4 | TCB ~2,400 lines | **OVERCLAIM** | M-13: 2,649 actual; `verifier.py` 1,013 vs ~780 |
| §6.2 | Circuit breaker: 5 failures → OPEN, 60 s | **VERIFIED** | Exact match |
| §6.2 | Watchdog two-thread design | **VERIFIED** | Liveness 1 s, monitor 5 s |
| §6.2 | WAL, atomic registry save | **VERIFIED** | `os.replace`; L-3 notes missing `fsync` |
| §6.2 | Redis fallback degrades with warning | **VERIFIED** | `ConnectionError` → WAL + warning |
| §6.2 | Rate limiting 100 req/min/IP | **PARTIAL** | M-9: per-process, no forwarded-header handling |
| §6.2 | Z3 subprocess isolation | **VERIFIED** | RLIMIT_AS/CPU, IPC token, 3 retries. `/self-verify` bypasses it (BLK-3) |
| §6.3 | All 7 endpoints | **VERIFIED** | All present; auth covers all but `/health`, `/metrics` |
| §6.3 | `/verify` requires `X-API-Key` when set | **VERIFIED** | `secrets.compare_digest` (A-03) |
| §6.4 | Docker deployment | **PARTIAL** | BLK-6, H-5 |
| §7.1 | Stated limitations | **VERIFIED** | Accurate and commendably candid |
| §7.2 | Comparison table: PAAC "Yes" on all 7 columns | **OVERCLAIM** | Struct. Inv. and Attest. columns are not supported (BLK-2, BLK-3) |

## Security fixes A-01 … A-05

| ID | Fix | Status | Evidence |
|---|---|---|---|
| **A-01** | Under-bounded loops must return SAT | **VERIFIED** | Post-unroll `still_running` flag appended exactly once; C-01 duplicate removed with an explanatory comment. 4 tests. |
| **A-02** | Cache not poisonable externally | **VERIFIED** | `__cache` name-mangled; `_cache` property returns a copy; writes go through `_cache_update`. 4 tests. |
| **A-03** | Constant-time API key comparison | **VERIFIED** | `secrets.compare_digest` in `security_middleware`. 3 tests. |
| **A-04** | `multiprocessing` uses `spawn` | **VERIFIED** | `set_start_method("spawn", force=True)` at the top of `main.py`, before other imports. 2 tests. |
| **A-05** | Axioms filtered by `target_functions` | **PARTIAL** | `_get_applicable_axioms` is correct (empty/`*`/explicit). **But H-1 undermines it**: axioms are encoded once over a merged multi-function SSA environment, and filtering keys off the *declared* `func_name` while `new_code` may hold many functions. 5 tests, all single-function. |

Also fixed and confirmed from `AUDIT_FINDINGS.md`: C-01 (duplicate violation
flag), H-02/KI-002 (duplicate params), H-03/KI-003 (missing-return warning).
Still open: I-01 (padding config ignored — now H-4), I-02 (unbounded rate
counters — M-9), I-03 (`rollback()` does not replay), I-04 (double z3 install).

---

# Evidence appendix

### Evidence A — the 386-test claim

Two independent lines, because I could not run the suite locally.

1. **Static count.** `def test_` across `tests/test_*.py` totals **exactly 386**:
   52 + 48 + 43 + 38 + 30 + 23 + 21 + 18 + 13 + 12 + 12 + 11 + 11 + 9 + 8 + 8 + 7 + 5 + 5 + 4 + 4 + 4.
   There are **zero** `@pytest.mark.parametrize` decorators in the repo, so
   collected count equals definition count.
2. **CI on the exact SHA.** Run #86 (id `31304994128`), branch `main`, head
   `83423c4c` — identical to the audited HEAD:

```
2026-08-09T09:03:48.6368115Z collected 386 items
2026-08-09T09:05:13.4532039Z ===== 386 passed in 85.70s (0:01:25) =====
```

**Conclusion: VERIFIED.** Caveat: CI runs only `pytest`, with no lint, type, or
security gate (L-4).

### Evidence B — SIL compiler adversarial probes

Executed via `audit/v7.0/audit_sil.py`. All expected behaviours held:

```
[PASS] direct recursion        -> SILError: Recursion cycle detected: f -> f
[PASS] mutual recursion a->b->a-> SILError: Recursion cycle detected: a -> b -> a
[PASS] 3-cycle a->b->c->a      -> SILError: Recursion cycle detected: a -> b -> c -> a
[PASS] func f(x: int, x: int)  -> SILError: Duplicate parameter name 'x' in function 'f'
[PASS] bound 0                 -> SILError: Loop bound must be positive
[PASS] bound 10000 (at cap)    -> accepted
[PASS] bound 10001 (over cap)  -> SILError: exceeds global cap 10000
[PASS] while with NO bound     -> SILError: Expected token type KEYWORD
[PASS] undefined var / func    -> SILError
[PASS] no return stmt          -> accepted with SyntaxWarning   (KI-003)
[PASS] 300-function call chain  -> accepted in 7.2 ms
[CRASH] 400 nested parens      -> RecursionError, UNCAUGHT      (M-3)
[NOTE] two nested loops @10000 -> accepted -> 1e8 unrolled stmts (M-2)
```

### Reproduction scripts

Committed under `audit/v7.0/`. All run on stdlib-only Python 3.11 — **no Z3, no
PyPI access required** — which is what made the empirical findings possible in a
network-restricted environment.

| Script | Demonstrates |
|---|---|
| `audit_pcm.py` | BLK-1 — five PCM bypasses plus two controls; measures checker latency |
| `audit_sil.py` | Evidence B — compiler probes, M-2, M-3 |
| `audit_recursion.py` | M-3 — minimum crashing payload; absence of any size guard |
| `audit_mutants.py` | BLK-5 — mutant counts for current vs stale axiom sets; reconciliation |

```bash
cd /path/to/paac
python3.11 audit/v7.0/audit_pcm.py
python3.11 audit/v7.0/audit_sil.py
python3.11 audit/v7.0/audit_recursion.py
python3.11 audit/v7.0/audit_mutants.py
```

---

# Recommended path to GO

**Tier 1 — required for the paper.** Fix or retract the three unsupported
contributions: BLK-1 (PCM), BLK-2 (attestation trust anchor), BLK-3
(self-verification). Regenerate the mutation artifacts and restate the metric
consistently (BLK-5). Correct §5.4's TCB counts (M-13), the §5.2 table, the §7.2
comparison table, and the §3.5/§6.2 constant-time claim (H-2).

Retraction is a legitimate option and in places the better one. The core BMC
contribution, the SIL compiler's compile-time guarantees, and the A-01…A-05
hardening are real, independently verified, and sufficient for a strong paper on
their own.

**Tier 2 — required for production.** BLK-6 (Kubernetes manifest), H-1 (function
scoping), BLK-4 (fail closed on vacuous verification), H-4 (config knobs), H-5
(Dockerfiles), H-6 (TCB coverage), M-3 (`RecursionError` + input size cap), M-4
(`FileLock` serialisation), M-9 (rate limiting behind a proxy).

**Tier 3 — quality.** Remaining Medium and Low items; add `bandit`/`mypy`/`ruff`
and an artifact-regeneration check to CI (L-4).

---

## Closing note on scope and honesty

Two things deserve saying plainly.

First, this audit was commissioned with a stated expectation of "GO — Ready for
submission." I could not reach that conclusion. Three headline contributions do
not survive adversarial testing, and one of them I broke five different ways with
a script that runs in milliseconds. Reporting otherwise would defeat the purpose
of an independent audit — particularly for a system whose entire thesis is that
formal guarantees should replace trust.

Second, the strongest signal in this repository is `PAPER_CLAIMS_CHECKLIST.md`.
Its v5-era entries — `CORRECTED` for the zk-SNARK claim, `CORRECTED` for the
TCB size, `PARTIAL` for self-verification with a clear explanation of *why* the
stubs returned SAT — represent exactly the right scientific instinct. Somewhere
between v5 and v7 that instinct was displaced: the self-verification stubs were
rewritten into tautologies that pass, and the checklist was left to go stale
rather than updated. Restoring that document to currency, and letting it once
again say `PARTIAL` where the work is partial, would do more for this project's
credibility than any of the seven extensions.

The engineering here is better than the claims require it to be. The claims are
what need to change.

---

*Findings are traceable to specific files and lines in the audited commit.
Where I could not execute code because of the sandbox's PyPI restriction, that is
stated explicitly rather than inferred past.*
