# PAAC Production Audit Report

**Date:** 2026-08-02
**Auditor:** Senior Security Auditor
**System:** PAAC (Provably Aligned AI Core)
**Version:** v4.1.0
**Commit:** 6383603

---

## Executive Summary

PAAC v4.1 is a formal verification wrapper for self-modifying AI code. After a
zero-trust audit of the entire codebase against the published paper and industry
best practices, the verdict is **CONDITIONAL FAIL**. The system has a sound
engineering foundation — real Z3 BMC, SSA encoding, circuit breaker, WAL
persistence, and subprocess isolation are all correctly implemented. However,
five issues prevent unconditional production approval: (1) the verifier is
**unsound for under-bounded loops** — a program can pass verification and then
raise a runtime exception, breaking the core safety guarantee; (2) the
**in-process verification cache is mutable and can be poisoned** by any code
running in the same process; (3) the **API key comparison uses `!=` instead of
`secrets.compare_digest`**, creating a timing side-channel on the authentication
path; (4) the **multiprocessing fork-under-threads** pattern causes Z3 subprocess
crashes under concurrent load, confirmed in testing; and (5) **axiom
`target_functions` is parsed but never enforced** — all axioms are applied to
all functions regardless of their declared scope. None of these are
insurmountable, but items 1 and 2 must be fixed before any production deployment.

---

## Key Findings

| ID   | Severity | Title                                              | Status |
|------|----------|----------------------------------------------------|--------|
| A-01 | CRITICAL | Verifier unsound for under-bounded loops           | OPEN   |
| A-02 | HIGH     | In-process cache is mutable and poisonable         | OPEN   |
| A-03 | HIGH     | API key comparison not constant-time               | OPEN   |
| A-04 | HIGH     | multiprocessing fork-under-threads crashes Z3      | OPEN   |
| A-05 | HIGH     | axiom target_functions never enforced              | OPEN   |
| A-06 | MEDIUM   | Division by zero silently accepted by verifier     | OPEN   |
| A-07 | MEDIUM   | Missing return statement not enforced              | OPEN   |
| A-08 | MEDIUM   | Duplicate parameter names silently accepted        | OPEN   |
| A-09 | MEDIUM   | Rate limiter dict grows unboundedly (memory leak)  | OPEN   |
| A-10 | MEDIUM   | WAL and registry store raw source code in plaintext| OPEN   |
| A-11 | MEDIUM   | Class-level mutable state — cross-instance sharing | OPEN   |
| A-12 | LOW      | TCB protection is filesystem chmod only            | OPEN   |
| A-13 | LOW      | Integer overflow not modeled (unbounded Z3 Int)    | OPEN   |
| A-14 | LOW      | Paper <120ms claim contradicts 200ms padding floor | OPEN   |
| A-15 | LOW      | quicksort.sil is not a real sort (no array ops)    | OPEN   |

---

## Paper Claim Compliance Matrix

| Claim                              | Paper § | Implemented? | Passes Test? | Notes                                              |
|------------------------------------|---------|--------------|--------------|---------------------------------------------------|
| BMC with SSA encoding              | 3.4     | YES          | YES          | SSA phi-node merge bug was fixed in this pass     |
| Loop unrolling                     | 3.4     | YES          | PARTIAL      | Unsound for under-bounded loops (A-01)            |
| Phi-node merging for if/else       | 3.4     | YES          | YES          | Fixed: exprs_then snapshot before restore()       |
| Axioms enforced as SMT constraints | 3.4     | YES          | PARTIAL      | target_functions not enforced (A-05)              |
| Counterexamples extracted          | 3.4     | YES          | YES          | Backdoor: ce = x=57005                            |
| Rollback restores state            | 3.4     | YES          | YES          | Restores to last accepted checkpoint              |
| <120ms verification                | 3.4     | NO           | NO           | Contradicts 200ms padding; actual: 200ms–5s       |
| Constant-time 200ms padding        | 3.5     | YES          | YES          | Applied in verify(), not _verify_inner()          |
| Read-only memory for TCB           | 3.5     | PARTIAL      | PARTIAL      | chmod 0o444 only; no cryptographic integrity      |
| IPC authentication                 | 3.5     | YES          | YES          | 32-byte token, constant-time compare              |
| TCB ~500 lines                     | 3.5     | NO           | NO           | Actual: ~1,600 lines across 6 core files          |
| SIL grammar: int, bool, string     | 3.2     | YES          | YES          |                                                   |
| SIL grammar: array type            | 3.2     | YES          | YES          | Z3 Array(IntSort, IntSort)                        |
| SIL grammar: unary operators       | 3.2     | YES          | YES          | not, unary minus                                  |
| SIL grammar: no recursion          | 3.2     | YES          | YES          | Call-graph DFS cycle detection                    |
| SIL grammar: bounded while loops   | 3.2     | YES          | YES          | Parser enforces bound keyword                     |
| Quicksort passes verification      | 4       | PARTIAL      | YES          | Example is not a real sort (A-15)                 |
| Backdoor fails verification        | 4       | YES          | YES          | SAT with ce: x=57005                              |
| Z3 subprocess isolation            | 3.5     | YES          | PARTIAL      | Crashes under concurrent load (A-04)              |
| RLIMIT_AS + RLIMIT_CPU             | 3.5     | YES          | YES          | Linux only; macOS not enforced                    |

---

## Detailed Findings

### A-01: [CRITICAL] Verifier Unsound for Under-Bounded Loops

**File:** `src/core/verifier.py:L228-L248` (`StmtEncoder._encode_stmt`, WhileStmtNode branch)

**Description:**
The BMC loop unrolling unrolls the loop exactly `bound` times and sets the
post-loop exit path to `And(entry_path, Not(entry_loop_cond))`. This is sound
only when the loop terminates in fewer than `bound` iterations. When the loop
requires exactly `bound` or more iterations to terminate, the verifier produces
a false UNSAT — it reports the program as safe when it would raise a runtime
exception.

**Evidence:**
```python
# Program: loop needs 5 iterations, bound=3
code = '''
func under_bound() -> int {
    x = 0;
    while (x < 5) bound 3 { x = x + 1; }
    assert x == 5;
    return x;
}
'''
# Verifier: safe=True (UNSOUND)
# Runtime:  RAISES SILRuntimeError("Loop bound 3 exceeded")
```
Confirmed by direct execution. The verifier and runtime disagree on safety.

**Impact:**
An adversarial agent can submit a program that passes formal verification but
raises an unhandled exception at runtime. This breaks the core safety guarantee
of the system. The paper's claim that "only verified-safe modifications are
applied" is violated.

**Recommendation:**
Either (a) require that `bound >= actual_iterations` and add a runtime check
that raises `VerificationError` if the loop terminates due to bound exhaustion
rather than condition becoming false, or (b) add a violation flag for the case
where the loop condition is still true after `bound` unrollings (i.e., add
`And(current_path, loop_cond_after_N_iterations)` as a violation).

**Status:** OPEN

---

### A-02: [HIGH] In-Process Verification Cache Is Mutable and Poisonable

**File:** `src/core/verifier.py:L432` (`BoundedModelChecker._cache`)

**Description:**
The SHA-256 cache (`self._cache: dict[str, tuple[bool, str | None]]`) is a
plain Python dict on the `BoundedModelChecker` instance. Any code running in
the same process — including SIL programs executed via the runtime, or a
compromised dependency — can access and mutate it via `bmc._cache[key] = (True, None)`,
marking any unsafe program as safe. There is no integrity protection on the
cache entries.

**Evidence:**
```python
bmc._cache[h1] = (True, None)   # poison: mark unsafe program as safe
safe, _ = bmc._verify_inner(ast1, [], 5000)
# Returns safe=True for a program containing assert false
```
Confirmed by direct execution.

**Impact:**
A compromised dependency or a future code path that exposes the BMC instance
could silently disable verification for any function. This is a complete bypass
of the safety guarantee.

**Recommendation:**
Make the cache read-only after each write (use a frozen structure or HMAC-sign
each entry). At minimum, document that the cache must not be accessible to
untrusted code and add a `__slots__` or property guard.

**Status:** OPEN

---

### A-03: [HIGH] API Key Comparison Not Constant-Time

**File:** `src/main.py:L155`

**Description:**
The API key is compared using Python's `!=` operator:
```python
if key != _API_KEY:
```
Python string comparison short-circuits on the first differing byte, leaking
the length and prefix of the correct API key via timing measurements. The IPC
token uses `secrets.compare_digest` correctly, but the API key does not.

**Evidence:**
```
grep -n "compare_digest\|key != _API_KEY" src/main.py
155:        if key != _API_KEY:
# No compare_digest usage for API key
```

**Impact:**
An attacker making thousands of requests with varying key prefixes can recover
the API key character by character via timing analysis. In a high-latency
network this is harder but not impossible, especially from a co-located attacker.

**Recommendation:**
Replace `key != _API_KEY` with
`not secrets.compare_digest(key.encode(), _API_KEY.encode())`.

**Status:** OPEN

---

### A-04: [HIGH] multiprocessing Fork-Under-Threads Crashes Z3 Subprocess

**File:** `src/core/verifier.py:L510-L530` (`_verify_subprocess`)

**Description:**
The verifier spawns Z3 subprocesses using `multiprocessing.Process` with the
default `fork` start method. Python's `fork` is unsafe when called from a
multi-threaded process (the FastAPI server uses threads for request handling).
The forked child inherits all parent thread locks in an unknown state, causing
Z3 to crash with non-zero exit codes under concurrent load.

**Evidence:**
Load test with 4 concurrent workers using subprocess isolation: 100% failure
rate. All 20 requests returned "Z3 subprocess crashed 3 times consecutively."
The load test was only made to pass by bypassing subprocess isolation and
calling `_verify_inner` directly.

**Impact:**
Under any concurrent production load, the Z3 subprocess will crash, triggering
the static fallback analyzer. The static fallback only catches `assert false`
and literal division by zero — it misses all other safety violations. This
effectively disables formal verification under load.

**Recommendation:**
Set `multiprocessing.set_start_method("spawn")` at process startup, or use
`multiprocessing.get_context("spawn").Process(...)` per call. The spawn method
is safe under threads but has higher startup overhead (~100ms per call).

**Status:** OPEN

---

### A-05: [HIGH] Axiom target_functions Field Never Enforced

**File:** `src/core/verifier.py:L619-L622` (`_verify_inner` axiom loop);
`src/axioms/axiom_parser.py:L14` (`Axiom.target_functions`)

**Description:**
The `Axiom` dataclass has a `target_functions` field (e.g., `["withdraw", "deposit"]`),
and `config/axioms.yaml` uses it to scope axioms to specific functions. However,
`_verify_inner` applies every axiom to every function in the program, completely
ignoring `target_functions`. The field is parsed and stored but never read during
verification.

**Evidence:**
```python
# Axiom scoped to ["withdraw"] only
axiom = Axiom('no_neg', '', 'balance >= 0', ['withdraw'])
# Applied to a function named 'completely_unrelated' — still applied
# (returns safe=True only because 'balance' is not in scope, not because
#  target_functions was checked)
```

**Impact:**
Axiom scoping is a documented feature that operators rely on to write targeted
safety policies. Its silent non-enforcement means: (a) operators believe their
axioms are scoped when they are not, creating a false sense of security; and
(b) axioms that happen to share variable names with unrelated functions may
produce unexpected rejections or false positives.

**Recommendation:**
In `_verify_inner`, filter axioms before encoding:
```python
applicable = [a for a in axioms
              if "*" in a.target_functions or func.name in a.target_functions]
```
Apply this filter per-function, not globally.

**Status:** OPEN

---

### A-06: [MEDIUM] Division by Zero Silently Accepted

**File:** `src/core/sil_compiler.py` (type checker); `src/core/verifier.py:L163` (ExprEncoder)

**Description:**
`x / 0` compiles and verifies without error. Z3's integer division by zero
returns an uninterpreted value (implementation-defined), producing potentially
unsound verification results. The static fallback catches only literal `/ 0`
(e.g., `x / 0`), not symbolic division by zero (e.g., `x / y` where `y` could
be zero).

**Evidence:**
```python
code = 'func div_zero(x: int) -> int { y = x / 0; return y; }'
# Compiles OK, verifies safe=True
```

**Impact:**
Programs with division by zero pass verification and may produce undefined
behavior at runtime. The runtime uses Python's `floordiv` which raises
`ZeroDivisionError` — an unhandled exception that bypasses the safety guarantee.

**Recommendation:**
Add a division-by-zero violation flag in `StmtEncoder`: for every division
operation, add `And(path_cond, right == 0)` as a violation flag.

**Status:** OPEN

---

### A-07: [MEDIUM] Missing Return Statement Not Enforced

**File:** `src/core/sil_compiler.py:L490-L510` (`SILTypeChecker._check_function`)

**Description:**
The type checker does not verify that all control-flow paths through a function
end with a `return` statement. A function declared `-> int` with no `return`
compiles successfully. At runtime, `SILRuntime.execute` returns `None` for
functions that fall off the end, which will cause a `TypeError` if the caller
expects an integer.

**Evidence:**
```python
c.compile('func f(x: int) -> int { x = x + 1; }')
# Compiles OK — no SILError raised
```

**Impact:**
Functions that pass verification can produce `None` at runtime, causing
downstream `TypeError` exceptions that bypass the safety guarantee.

**Recommendation:**
Add a control-flow completeness check in `SILTypeChecker._check_function`:
verify that every path through the function body ends with a `ReturnStmtNode`.

**Status:** OPEN

---

### A-08: [MEDIUM] Duplicate Parameter Names Silently Accepted

**File:** `src/core/sil_compiler.py:L460` (`SILParser.parse_function`)

**Description:**
A function with duplicate parameter names (e.g., `func f(x: int, x: int)`)
compiles without error. The second `x` silently shadows the first in the type
checker's `current_env` dict. In the verifier's SSA environment, both
parameters are declared with the same base name, causing the second
`declare_param` to overwrite the first's Z3 variable.

**Evidence:**
```python
c.compile('func f(x: int, x: int) -> int { return x; }')
# Compiles OK — no SILError raised
```

**Impact:**
Duplicate parameters produce incorrect SSA encoding, potentially causing the
verifier to miss safety violations or produce false positives.

**Recommendation:**
In `parse_function`, check for duplicate parameter names:
```python
seen_params = set()
for p in params:
    if p.name in seen_params:
        raise SILError(f"Duplicate parameter name: {p.name}")
    seen_params.add(p.name)
```

**Status:** OPEN

---

### A-09: [MEDIUM] Rate Limiter Dict Grows Unboundedly

**File:** `src/main.py:L97-L107` (`_check_rate_limit`)

**Description:**
`_rate_counters` is a `defaultdict(list)` that accumulates one entry per unique
client IP address. The per-IP timestamp list is pruned on each request, but the
IP key itself is never removed from the dict. Under a distributed denial-of-service
attack using spoofed source IPs, this dict grows without bound, consuming all
available memory.

**Evidence:**
```python
# _rate_counters[ip] = [t for t in window if now - t < _RATE_WINDOW_S]
# The IP key is never deleted even when its list becomes empty
print('Global cleanup of stale IPs:', False)  # confirmed
```

**Impact:**
An attacker sending one request from each of N unique IPs creates N dict entries
that are never freed. With 1 million unique IPs, this consumes ~100 MB of memory
and degrades performance.

**Recommendation:**
Use a bounded LRU cache (e.g., `functools.lru_cache` or `cachetools.TTLCache`)
for the rate limiter, or periodically evict IPs whose timestamp lists are empty.

**Status:** OPEN

---

### A-10: [MEDIUM] WAL and Registry Store Raw Source Code in Plaintext

**File:** `src/core/failsafe.py:L107` (`wal_append`); `src/core/failsafe.py:L155` (`registry_save`)

**Description:**
The WAL file (`checkpoints.wal`) and registry (`live_registry.json`) store the
full source code of every submitted function modification in plaintext JSON.
These files are written to the working directory with no access controls beyond
the process's umask. In a shared-host deployment, other processes can read the
source code of all submitted modifications.

**Evidence:**
```
checkpoints.wal contains:
{"func_name": "sq", "new_code": "func sq(x: int) -> int { y = x * x; ... }",
 "source_citation": "https://doi.org/10.1234/example", ...}
```

**Impact:**
Source code and citations submitted by one tenant are readable by any process
with filesystem access. In a multi-tenant deployment this is a confidentiality
violation.

**Recommendation:**
Set restrictive file permissions (`0o600`) on WAL and registry files at creation.
For multi-tenant deployments, encrypt at rest using a per-tenant key.

**Status:** OPEN

---

### A-11: [MEDIUM] Class-Level Mutable State Enables Cross-Instance Contamination

**File:** `src/monitor/code_monitor.py:L62-L65`

**Description:**
`CodeMonitor._live_registry` and `CodeMonitor._circuit_breaker` are class-level
variables shared across all instances of `CodeMonitor`. In a multi-tenant
deployment where each tenant gets a separate `CodeMonitor` instance, one
tenant's verification failures open the circuit breaker for all tenants, and
one tenant's accepted modifications appear in all tenants' registries.

**Evidence:**
```python
# src/monitor/code_monitor.py:L62
_live_registry: dict[str, str] = {}       # class-level
_circuit_breaker: CircuitBreaker = CircuitBreaker()  # class-level
```

**Impact:**
Tenant isolation is broken. A malicious tenant can deliberately trigger 5
verification failures to deny service to all other tenants via the shared
circuit breaker.

**Recommendation:**
Move `_live_registry` and `_circuit_breaker` to instance-level (`self.`) and
initialize them in `__init__`. Pass a tenant ID to `CodeMonitor` and use it
to namespace WAL and registry paths.

**Status:** OPEN

---

### A-12: [LOW] TCB Protection Is Filesystem chmod Only — No Cryptographic Integrity

**File:** `src/core/tcb_protect.py:L60-L98` (`protect_tcb`)

**Description:**
The paper claims read-only memory protection for the TCB. The implementation
uses `chmod(0o444)` on source `.py` files. This prevents accidental overwrites
but provides no protection against: (a) a root-privileged attacker who can
`chmod u+w` and overwrite; (b) modification of `.pyc` bytecode files (which
are not protected); (c) `sys.modules` injection to replace the live module
object in memory; or (d) monkey-patching of functions on the live module.

**Evidence:**
```
verifier.py mode: 0o100444 (read-only)
# But .pyc files are not protected:
ls -la src/core/__pycache__/verifier*.pyc  # writable
```

**Impact:**
The TCB protection claim in the paper is overstated. A determined attacker with
process-level access can bypass it entirely.

**Recommendation:**
For genuine TCB integrity, compute SHA-256 hashes of all TCB modules at startup
and re-verify them before each verification call. Store the expected hashes in
a separate read-only configuration file.

**Status:** OPEN

---

### A-13: [LOW] Integer Overflow Not Modeled

**File:** `src/core/verifier.py:L130-L175` (`ExprEncoder.encode`)

**Description:**
Z3's `Int` sort represents unbounded mathematical integers. SIL programs are
verified against this model, but real execution uses Python's arbitrary-precision
integers (no overflow) or, if the output is used in a real system, fixed-width
integers. Programs that rely on overflow behavior (e.g., hash functions, bit
manipulation) will be verified against an incorrect model.

**Impact:**
Low for the current use case (financial/counter axioms), but a soundness gap
for any program that relies on bounded integer semantics.

**Recommendation:**
Document this limitation explicitly. For programs requiring bounded integers,
add a `bitvector` type to SIL backed by Z3's `BitVec` sort.

**Status:** OPEN

---

### A-14: [LOW] Paper <120ms Claim Contradicts 200ms Padding Floor

**File:** `src/core/verifier.py:L31` (`CONSTANT_VERIFICATION_TIME_S = 0.200`)

**Description:**
The paper (§3.4) claims verification completes in under 120ms. The implementation
enforces a 200ms constant-time padding floor (§3.5). These two claims are
mutually contradictory. Actual measured latency is 200ms–5s depending on program
complexity.

**Impact:**
Misleading performance claims may cause operators to set incorrect SLA
expectations or timeout configurations.

**Recommendation:**
Correct the paper. The honest claim is: "Verification completes in 200ms–5s.
The 200ms floor is intentional for timing side-channel resistance."

**Status:** OPEN (documentation issue)

---

### A-15: [LOW] quicksort.sil Is Not a Real Sort

**File:** `examples/quicksort.sil`

**Description:**
The paper's case study (§4) claims quicksort passes verification. The
`quicksort.sil` example does not implement a sort — it implements a loop that
increments a counter and a partition function that increments a pivot index.
No array elements are compared or swapped. The verification result (UNSAT) is
trivially correct because the assertions (`i >= 0`, `pivot >= lo`) are trivially
satisfiable, not because a sort algorithm was verified.

**Evidence:**
```sil
func iterative_sort(n: int) -> int {
    i = 0;
    while (i < n) bound 1000 { assert i >= 0; i = i + 1; }
    return i;
}
# This is a counter, not a sort.
```

**Impact:**
The paper's case study claim is not reproducible from the provided example.
This is a credibility issue for the research paper.

**Recommendation:**
Implement a genuine iterative sort (e.g., insertion sort) operating on a SIL
`array` type, with assertions that verify the sorted-order invariant.

**Status:** OPEN (documentation/example issue)

---

## Security Gaps (Unresolved)

| ID  | Gap                                              | Severity | Mitigation                              |
|-----|--------------------------------------------------|----------|-----------------------------------------|
| R-1 | macOS RLIMIT_AS not enforced by kernel           | MEDIUM   | Deploy with Docker `--memory=2g`        |
| R-2 | TCB protection is chmod only, not cryptographic  | MEDIUM   | Hash-verify TCB modules at startup      |
| R-3 | No mTLS for API transport                        | MEDIUM   | Add TLS termination at load balancer    |
| R-4 | Fork-under-threads crashes Z3 under load         | HIGH     | Use `spawn` start method                |
| R-5 | No integer overflow modeling                     | LOW      | Add BitVec type or document limitation  |
| R-6 | WAL/registry plaintext on disk                   | MEDIUM   | Set 0o600 permissions; encrypt at rest  |
| R-7 | No audit log signing (append-only not enforced)  | LOW      | Use append-only filesystem or WORM log  |
| R-8 | Axiom target_functions not enforced              | HIGH     | Filter axioms per function in verifier  |

---

## Recommendations

### P0 — Must Fix Before Any Production Deployment

1. **Fix loop unrolling soundness (A-01)**: Add a violation flag for the case
   where the loop condition is still true after `bound` unrollings. This is the
   most critical correctness issue — it breaks the core safety guarantee.

2. **Fix API key comparison (A-03)**: Replace `key != _API_KEY` with
   `not secrets.compare_digest(key.encode(), _API_KEY.encode())` in
   `src/main.py:L155`.

3. **Fix multiprocessing start method (A-04)**: Use `spawn` context for all
   subprocess creation in `_verify_subprocess`. This is required for correct
   operation under any concurrent load.

### P1 — Fix Before Enterprise Deployment

4. **Enforce axiom target_functions (A-05)**: Filter axioms by function name
   before encoding in `_verify_inner`. This is a documented feature that
   operators rely on.

5. **Add division-by-zero violation flag (A-06)**: Encode `right == 0` as a
   violation for every division operation in `StmtEncoder`.

6. **Enforce return statement completeness (A-07)**: Add control-flow
   completeness check in `SILTypeChecker`.

7. **Reject duplicate parameter names (A-08)**: Add duplicate check in
   `parse_function`.

8. **Fix rate limiter memory leak (A-09)**: Use a bounded TTL cache for
   `_rate_counters`.

9. **Move class-level state to instance-level (A-11)**: `_live_registry` and
   `_circuit_breaker` must be per-instance for correct multi-tenant isolation.

### P2 — Future Work

10. **Protect in-process cache integrity (A-02)**: HMAC-sign cache entries or
    use an immutable cache structure.

11. **Set restrictive file permissions on WAL/registry (A-10)**: `0o600` at
    creation time.

12. **Add cryptographic TCB integrity check (A-12)**: Hash-verify TCB modules
    at startup and before each verification call.

13. **Correct paper performance claims (A-14)**: Update §3.4 to reflect actual
    200ms–5s latency.

14. **Replace quicksort.sil with a real sort (A-15)**: Implement insertion sort
    on a SIL array with sorted-order invariant assertions.

15. **Add BitVec type for bounded integer semantics (A-13)**: Required for any
    use case involving hash functions or bit manipulation.

---

## Final Verdict

**CONDITIONAL FAIL** — Do not deploy to production in current state.

The system has a sound engineering foundation and correctly implements the core
BMC pipeline, SSA encoding, circuit breaker, WAL persistence, and subprocess
isolation. However, the verifier is demonstrably unsound for under-bounded loops
(A-01), the API key comparison has a timing side-channel (A-03), and the
multiprocessing fork-under-threads pattern causes complete verification failure
under concurrent load (A-04). These three issues together mean the system cannot
reliably enforce its core safety guarantee in a production environment.

**Path to PASS**: Fix A-01, A-03, and A-04 (estimated 1–2 days of engineering
work). Re-run the full test suite and load test. The system can then be approved
for production deployment with the remaining P1/P2 items tracked as known
limitations.

---

**Signed:**

Senior Security Auditor
Zero-Trust Evaluation Team
2026-08-02
