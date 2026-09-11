# PAAC Audit Findings

**Date:** 2026-08-03
**Version:** v5.0.0
**Auditor:** Senior Release Engineer
**Scope:** Full codebase — src/, tests/, config/, docs/, docker/

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Total files audited | 52 |
| Critical issues | 1 |
| High issues | 4 |
| Medium issues | 7 |
| Low issues | 11 |
| Overall verdict | **CONDITIONAL PASS** — all critical/high issues fixed in Phase 2 |

---

## Critical Issues (Must Fix)

| ID | File | Issue | Severity | Fix |
|----|------|-------|----------|-----|
| C-01 | `src/core/verifier.py` | `StmtEncoder._encode_stmt` adds the post-loop `still_running` violation flag **twice** (lines 218–228 are a verbatim duplicate). This causes Z3 to receive a redundant `Or(...)` clause, doubling the violation weight and potentially producing spurious SAT results for loop-heavy programs. | CRITICAL | Remove the duplicate block (second `still_running` append). |

---

## High Issues

| ID | File | Issue | Severity | Fix |
|----|------|-------|----------|-----|
| H-01 | `src/core/runtime_monitor.py:103` | `eval(py_cond, {"__builtins__": {}}, dict(env))` — restricted `eval` with user-controlled `condition` string. Bandit B307. Even with empty builtins, crafted conditions can raise or leak. | HIGH | Replace with a safe expression evaluator that walks the SIL AST directly instead of calling `eval`. |
| H-02 | `src/core/sil_compiler.py` | `SILTypeChecker` does not detect duplicate parameter names (KI-002). `func f(x: int, x: int)` compiles silently; the second `x` shadows the first in the SSA environment, producing unsound verification results. | HIGH | Add a duplicate-parameter check in `_check_function`. |
| H-03 | `src/core/sil_compiler.py` | `SILTypeChecker` does not require a `return` statement (KI-003). A function that falls off the end returns `None` at runtime but the verifier encodes no return value, silently missing post-condition checks. | HIGH | Warn (not error) when no `ReturnStmtNode` is found in a function body. |
| H-04 | `.env.example` | Missing critical environment variables: `PAAC_API_KEY`, `PAAC_CERT_KEY`, `PAAC_PCM_LOG`, `PAAC_ATTEST_KEY`. Operators deploying from the example file will run with empty API key (no auth) and default HMAC keys. | HIGH | Add all security-relevant variables with placeholder values and comments. |

---

## Medium Issues

| ID | File | Issue | Severity | Fix |
|----|------|-------|----------|-----|
| M-01 | `src/pcm/certificate.py` | `import re` placed at the bottom of the file (line 290) after all code. Violates PEP 8 and causes confusion about module-level state. | MEDIUM | Move `import re` to the top of the file. |
| M-02 | `src/core/sil_runtime.py:44` | `import src.core.sil_runtime as _rt` inside `_tick()` — a module self-import on every tick call. Adds overhead and is a code smell. | MEDIUM | Read `MAX_INSTRUCTIONS` at module level or pass it as a parameter. |
| M-03 | `src/cegar/repair.py` | Unused imports: `ProgramNode`, `CounterExample`. Ruff F401. | MEDIUM | Remove unused imports. |
| M-04 | `src/coverage/axiom_coverage.py` | Unused import: `ExprEncoder`. Ruff F401. | MEDIUM | Remove unused import. |
| M-05 | `src/diffverify/diff_verifier.py` | Unused imports: `field`, `ExprEncoder`, `VerificationError`. Ruff F401. | MEDIUM | Remove unused imports. |
| M-06 | `src/pcm/proof_generator.py` | Unused imports: `field`, `ProgramNode`. Ruff F401. | MEDIUM | Remove unused imports. |
| M-07 | `src/mutation/report.py` | Unused imports: `asdict`, `MutantResult`. Ruff F401. | MEDIUM | Remove unused imports. |

---

## Low Issues

| ID | File | Issue | Severity | Fix |
|----|------|-------|----------|-----|
| L-01 | `src/cli.py` | `all_mods` variable assigned but never used (Ruff F841). | LOW | Remove unused variable. |
| L-02 | `src/core/self_verify.py` | `pad` variable assigned but never used in `_translate_stmt` (Ruff F841). `Any` imported but unused (Ruff F401). | LOW | Remove unused variable and import. |
| L-03 | `src/pcm/proof_checker.py` | `step_covered` variable assigned but never used in `Conclude` handler (Ruff F841). | LOW | Remove unused variable. |
| L-04 | `src/mutation/axiom_mutator.py` | `field` imported but unused (Ruff F401). | LOW | Remove unused import. |
| L-05 | `src/certificates/proof_cert.py` | `asdict`, `ExprEncoder` imported but unused (Ruff F401). | LOW | Remove unused imports. |
| L-06 | `docs/DEPLOYMENT.md` | Version header says "v4.2.0" — not updated for v5.0.0. Missing PCM configuration section. | LOW | Update version and add PCM/certificate env vars. |
| L-07 | `README.md` | Test count says "260 tests pass" — actual count is 355. | LOW | Update to reflect actual count. |
| L-08 | `config/default.yaml` | No PCM configuration section (`pcm_mode`, `pcm_audit_log`, `paac_cert_key`). | LOW | Add PCM config block. |
| L-09 | `src/core/verifier.py` | `_loop_exit_path` field on `StmtEncoder` is set but the `encode_stmts` loop only uses it via `current_path` reassignment — the logic is correct but the field name is misleading. | LOW | Rename to `_post_loop_path` for clarity. |
| L-10 | `tests/test_v5_features.py` | Unused imports: `hashlib`, `Axiom`, `SELF_AXIOMS`, `DiffStatus`, `run_axiom_mutation`. Ruff F401/I001. | LOW | Remove unused imports. |
| L-11 | `tests/test_mutation_testing.py` | Unused imports: `MutatedAxiom`, `MutantResult`. Ruff F401. | LOW | Remove unused imports. |

---

## Informational

| ID | File | Note |
|----|------|------|
| I-01 | `src/core/verifier.py` | `CONSTANT_VERIFICATION_TIME_S = 0.200` is hardcoded. The config file has `constant_verification_time_padding_s` but it is never read. Acceptable for now; document the discrepancy. |
| I-02 | `src/main.py` | `_rate_counters` is an unbounded `defaultdict` — under sustained load from many unique IPs it will grow without bound. Acceptable for a research prototype; add a note. |
| I-03 | `src/core/failsafe.py` | `rollback()` logs intent but does not actually replay history. Documented as future work. |
| I-04 | `docker/Dockerfile` | `pip install --only-binary=:all: z3-solver` then `pip install -r requirements.txt` — z3-solver is installed twice. Minor inefficiency. |

---

# v8 Session Findings

**Date:** 2026-09-10
**Scope:** `src/core/verifier.py`, `src/monitor/code_monitor.py`, `src/monitor/agent_adapter.py`, `src/pcm/proof_checker.py`
**Context:** PLAN_V8.md Step 0. Findings below were located by reading the
verification data path end to end, from the agent's submitted JSON to the Z3
query, rather than by running the existing suite (which passes and did not
catch any of them).

---

## Critical

| ID | File | Issue | Severity | Status |
|----|------|-------|----------|--------|
| C-02 | `src/core/verifier.py`, `src/monitor/code_monitor.py` | **Unsatisfiable precondition bypasses the entire verifier.** `_verify_inner` asserts `pre_cond` as a solver constraint (paper section 3.4, `solver.add(_z3_pre)`). Z3 then conjoins it with the axiom-violation disjunction. An unsatisfiable `pre_cond` such as `"1 == 0"` makes the whole query trivially UNSAT, so `verify()` reports `safe=True` for **any** payload and **no axiom is checked at all**. The value is attacker-controlled end to end: `AgentAdapter.propose_modification` reads it straight off the agent's JSON (`pre_cond=data.get("precondition", "true")`), and `intercept_modification` passes it through unvalidated. The only gates upstream were the circuit breaker and a source-citation format rule (20+ characters containing a dot), neither of which inspects `pre_cond`. Confirmed reachable through the production entry point: submitting `func compute(x: int) -> int { return -1; }` (violates `result_bounded`) with `precondition = "1 == 0"` and a valid-looking citation returned `{"status": "accepted"}` and wrote the payload to `_live_registry`. | CRITICAL | **FIXED** |

**Fix.** New `check_precondition_satisfiable()` in `src/core/verifier.py` checks
`pre_cond` on its own, in a fresh `z3.Context` and `Solver`, over the target
function's declared parameters, and raises the new
`PreconditionUnsatisfiableError` when no input can satisfy it. Called from
`intercept_modification` after compilation and **before** the `if self.pcm_mode:`
branch, so it covers both the BMC and PCM paths. A matching handler returns the
standard `{"status": "rejected", ...}` dict rather than letting the exception
escape, and logs the rejection reason and the offending `pre_cond` to the audit
log.

**Note on why an unsatisfiable precondition is always rejected rather than
ignored.** Silently dropping it would leave the modification to be verified with
no input constraint, which is not what the submitter asked for and hides the
fact that the submission was malformed or hostile. Rejection is the only
response that neither trusts the value nor discards information.

**Regression tests.** `tests/test_code_monitor.py`, a new file: the endpoint-level
behaviour had no test coverage at all before this, which is why the bypass
survived. Four spellings of the same contradiction (`"1 == 0"`, `"false"`,
`"x != x"`, `"x > 0 and x < 0"`) are asserted at both the gate-function level and
end to end through `intercept_modification`, so the gate is a real satisfiability
check and not a string blocklist.

**Correction to an earlier version of this entry.** The description above
originally said the exploit payload "unconditionally violates `result_bounded`",
and the first draft of the regression tests were built on that premise. That
premise is false, and C-03 below is why: `result_bounded` never fires for any
function, so `func compute(x: int) -> int { return -1; }` is accepted on the
axiom path too, entirely independently of the precondition. The sentence "no
axiom is actually checked" in the C-02 description is still literally true for
that payload, but it is true for **two independent reasons**, and only one of
them is C-02. The bypass itself is real and was confirmed by observing that a
*satisfiable* precondition and an *unsatisfiable* one produced different solver
behaviour; but `compute` + `return -1` was the wrong probe for demonstrating it,
because that payload is accepted either way.

The boundary tests were rewritten to use `counter_in_range: counter >= 0`
against `decrement`, where `counter` is a declared parameter and therefore
genuinely bound, so the axiom actually fires. That pair now establishes two
things the earlier version could not: the same body is **rejected** under
`pre_cond="true"` by a real axiom violation, and **accepted** under
`pre_cond="counter >= 1"`, which rules out the sole counterexample. The second
half matters more than it looks: it shows the C-02 fix rejects UNSAT
preconditions without weakening or ignoring SAT ones, which a gate that simply
rejected everything would also have passed the four bypass tests.

---

| ID | File | Issue | Severity | Status |
|----|------|-------|----------|--------|
| C-03 | `src/core/verifier.py`, `config/axioms.yaml` | **FIXED. See the "C-03 resolution" section near the end of this file for the fix, and C-04 for the second dead axiom set it uncovered. The description below is preserved as the original finding, in the present tense it was written in.** **Axioms over variables the function never binds are silently dropped, so 3 of the 5 shipped axioms never fire.** `_encode_axiom` compiles each axiom condition against the live SSA environment. When the condition names a variable the function never bound, `SILCompiler` raises `SILError("Undefined variable: ...")`; `_encode_axiom` treats that as *"axiom inapplicable to this function"*, logs at DEBUG, and returns `None`, and the caller drops it from the violation disjunction. The verifier then reports `safe=True` having checked nothing. Same fail-open shape as C-02, reached by a different route. | CRITICAL | **OPEN** |

**`result_bounded` is structurally dead, not merely sometimes inapplicable.** Its
condition is `result >= 0`, but nothing ever binds a variable named `result`:
the `ReturnStmtNode` branch of `StmtEncoder._encode_stmt` encodes the return
expression and discards it, `_ = self.expr_enc.encode(stmt.value)`. There is no
`result` in the environment for any function, ever, so this axiom cannot fire
for any input whatsoever. `grep` for the string `result` in `verifier.py` returns
no binding site, only the discard.

**`no_exit` and `no_network` are opt-in for the code being checked, which
inverts them.** Both target `["*"]`, so nominally every function. Their
conditions reference `exit_called` and `network_calls`, which `axioms.yaml`
documents as sentinel variables that "SIL programs that set ... will violate
this axiom". A function that simply never mentions the sentinel has no such
variable bound, so the axiom is dropped and the function passes. The safety
property therefore only applies to code that volunteers to be checked, which is
the opposite of what a safety axiom over `*` should mean.

**Observed effect, end to end.** For `func compute(x: int) -> int { return -1; }`,
which plainly violates the intent of `result_bounded: result >= 0` and is inside
that axiom's `target_functions`:

- `no_negative_balance`, `counter_in_range`: filtered out by `target_functions`
- `result_bounded`, `no_exit`, `no_network`: all three dropped as "inapplicable"

Zero axioms are checked, and the endpoint returns `{"status": "accepted"}`. The
startup line `Loaded 5 safety axioms` is true and misleading in the same breath:
loaded is not applied, and nothing reports the gap above DEBUG level.

**Pinned by test, not just documented.** `test_result_bounded_axiom_actually_rejects_negative_return`
in `tests/test_code_monitor.py` is marked `xfail(strict=True)`, so it fails if it
ever starts passing. Whoever fixes C-03 is forced to come back and remove the
marker, which keeps this entry honest.

**Not fixed here, deliberately.** The fix is a design decision, not a patch, and
there are at least three defensible options that differ in what they promise:
bind `result` at return and keep silent-skip for genuinely irrelevant axioms;
distinguish "inapplicable" from "unencodable" and fail closed on the latter; or
require axioms to declare the variables they need and reject at load time any
axiom whose variables no targeted function can bind. The third is the only one
that catches this class at configuration time rather than per verification. This
belongs with the Step 2 work in PLAN_V8.md, and it interacts with the caller
obligation work (0.6 / T1), so building it twice is the outcome to avoid.

**Why the existing suite missed it.** Nothing asserted that a specific axiom
*fires*. The tests assert that unsafe code is rejected, and for the payloads
used, rejection happened to come from elsewhere in the pipeline, so a dead axiom
was indistinguishable from a live one.

---

## High

| ID | File | Issue | Severity | Status |
|----|------|-------|----------|--------|
| H-06 | `src/monitor/code_monitor.py`, `src/core/failsafe.py` | **The circuit breaker counts correct rejections as failures, so an adversary can suspend verification for 60s at zero cost.** `record_failure()` is called on every rejection path: axiom violation (the `else` at line 465), `PreconditionUnsatisfiableError` (484), `VerificationError` (494), and PCM rejection (527). Only the third of those is a failure of the verifier; the others are the verifier *working*. After 5 consecutive rejections the breaker opens and `allow_request()` raises `CircuitOpenError` for 60 seconds. Since rejection is the expected outcome for hostile input, a hostile agent trivially reaches the threshold by submitting 5 bad modifications, and every subsequent proposal, including legitimate ones from other callers, is refused until the cooldown or the watchdog reset. Observed directly: the four bypass tests plus one boundary test opened the breaker and the next test received `{"status": "error", "http_status": 503}` instead of a verdict. | HIGH | **OPEN** |

**Severity reasoning: availability, not a safety bypass.** The open state returns
HTTP 503 and never `"accepted"`, so it fails closed and no unverified
modification gets through. Rated HIGH rather than CRITICAL on that basis. The
concern is that the mechanism whose job is to keep checking modifications can be
switched off for a minute by the very behaviour it is designed to catch, and the
breaker's own signal is meaningless: it cannot distinguish "Z3 is crashing and I
should stop" from "I am successfully rejecting an attack and should keep going".

**Correct fix, not applied here.** Separate the two counters. `record_failure()`
should mean "the verifier could not reach a verdict" (Z3 crash, timeout,
`VerificationError`), which is the condition the breaker exists for. A reached
verdict of "unsafe" should be recorded as a *success* of the mechanism, or on a
separate rejection-rate metric that alerts rather than trips. Note that the C-02
fix followed the existing convention and calls `record_failure()` on the new
rejection path, which makes this marginally easier to reach; that line changes
with the rest when H-06 is fixed, rather than being special-cased now to make
tests pass. `src/monitor/code_monitor.py` | **Redis startup probe is unbounded, so "graceful degradation" stalls every construction.** `CodeMonitor.__init__` builds a client and calls `.ping()`. The default `REDIS_HOST` is the bare hostname `"redis"`, which does not resolve outside a container network, so with no Redis reachable the probe blocks for an environment-dependent interval before `ConnectionError` is raised. Every `CodeMonitor` construction pays this before falling back to the WAL. The code comment says "degrade gracefully to WAL", and it does degrade correctly, but only after a long unbounded stall, which is not graceful for a service whose job is to keep verifying modifications. | HIGH | **FIXED** (second attempt) |

**First attempt, which did not work, recorded because the reasoning was wrong in
an instructive way.** Adding `socket_connect_timeout=1.0` and `socket_timeout=1.0`
looked like the obvious fix and was committed as such. It is not sufficient.
redis-py forwards `socket_connect_timeout` to `socket.create_connection`, which
calls `getaddrinfo` to resolve the host **before** it opens a socket, and
`getaddrinfo` is not covered by that timeout. A failing single-label lookup on
Windows can fall through DNS and then LLMNR/NetBIOS before giving up. Measured
cost with `socket_connect_timeout=1.0` already in place, taken from consecutive
log lines in one test run: WAL replay finished at `22:03:47.758`, the Redis
fallback warning appeared at `22:04:15.709`, so **28 seconds, per construction,
with the timeout supposedly in effect**. The original diagnosis in this file also
misattributed the cause to local security software intercepting loopback
connections; the actual cause is name resolution, which is why pointing
`REDIS_HOST` at `127.0.0.1` during earlier testing did not help either.

**Actual fix.** `_probe_redis()` runs the ping on a daemon thread and enforces a
wall-clock deadline with `Thread.join(timeout=...)`, falling back to the WAL if
the deadline passes. This bounds startup regardless of *why* the probe is slow:
name resolution, a blackholed address that never answers SYN, or a host that
completes the handshake and then stalls mid-command. The socket timeouts are
retained, and the deadline is set above them, so a socket-level failure still
gets the chance to report a precise error before the deadline abandons the
thread. The abandoned thread is safe to leak: it is a daemon, it writes only to
a local dict nothing reads afterwards, and `self.redis_client` goes unused once
`use_redis` is False.

**Lesson worth keeping.** A timeout parameter bounds the operation it is
documented to bound, not the whole call. The only way this was caught was by
comparing two log timestamps rather than trusting that the fix worked.

**Why this was invisible until now.** No prior test constructed a `CodeMonitor`
directly against a config without mocking Redis, so nothing exercised the probe.
It surfaced only because the C-02 regression tests are the first to instantiate
the real monitor.

---

## Informational

| ID | File | Note |
|----|------|------|
| I-05 | `src/pcm/proof_checker.py` | **PCM silently drops malformed preconditions instead of rejecting them.** `ProofChecker.check()` seeds its environment from `proof["preconditions"]` via `SymbolicEnv.assume()`, which calls `_parse_simple_constraint()`. That helper matches only `var op integer`, and returns `None` for anything else, at which point `assume()` returns without recording a bound and without raising. So `"x != x"` and `"1 == 0"` in a proof's `preconditions` block are ignored rather than rejected. This is not the C-02 bypass: PCM's `preconditions` field is a distinct mechanism from `CodeModification.pre_cond`, it never reaches Z3, and dropping the constraint makes the checker *more* conservative rather than less, since a missing bound means `entails()` is more likely to fail and reject. Logged rather than fixed, because the correct behaviour (reject a malformed or unsatisfiable proof precondition) is a change to PCM's contract and belongs with the Step 3 differential-fuzzing work in PLAN_V8.md, not bundled into the C-02 fix. |
| I-06 | `README.md` | Test-count drift continues. L-07 in the v5 audit recorded "says 260, actual 355". The README now claims 386. Unverified in this session: the full suite was not run to completion because each `CodeMonitor` construction takes roughly 30 seconds in this environment, so a full run is minutes long. PLAN_V8.md Step 0.1 still owns establishing the real number. |
| I-07 | `tests/` | **FIXED, and it was not cosmetic.** Originally logged as tidiness. It was actually producing confident wrong answers, so it is recorded in full below. **Interrupted runs leave state that changes later behaviour.** `live_registry.json`, `checkpoints.wal` and `audit.log` are written to the working directory and reloaded by the next `CodeMonitor` construction, which logged "loaded 1 function(s)" and "replayed 1 checkpoint(s)" from a previous aborted run. Tests that construct a real monitor are therefore order-dependent and not hermetic. Force-killing a run also leaves orphaned `multiprocessing` Z3 workers alive (six were observed), which compete for CPU and the `paac_monitor.lock` file lock and make subsequent runs slower still. Fixed by the autouse `_isolate_monitor_state` fixture in `tests/test_code_monitor.py`. **Upgraded from tidiness to a real defect once it started reporting false failures.** Two concrete cases: (1) the C-03 `xfail` test legitimately accepts an unsafe `compute`, which persists that payload to `live_registry.json`, and on the *next* run all four C-02 bypass tests loaded it back and failed their "unsafe code must not reach the registry" assertion, blaming the C-02 fix for a leftover written by a different test; (2) `CodeMonitor._circuit_breaker` is class-level and one instance per process, and because rejections call `record_failure()` (see H-06), five rejections opened the breaker and every later test received 503 instead of a verdict. Both were ordering artefacts that pointed the blame at working code. The fixture uses `monkeypatch.chdir(tmp_path)`, which covers all three on-disk paths at once, since `_WAL_PATH` and `_REGISTRY_PATH` in `src/core/failsafe.py` are relative and resolved at `open()` time and `CodeMonitor.lock_path` is built from `os.getcwd()`; setting the corresponding env vars from a fixture would be too late, as both are read at module import. It also clears `_live_registry` and replaces `_circuit_breaker` on both setup and teardown, and the axiom path passed to the monitor was made absolute so it survives the `chdir`. Verified with three consecutive randomly ordered runs: `13 passed, 1 xfailed`, exit 0, roughly 15s each. |
| I-08 | `src/monitor/code_monitor.py` | **The audit log path is resolved at import time against the current working directory.** `_audit_handler = logging.FileHandler("audit.log")` runs at module import with a relative path, so the audit trail lands wherever the process happened to be started, and a `chdir` after import does not move it. Confirmed incidentally: the hermetic test fixture chdirs into a `tmp_path`, and `audit.log` was still created in the repo root. Not a correctness bug for the tests, since the audit log is append-only and no code reads it back to make decisions, which is why I-07 could be fixed without touching it. It is worth fixing for deployment: this is the security-relevant record of every accepted and rejected modification, and "wherever the operator ran it from" is not a defensible location for it. An explicit `PAAC_AUDIT_LOG` path, resolved absolutely and created eagerly, would match how `PAAC_WAL_PATH` and `PAAC_REGISTRY_PATH` are already handled. |

---

## v8 Session Verification Summary

`tests/test_code_monitor.py`: **13 passed, 1 xfailed**, exit code 0. Confirmed on
four consecutive runs under `pytest-randomly`'s randomised ordering, roughly 15s
per run, with no `live_registry.json`, `checkpoints.wal` or `paac_monitor.lock`
left in the repository root afterwards.

The single `xfail` is `test_result_bounded_axiom_actually_rejects_negative_return`,
which pins C-03 and is `strict=True`, so it will fail loudly if C-03 is fixed and
the marker is not removed.

Suite runtime fell from 87.58s for 3 tests to 15.21s for all 14 once H-05 was
actually fixed, because the 28s Redis stall was being paid on every single
`CodeMonitor` construction.

**What is verified, stated precisely.** The C-02 precondition bypass is closed at
the production entry point, for four distinct spellings of an unsatisfiable
precondition, asserted both at the gate function and end to end through
`intercept_modification`. A genuine axiom violation is still rejected, and a
genuinely safe modification under a satisfiable precondition is still accepted,
both demonstrated against `counter_in_range`, an axiom that actually fires.

**What is not verified.** The repository-wide test count in `README.md`, still
claiming 386, remains unchecked; only this one module was run. C-03 and H-06 are
open and are documented above rather than fixed. The `no_exit` and `no_network`
axioms have not been exercised against a function that does bind their sentinel
variables, so the claim that they work in that case is untested either way.

---

## Second Pass: Repository-Wide Suite

The first pass verified one module. Running the whole suite changed the picture,
so this section supersedes the "What is not verified" paragraph above.

### Measured, not assumed

| Metric | Claimed | Measured |
|---|---|---|
| Test count | 386 passing (`README.md`) | 400 collected, **394 passed, 5 failed, 1 xfailed**, 206.41s |
| Suite status | green | **red**, 5 failures, none of them new |

The 5 failures were confirmed pre-existing and unrelated to the C-02, H-05 and
I-07 work by re-running the three affected files in isolation, where the same 5
failed (`5 failed, 63 passed`). Attributing them to the v8 changes without that
check would have been guesswork.

After the fixes below and the removal of the dead `proof_cert` tests, the suite
is **385 passed, 1 xfailed, exit 0, 194.94s**. The single `xfail` is the strict
marker pinning C-03.

| ID | File | Issue | Severity | Status |
|----|------|-------|----------|--------|
| H-07 | `src/monitor/watchdog.py` | **H-05 again, in a second location, and here it disabled the watchdog outright.** `_monitor_loop` opened a Redis connection and PINGed it *before* entering its `while` loop, with `socket_timeout=0.5` and no bound on name resolution. With the default host `redis` unresolvable, the monitor thread parked inside `getaddrinfo` for roughly 28 seconds before its first iteration. Two consequences, both observed as test failures: a genuine liveness stall went undetected for that entire window, and `stop()` could not retire the thread, because setting `_monitor_running = False` has no effect on a thread blocked in a resolver call. The check's only effect was to emit a log line; it did not change watchdog behaviour and did not influence `CodeMonitor`'s store selection, which `CodeMonitor` decides for itself and already logs. | HIGH | **FIXED** |

**Fix.** The Redis check was removed rather than bounded. A liveness monitor is
the wrong component to discover the state of an optional cache, and the loop now
performs no I/O at all, which is the property that makes it trustworthy.
Verified: `tests/test_watchdog_liveness.py` went from 2 failures to **7 passed**.

**The pattern, which matters more than either instance.** This is the third
place the same construct appears. `src/core/watchdog.py` still probes Redis in
its constructor with `socket_timeout=1` and no connect timeout; it is lower risk
only because its default host is `localhost`, which resolves, and its own
comment records that "the test hanging issue" was already fixed there once. The
recurring defect is treating a per-operation socket timeout as a bound on a
network call that begins with name resolution. It is not one, and redis-py
resolves before it connects.

| ID | File | Issue | Severity | Status |
|----|------|-------|----------|--------|
| M-01 | `src/mutation/cli.py` | **Report writing was platform-dependent and lost data.** All three report files were opened with bare `open(path, "w")`, so the encoding came from `locale.getpreferredencoding()`, which is cp1252 on a default Windows install. `to_markdown()` emits characters outside Latin-1 (status indicators such as U+1F534), so writing died with `UnicodeEncodeError` partway through and left a truncated file behind. The mutation report is the artefact backing the "43 mutants, 100% robustness" claim, so on Windows that evidence could not be produced at all. | MEDIUM | **FIXED** |

**Fix.** `encoding="utf-8"` on all three writes, plus `newline=""` on the CSV so
row endings do not depend on the platform. Verified: `tests/test_mutation_testing.py`
went from 2 failures to **43 passed**.

| ID | File | Issue | Severity | Status |
|----|------|-------|----------|--------|
| E-01 | environment | **A "VERIFIED" claim rested on a test that could not execute.** `test_spawn_start_method_configured` imports `src.main`, which imports `fastapi`. `fastapi`, `pydantic`, `uvicorn` and `prometheus-client` are all pinned in `requirements.txt` but were absent from the working virtualenv, so the test raised `ModuleNotFoundError` rather than asserting anything. `PAPER_CLAIMS_CHECKLIST.md` cited this exact test as evidence for "Multiprocessing uses spawn (A-04 fix), VERIFIED". | MEDIUM | **FIXED** |

**Fix.** Installed the four declared dependencies at their pinned versions. No
source change; the code was correct and the environment was incomplete.

**Why this one is worth a finding ID.** The failure mode is a claim-tracking
failure, not a code failure. "VERIFIED" had been recorded against the existence
of a named test rather than against a run of it. `PAPER_CLAIMS_CHECKLIST.md` now
carries a header saying so.

### Step 0 housekeeping completed

- **Version control restored.** The repository had no `.git` at all; history was
  lost when the folder was copied. Re-initialised and committed as a revert point
  before any deletions. The commit message states explicitly that the snapshot
  already contains the v8 work and is therefore not a pristine upstream baseline,
  because no such state is recoverable.
- **Relicensed to Apache-2.0.** `LICENSE` replaced (it previously granted no
  rights at all: "No license is granted to any person or entity"). Text taken
  verbatim from `apache.org/licenses/LICENSE-2.0.txt` rather than reproduced from
  memory. `NOTICE` added. 11 source files carried
  `Copyright (c) 2026 ... All rights reserved.`, which asserts the opposite of
  what Apache-2.0 grants; all now carry `SPDX-License-Identifier: Apache-2.0`.
- **`src/certificates/proof_cert.py` deleted** as legacy, superseded by
  `src/pcm/`. Also removed: the `TestProofCertificates` class (139 lines) and the
  `export-proof` CLI command (85 lines), which would otherwise have become an
  `ImportError` on invocation. The package directory is gone.
- **Correction to the plan for this step.** The plan said to drop the
  `PAAC_CERT_KEY` row from the README along with `proof_cert.py`. That would have
  been wrong: `PAAC_CERT_KEY` is read by `src/pcm/certificate.py` as well, which
  `code_monitor.py` imports and uses in PCM mode. The row stays. Deleting a
  module and deleting its documented configuration are not the same change, and
  the second one would have removed live documentation.

### Still open

- **C-03** and **H-06**, both documented above, both unfixed by choice.
- **`src/core/watchdog.py`** carries the H-07 pattern in milder form.
- **Em dashes** remain in pre-existing prose and comments (`verifier.py` 10,
  `code_monitor.py` 6, `AUDIT_FINDINGS.md` 9 at last count). Everything authored
  in this work is clean; the sweep across untouched files has not been done.
- **Windows-only verification.** Every number here was measured on Windows with
  Python 3.11.9. The cp1252 bug in M-01 is direct evidence that this codebase has
  platform-specific behaviour, so these results should not be assumed to
  transfer to the Linux CI target without being re-run there.

---

## C-03 closed, and what closing it uncovered

**Status: FIXED.** Three changes, all required together.

**1. `result` is now bound.** The `ReturnStmtNode` branch of `StmtEncoder._encode_stmt`
previously computed the return expression and discarded it
(`_ = self.expr_enc.encode(stmt.value)`), so no variable named `result` ever
entered the SSA environment and `result_bounded: result >= 0` could not be
encoded for any function. It now writes the encoded value to `result` as an
ordinary SSA variable, so the existing phi-merge handles branches.

Known limitation, stated rather than hidden: BMC encodes statements as
straight-line code and does not model `return` as transferring control, so in a
function with several returns on one path each rebinds `result` and an axiom sees
the last. Fixing that needs return-aware path conditions and is a separate
change.

**2. Axioms may declare `defaults`.** `Axiom.defaults` maps a variable name to
the value to assume when the verified function never binds it. Required for
`no_exit` and `no_network`, which target `["*"]` but reference sentinels an
ordinary function never assigns. A default is a semantic claim about absence
("code that never touched the sentinel did not exit"), so it is declared per
axiom rather than assumed globally by the verifier. Defaults never override
observed program state, and they bind a concrete Z3 value rather than a fresh
symbol; a fresh symbol would leave the sentinel unconstrained and Z3 would pick
a violating value, turning every function into a false positive.

**3. Unencodable safety axioms now fail closed.** `_encode_axiom` grew an
`on_unbound` policy. Preconditions keep the old skip behaviour, where an
unresolvable name is genuinely harmless. Safety axioms pass `on_unbound="error"`
and raise `AxiomNotEncodableError`. The `if not violation_flags: return True`
path in `_verify_inner` also now logs a warning naming the function, because
reaching it means nothing was checked.

**Verified:** `test_result_bounded_axiom_actually_rejects_negative_return` was an
`xfail(strict=True)`. After the fix it reported `XPASS(strict)`, which is a
failure, which forced it to be rewritten as a positive test. That is the strict
marker doing exactly the job it was added for. The payload
`func compute(x: int) -> int { return -1; }` is now rejected with a counterexample.

Two further tests were added to pin the shape of the fix, because "fail closed"
and "declare defaults" can each be broken in a way the other hides:
`test_sentinel_axioms_do_not_reject_functions_that_ignore_them` (defaults must
not cause mass false positives) and `test_sentinel_axiom_rejects_code_that_trips_it`
(the default must not make the axiom unfalsifiable).

### C-04: the same defect in PAAC's self-verification, found by the fix

| ID | File | Issue | Severity | Status |
|----|------|-------|----------|--------|
| C-04 | `src/core/self_verify.py` | **All four self-axioms were silently dropped for most TCB stubs, so PAAC's verification of its own trusted computing base was largely vacuous.** `SELF_AXIOMS` declares `self_nonneg_timeout`, `self_nonneg_loop_bound`, `self_safe_flag` and `self_nonneg_key_len`, each targeting `["*"]` while referencing `timeout_ms`, `loop_limit`, `safe_flag` and `key_len` respectively. Most stubs bind none of those, so every such axiom was dropped as "inapplicable" and self-verification reported success across the TCB while checking almost nothing on it. `PAPER_CLAIMS_CHECKLIST.md` cited this path as "PAAC can translate its own TCB to SIL stubs, VERIFIED, 6 stubs compile and verify". The stubs did compile; the axioms did not fire. | CRITICAL | **FIXED** |

**How it was found.** Not by inspection. Making C-03 fail closed turned 14 tests
red across `test_self_verify.py` and `test_v5_features.py`, all with
`AxiomNotEncodableError` naming `loop_limit`. A fail-closed check converted a
silent vacuity into a loud failure, which is the entire argument for preferring
it to a debug log.

**Fix.** `defaults` on all four self-axioms, each chosen so that absence is not a
violation: a stub with no timeout, no loop, no safe flag and no cache key cannot
be wrong about them. All 14 tests pass again, and now for a reason.

**Bearing on the bootstrap claim.** The claim that PAAC verifies its own TCB was
substantially weaker than it read, for the whole period this defect existed. The
stubs were translated and compiled, which is real work, but the structural
invariants were not being enforced on most of them.

---

## Step 1 complete: decomposition witnesses synthesised and confirmed

New module `src/decomp/`, tests in `tests/test_decomposition.py`, full write-up
in `docs/DECOMPOSITION.md`.

**Two confirmed decomposition attacks.** Each is a sequence of modifications that
PAAC accepts individually and whose composition violates
`counter_in_range: counter >= 0` when executed.

| Schema | Outcome | Holes | Steps accepted |
|---|---|---|---|
| A, call-chain precondition escape | WITNESS | `T=1, DEC=1, ARG=0` | 2 of 2 |
| B, sentinel accumulation | NOT EXPRESSIBLE | n/a | n/a |
| C, contract weakening across versions | WITNESS | `T1=1, DEC1=1, T2=2, DEC2=2` | 3 of 3 |

**Decomposition resistance: 0 of 2 confirmed witnesses rejected.** Denominator
stated because it is the weak part: these are attacks we thought to look for.

**Why the findings are not artefacts of my own encoding.** Synthesis is two
stages that cannot flatter each other. Z3 proposes hole values from a schema's
hand-written arithmetic; the proposal is then submitted to the real
`BoundedModelChecker` against the real `config/axioms.yaml`, and the composed
program is executed on the real `SILRuntime`. A candidate counts only if every
step is genuinely accepted and the execution genuinely violates the axiom.
Otherwise it is reported SPURIOUS. An error in a schema can waste a query; it
cannot manufacture a result. Both witnesses were in fact reported SPURIOUS twice
before the pipeline was correct, which is the mechanism working.

**Three things learned by running the attack rather than reading the code:**

- **A caller cannot be submitted alone.** `reset_counter` referencing a
  previously-accepted `decrement` fails with `Undefined function: decrement`,
  because each modification compiles as its own unit. The attacker must
  co-submit the callee. That is an accidental but real constraint, and it is why
  schema A's first formulation was spurious.
- **Uninterpreted calls are conservative for return values, not permissive.** A
  caller that *returns* a call result is correctly rejected, because the
  unconstrained symbol lets Z3 pick a violating value. The unsoundness is
  specifically the unchecked precondition at the call site. A schema conflating
  the two finds nothing, and reading that as "no attack exists" would have been
  wrong.
- **Schema C's first formulation returned a true UNSAT for a useless schema.**
  Holding the callee's body fixed and varying only its precondition cannot
  create a violation, since the value an axiom reads does not depend on the
  precondition. A correct UNSAT over a schema that cannot express an attack is
  worth nothing, which is why every UNSAT is reported next to its schema.

**New finding surfaced by this work:**

| ID | File | Issue | Severity | Status |
|----|------|-------|----------|--------|
| H-08 | `src/core/verifier.py`, `src/monitor/code_monitor.py` | **`verify()` accepts a single `pre_cond` for an entire program, so a multi-function submission cannot express one contract per function.** Combined with the requirement that a caller co-submit its callee, this means a submission containing a caller and its callee is verified under one shared precondition that cannot correctly describe both. This is adjacent to both decomposition witnesses and is part of why schema A's two-function submission is accepted. | HIGH | **OPEN** |

**Not closed, by design.** The defence is PLAN_V8 Step 2 and is not built.
`tests/test_decomposition.py` carries `xfail(strict=True)` tests asserting PAAC
rejects each witness; they fail today, and when Step 2 lands they will flip to
passes and the strict markers will force their own removal. Schema C is the
harder target: it would still occur under call-site obligation checking unless
replacing a function also re-verifies its callers.

---

## C-03 resolution

**Status: FIXED.** Suite: **398 passed, 2 xfailed, exit 0** (219.46s). The two
`xfail`s are strict markers pinning the two open decomposition vulnerabilities
described in the next section, not regressions.

Three changes, all required together. Any one alone is either useless or breaks
the system.

**1. Bind `result`.** `StmtEncoder._encode_stmt` now writes the encoded return
expression to the SSA name `result` instead of discarding it. That single line is
what makes `result_bounded: result >= 0` encodable for the first time. Confirmed
by the payload that motivated the finding: `func compute(x: int) -> int { return
-1; }` with `pre_cond="true"` is now **rejected with a counterexample**, where
before it was accepted having been checked against nothing.

**2. Declared defaults, `Axiom.defaults`.** Failing closed on unencodable axioms
without this would reject every submission in the system, because `no_exit` and
`no_network` target `["*"]` and name sentinels that ordinary functions never
assign. `config/axioms.yaml` now declares `exit_called: 0` and
`network_calls: 0`, so absence is bound to a concrete value and the axiom is
genuinely evaluated rather than skipped. The default is bound as a Z3 constant,
not a fresh symbol: a fresh symbol would leave the sentinel unconstrained and Z3
would pick `exit_called = 1` to satisfy the violation disjunction, turning every
function into a false positive.

Two tests hold this in place from both sides, because either alone is
insufficient: a function that ignores the sentinels must still be accepted, and a
function that sets `exit_called = 1` must still be rejected. The second is what
proves the default has not simply pinned the axiom to always-true, which would be
the same vacuous pass in a new costume.

**3. Fail closed, `AxiomNotEncodableError`.** An axiom that targets the function
under verification and cannot be encoded now raises instead of being dropped at
DEBUG level. `_verify_inner` also no longer returns `safe=True` from the
zero-violation-flags path without saying so: that path is reachable only when
nothing targeted the function at all, and it now logs at WARNING that reporting
safe because there is nothing to check is not the same as having checked
something.

`_encode_axiom` grew an `on_unbound` parameter for this. Preconditions keep the
old skip behaviour, which is correct for them: a precondition naming an
unresolvable variable cannot become the vacuous `False` constraint the C-02 gate
exists to catch. Safety axioms pass `"error"`. The two policies are routed
through one helper so they cannot drift apart.

### What the fail-closed change immediately uncovered

| ID | File | Issue | Severity | Status |
|----|------|-------|----------|--------|
| C-04 | `src/core/self_verify.py` | **All four self-verification axioms were dead, so PAAC's bootstrap self-check was largely vacuous.** `SELF_AXIOMS` contains `self_nonneg_timeout`, `self_nonneg_loop_bound`, `self_safe_flag` and `self_nonneg_key_len`. Every one targets `["*"]` and names a variable (`timeout_ms`, `loop_limit`, `safe_flag`, `key_len`) that most TCB stubs never bind, so every one was silently dropped for most stubs. Self-verification reported success across the TCB while checking almost nothing on it. `PAPER_CLAIMS_CHECKLIST.md` cited this path as "PAAC can translate its own TCB to SIL stubs, VERIFIED, 6 stubs compile and verify". The stubs did compile; the axioms did not fire. | CRITICAL | **FIXED** |

Found by the C-03 fix rather than by inspection: turning the silent skip into an
error made 14 tests fail immediately, all in the self-verification path, naming
`Undefined variable: loop_limit`. Fixed by declaring defaults on all four, each
chosen so that absence is not a violation, since a stub with no timeout and no
loop cannot be wrong about them.

Worth stating plainly: this is the same defect as C-03 in the component whose
entire purpose is for PAAC to check itself. A verifier that cannot detect its own
axioms being inert is the least reassuring place for this bug to live, and it is
the strongest argument in this file for the fail-closed change being worth the
disruption it caused.

**Cost of the change.** 14 tests failed on the first full run after it landed,
every one of them a genuine dead axiom rather than a false alarm. That is the
change working. A silent-skip design cannot produce that signal, which is exactly
why the axioms had been dead long enough to be documented as verified.

---

## Step 1: decomposition witnesses

Full write-up in `docs/DECOMPOSITION.md`, including the threat model, the schema
boundaries, and what the results do not establish. Summary of the findings:

| ID | Component | Issue | Severity | Status |
|----|-----------|-------|----------|--------|
| D-01 | `src/core/verifier.py` `ExprEncoder.encode` | **Call-site preconditions are unenforced, confirmed end to end.** Schema A witness, holes `T=1, DEC=1, ARG=0`. `decrement` is accepted for `counter >= 1`; `reset_counter` is accepted and calls `decrement(0)`. Both accepted by the real verifier. Executing `reset_counter(0)` violates `counter_in_range`. This was previously recorded as finding 0.6 from reading the encoder; it is now demonstrated through the production path. | HIGH | **OPEN** |
| D-02 | `src/monitor/code_monitor.py` `_live_registry` | **Replacing a function does not re-verify its callers.** Schema C witness, holes `T1=1, DEC1=1, T2=2, DEC2=2`. Three modifications, each safe under its own contract, all accepted. The third replaces `decrement` with a version demanding more of callers; the caller verified against the previous contract is never re-examined and now breaks. | HIGH | **OPEN** |

Both are pinned by `xfail(strict=True)` tests in `tests/test_decomposition.py`,
so the defence cannot land without those markers being removed.

**D-02 is the more fundamental of the two, and the distinction matters for the
fix.** D-01 arises because the call site never had a covering proof. D-02 is a
proof that existed and was invalidated. So D-02 survives any amount of extra
scrutiny applied to the incoming modification, because the modification that
breaks the system is not the one that looks wrong. Closing it requires
re-verifying the composed program, which is why PLAN_V8 Step 2's T1 tier cannot
be reduced to "check submissions harder".

**Two negative results worth recording.**

Schema B is reported NOT_EXPRESSIBLE rather than UNSAT. SIL has no globals and no
heap, so the `exit_called` and `network_calls` sentinels cannot carry state
between modifications; the schema has no object to range over. Calling that UNSAT
would imply a solver had searched a space and found it empty. This is also the
clearest illustration of PLAN_V8 section 2 from the attacker's side: SIL's
restriction removes the entire attack class, and it would return the moment
globals or a heap were added.

Co-submission does not defend D-01. `SILCompiler` rejects calls to undefined
functions, so a caller must carry its callee, which puts the callee in front of
the verifier at the same moment as the call. It is still accepted. This was found
by running the schema, not by reading the code, and it eliminates the first
defence most people would propose.

**Methodological note, because it is what makes the findings defensible.**
Synthesis has two stages that cannot flatter each other. Z3 proposes hole values
from a hand-written arithmetic characterisation; the real `BoundedModelChecker`
and the real `SILRuntime` then decide whether a candidate is a finding. A wrong
schema costs a false lead and is reported as SPURIOUS, never as a result. This
was not hypothetical: an early schema C was self-contradictory and returned
UNSAT, and an early schema A produced a candidate the runtime did not corroborate.
Both were caught by stage 2 rather than by inspection.

The outcome vocabulary keeps DEFENDED separate from SPURIOUS for the same reason.
"The composition is genuinely unsafe and PAAC refused a step" is evidence for the
system and belongs in the results; "the schema arithmetic was wrong" is not a
result at all. Collapsing them would let a broken schema masquerade as a defence.

---

## H-06 Resolution

Supersedes the "Still open" line in the second pass that listed C-03 and H-06 as
unfixed by choice. Both are now closed. C-03's resolution is recorded above with
C-04; H-06's is here.

| ID | Status |
|----|--------|
| H-06 | **FIXED** |

The breaker called `record_failure()` on every rejection path. Three of those are
the verifier *working*, and they now record a success instead:

| Path | Before | After | Why |
|---|---|---|---|
| Axiom violation found (`safe` is False) | failure | **success** | A verdict was reached. The modification is refused; the mechanism performed. |
| `PreconditionUnsatisfiableError` | failure | **success** | The C-02 gate firing is the gate doing its job. |
| PCM proof rejected | failure | **success** | The proof checker correctly refused a proof. |
| `VerificationError` | failure | failure | **No verdict produced**: Z3 timeout, crashed subprocess, unknown result. This is the only condition a breaker should trip on. |
| `AxiomNotEncodableError` | n/a | failure | New with C-03. The axiom set cannot be evaluated, so retrying cannot help until an operator changes configuration. |

The modification is still rejected in every one of those cases. Only the
breaker's bookkeeping changed.

**Why it mattered.** The breaker could not distinguish "Z3 is broken, stop
retrying" from "I am successfully catching an attack, keep going". Since
rejection is the *expected* outcome for hostile input, an adversary reached the
five-failure threshold with five deliberately bad submissions and suspended all
verification for the 60 second cooldown, at no cost and with no privileges. It
failed closed rather than open, returning HTTP 503 rather than accepting
anything, which is why this was rated HIGH rather than CRITICAL. The problem was
that the component whose job is to keep checking modifications could be switched
off by the very behaviour it exists to catch.

**Blast radius of the change: none outside this file.** Every circuit breaker
test drives `record_failure()` directly on a `CircuitBreaker` instance
(`tests/test_failsafe.py`, `test_failsafe_simulation.py`, `test_production.py`,
`test_watchdog.py`, and the watchdog reset test), so they exercise the breaker's
own state machine, which was not touched. Only the choice of which call sites
report a failure changed.

**One stale comment corrected.** The `_isolate_monitor_state` fixture docstring
in `tests/test_code_monitor.py` cited rejection-counts-as-failure as a reason the
fixture exists. That cause is gone, so the note now says so. The reset itself
stays: the breaker is shared process-wide mutable state, and a test inheriting it
is order-dependent regardless of the current bookkeeping rules.

### Added: reproduction script for the decomposition results

`scripts/run_decomposition.py`, with `--json` and `--timeout-ms`. PLAN_V8 section
5 requires the solver queries to be rerunnable from a committed script, and
section 9 requires every number to trace to a command. The script prints each
schema's outcome next to its boundary and hole range, and prints the summary
counts with the denominator, so a result cannot easily be quoted without its
qualifier. It exits 0 whatever the outcomes are: a witness is a research result,
not a build failure, and making the script fail on one would create pressure to
stop looking.

### Correction: work duplicated in this pass

Recorded because the no-lie contract applies to the process as well as the
product. Partway through this session the earlier commits
(`ac5b32c`, `5c1bc2b`) had dropped out of my working context, and I rebuilt C-03,
C-04 and the decomposition module from scratch, then overwrote the committed
`docs/DECOMPOSITION.md` and `tests/test_decomposition.py` with weaker versions of
work that already existed. The rebuilt documentation lacked D-01 and D-02
entirely, because the second attempt had not yet confirmed those witnesses.

Caught by reading `git log` after noticing the README described findings
(D-01, D-02, C-04) that "did not exist". The overwrites were reverted with
`git checkout` and only the genuinely new work was kept: the H-06 fix, the
reproduction script, and two unused-import removals. Nothing was lost, because
the earlier work had been committed. Had it not been, it would have been.
