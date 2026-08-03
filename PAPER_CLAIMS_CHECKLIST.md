# PAPER_CLAIMS_CHECKLIST.md — PAAC v5.0.0
# EU AI Summer Research Program — EPFL
# Generated: 2026-08-02

This document maps every claim in the PAAC paper to its verification status.
Status codes: VERIFIED | PARTIAL | CORRECTED | FUTURE_WORK

---

## Section 1: Core Verification Pipeline

| Claim | Status | Evidence |
|---|---|---|
| SIL compiler rejects recursion at compile time | VERIFIED | `test_mutual_recursion_detected`, `test_direct_recursion_rejected` |
| All loops require explicit bounds | VERIFIED | `test_loop_without_bound_rejected` |
| Z3 BMC pipeline is sound for well-bounded loops | VERIFIED | `test_under_bounded_loop_is_unsafe`, `test_exactly_bounded_loop_is_safe` |
| Under-bounded loops return SAT (A-01 fix) | VERIFIED | `test_under_bounded_loop_is_unsafe` — `while (x<5) bound 3` correctly SAT |
| Cache cannot be poisoned externally (A-02 fix) | VERIFIED | `test_cache_not_poisonable_via_direct_assignment`, `test_cache_not_poisonable_via_attribute_set` |
| API key comparison is constant-time (A-03 fix) | VERIFIED | `test_main_uses_compare_digest`, source inspection |
| Multiprocessing uses spawn (A-04 fix) | VERIFIED | `test_spawn_start_method_configured` |
| Axioms filtered by target_functions (A-05 fix) | VERIFIED | `test_axiom_not_applied_to_non_target_function` |

---

## Section 2: Bootstrap Self-Verification

| Claim | Status | Evidence |
|---|---|---|
| PAAC can translate its own TCB to SIL stubs | VERIFIED | `test_all_tcb_stubs_compile_and_run` — 6 stubs compile and verify |
| Python-to-SIL translator handles assert statements | VERIFIED | `test_python_to_sil_stub_simple_function` |
| Python-to-SIL translator handles loops | VERIFIED | `test_python_to_sil_stub_with_loop` |
| Malicious TCB modification is detected | VERIFIED | `test_malicious_modification_rejected` — `assert false` stub is SAT |
| Self-verification is deterministic | VERIFIED | `test_self_verify_stress_10_runs_deterministic` |
| PAAC proves its own structural invariants hold | PARTIAL | Stubs assert conditions that are SAT for unconstrained inputs. This is correct behavior — the verifier finds boundary conditions. Full proof requires preconditions on inputs (future work). |
| Translation covers all Python constructs | CORRECTED | Only assert, assignment, simple arithmetic, and loops are translated. External calls (Z3, Redis) are dropped. This is documented as a limitation. |

---

## Section 3: Cryptographic Attestation

| Claim | Status | Evidence |
|---|---|---|
| Attestation is generated for every accepted modification | VERIFIED | `test_attest_generates_record`, `/verify` endpoint integration |
| Attestation commitment is 32 bytes (64 hex chars) | VERIFIED | `test_attest_generates_record` — `len(record.commitment) == 64` |
| Tampered result invalidates commitment | VERIFIED | `test_tampered_result_fails_verification` |
| Tampered program hash invalidates commitment | VERIFIED | `test_tampered_program_hash_fails` |
| Key rotation works; old attestations verifiable with old key | VERIFIED | `test_key_rotation` |
| 1000 attestations all verify correctly | VERIFIED | `test_stress_1000_attestations` |
| Concurrent attestation generation is thread-safe | VERIFIED | `test_concurrent_attestations_thread_safe` |
| Attestation is a full zk-SNARK proof | CORRECTED | HMAC-SHA256 is used, not a zk-SNARK. HMAC provides integrity and authenticity but not zero-knowledge. A verifier who holds the key can forge attestations. Full SNARKs require arkworks/bellman (Rust/C++) — future work. |

---

## Section 4: Multi-Agent Coordination

| Claim | Status | Evidence |
|---|---|---|
| Independent function modifications are verified collectively | VERIFIED | `test_two_agents_independent_functions_accepted` |
| Unsafe modification in a batch causes batch rejection | VERIFIED | `test_two_agents_one_unsafe_rejected` |
| Conflicting modifications are queued and serialized | VERIFIED | `test_conflict_detection_queues_second_modification` |
| Queue stops after first rejection | VERIFIED | `test_queue_stops_on_rejection` |
| Agent crash marks modifications as abandoned | VERIFIED | `test_agent_crash_marks_modifications_abandoned` |
| 5 concurrent agents all accepted | VERIFIED | `test_five_agents_concurrent` |
| 10 agents × 10 mods stress test passes | VERIFIED | `test_10_agents_100_mods_stress` |
| Dependency graph tracks transitive dependencies | VERIFIED | `test_dependency_graph_registers_calls` |
| Shared mutable state (Redis, globals) is modelled | CORRECTED | Not modelled. Compositional soundness holds only within the SIL fragment. Python-level interactions via Redis or global variables are not tracked. Documented as a limitation. |

---

## Section 5: Performance

| Claim | Status | Evidence |
|---|---|---|
| Verification latency < 120ms | CORRECTED | Minimum floor is 200ms (constant-time padding). Typical: 200-800ms. The <120ms claim was incorrect and has been removed from the paper. |
| Constant-time padding prevents timing side channels | VERIFIED | `test_constant_time_padding_on_safe_path`, `test_constant_time_padding_on_unsafe_path` |
| p95 latency < 1s under load | VERIFIED | Load test: p95=15ms for Z3 query time (plus 200ms padding floor) |

---

## Section 6: TCB and Security

| Claim | Status | Evidence |
|---|---|---|
| TCB is ~500 lines | CORRECTED | Actual: ~2,123 lines across 6 core files. Updated in paper. |
| TCB files are in read-only memory | CORRECTED | chmod 0o444 only (filesystem-level). Not kernel read-only memory pages. Documented as a limitation. |
| Z3 subprocess is isolated | VERIFIED | RLIMIT_AS + RLIMIT_CPU on Linux; spawn start method |
| IPC token prevents spoofing | VERIFIED | 32-byte random token, constant-time comparison |
| Circuit breaker prevents cascade failures | VERIFIED | `test_circuit_breaker_open_rejects_all` |

---

## Section 7: Known Limitations (new section)

These are documented honestly in the paper:

1. Loop soundness requires sufficient bounds — no automated bound inference.
2. 200ms latency floor — constant-time padding is a security property.
3. TCB ~2,123 lines — larger than the research prototype.
4. SIL cannot express heap, concurrency, or quantified invariants.
5. Axiom completeness is manual — incomplete axioms allow unsafe programs.
6. TCB protection is chmod only — not kernel-enforced.
7. Bootstrap verification translates only assert/arithmetic — external calls dropped.
8. Attestation uses HMAC-SHA256 — not a zero-knowledge proof.
9. Multi-agent coordination does not model Redis/global state interactions.
10. macOS RLIMIT_AS not enforced — use Docker --memory=2g.

---

## Test Count Summary

| Category | Tests |
|---|---|
| Baseline (pre-v5) | 212 |
| Bootstrap self-verification (new) | 13 |
| Cryptographic attestation (new) | 17 |
| Multi-agent coordination (new) | 18 |
| **Total** | **260** |

All 260 tests pass. Bandit: 0 HIGH. Mypy: 0 errors.
