# PAAC v8 Build Plan: Inductive Decomposition Resistance

**Status:** plan, not yet built. Nothing here is a claim about the current
system. Written 2026-09-10.

**Audience:** the implementing model (Sonnet), then a verifying model (Opus).

---

## 0. The one-sentence goal

PAAC currently answers *"is this one modification safe?"* v8 makes it answer
*"can any sequence of individually-accepted modifications ever become unsafe?"*
and answers it **by proof, not by replay**.

Everything below serves that. If a task does not serve it, it is out of scope.

---

## 1. Why this, and why now

Three 2026 results define the gap.

**Per-step monitors fail by construction.** "Monitoring Decomposition Attacks in
LLMs with Lightweight Sequential Monitors" ([arXiv
2506.10949](https://arxiv.org/html/2506.10949v1)) reports that current defences
fail under decomposition attacks, where a malicious goal is split into benign
subtasks that get past refusals. "The Distributed Detectability Band Against
Marginal-Preserving Attacks" ([arXiv
2606.10456](https://arxiv.org/html/2606.10456v2)) makes the same point for AI
control: monitors score individual actions, but harm can be spread across many
benign-looking steps, each below any per-step alarm.

**The gap is measured and unclosed.** A PRISMA review of 38 studies 2022-2026
([arXiv 2608.14590](https://arxiv.org/abs/2608.14590)) reports that blocking 94%
of unsafe actions can still yield under 5% safe task completion because agents
exploit alternative paths, and concludes that no existing approach achieves
soundness, scalability, semantic correctness and task-level safety preservation
together.

**Proof-carrying is the endorsed direction.** "Incompleteness of AI Safety
Verification via Kolmogorov Complexity" ([arXiv
2604.04876](https://arxiv.org/html/2604.04876v1)) argues no finite verifier can
certify all compliant instances, and that this motivates proof-carrying
approaches giving instance-level guarantees. PAAC already has PCM, so this is a
citation in its favour and a reason to harden PCM rather than replace it.

Content rephrased from all three sources for licensing compliance.

**What is unbuilt.** Every decomposition result above targets *probabilistic*
monitors: LLM judges, action scorers, sequential classifiers. No published work
demonstrates decomposition against a *formal SMT-based verifier gating source
code*, and none offers a **sound** rather than statistical defence.

---

## 2. The contribution, stated precisely

Not "track a monotone counter across modifications". That is bookkeeping, it is
well understood, and it only ever tells you about the past.

The contribution is **inductive invariance over the modification relation**.
Discharge this with Z3, once, ahead of time:

```
Base:  A(P_0)
Step:  forall P, D .  A(P) and accept(D, P)  =>  A(apply(D, P))
```

where `D` is a proposed modification and `apply(D, P)` is the program after it.

If the step case is UNSAT, then **no sequence of accepted modifications, of any
length, can ever violate A**. Acceptance becomes closed under composition. You
stop checking compositions after the fact and instead prove the checker cannot be
decomposed against.

Three properties make this the right target:

- **It is a proof, not a monitor.** No history to store, no replay cost, no
  per-step alarm to slip under. The decomposition literature's central attack
  does not apply to a closure property.
- **It quantifies over modifications PAAC has never seen.** A monitor reasons
  about what happened. This reasons about every modification the agent *could*
  propose next. That is the difference between auditing and guaranteeing.
- **It is falsifiable and cheap to check.** Z3 returns SAT with a witness, and
  the witness *is* a decomposition attack. The failure mode hands you the
  exploit.

### Why SIL's restriction is the enabling condition, not the weakness

The standing criticism of PAAC is that SIL has no heap, no pointers, no recursion
and no concurrency, so it cannot express real agent code. That criticism is
correct and stays documented.

But the quantified step case above is only tractable *because* of those
restrictions. Bounded loops give finite unrolling. No recursion gives a finite
call graph. No heap gives no aliasing, so `apply(D, P)` has clean syntactic
semantics. Quantifying over modifications in a language with heap and concurrency
is not something Z3 discharges.

So the restriction that limits PAAC's reach is exactly what buys it a guarantee
nobody else can state. Lead with that framing. It converts the most obvious
objection into the reason the method works, and it is honest: the guarantee is
strong *and* the domain is narrow, and both halves get said in the same breath.

### Relationship to prior work, to state before a reviewer asks

Monotone invariants over a sequence are not new, and monotone-lattice runtime
monitors exist elsewhere including in the author's other project. Say so
explicitly, then say what is different here: those order a **runtime state
tuple** and check it at admission time; this quantifies over the **space of
source-code modifications** and discharges a closure property with an SMT solver
before any modification arrives. Different object, different technique, different
guarantee. Own the connection in the writeup rather than letting someone find it.

---

## 3. Non-goals

- **No features outside section 0.** No new endpoints, no new proof-language
  keywords, no dashboards, no SNARKs.
- **Do not expand SIL.** Per section 2 that would undermine the tractability
  argument. Expressiveness is a separate, later project.
- **Do not read or import from CHRONOS.** Separate repos, separate histories,
  independent derivation.
- **Do not edit the submitted paper.** It is under EPFL review until 30 Sept,
  feedback early October. v8 is code and repo docs. One paper revision *after*
  feedback, informed by both.
- **Test count is not a goal.** A test that asserts a call returned without
  asserting what it returned validates padding.
- **No em dashes anywhere in the repo.** Commas, colons or full stops instead.

---

## 4. Step 0: ground truth and cleanup (short, then move on)

Minimal pass. The point is not to relitigate old docs, it is to stop shipping
numbers nobody can reproduce.

**0.1 Run the suite, record the real figure.**
```bash
python3.11 -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
PYTHONPATH=. python3.11 -m pytest tests/ -q
```
`README.md` claims 386. Record the actual number, Python version, machine. Fix
the README if it differs.

**0.2 Delete `src/certificates/proof_cert.py`.** Confirmed legacy. It implements
version `1.0` certificates under HMAC-SHA256 with the default key
`paac-default-cert-key-change-in-prod`, which gives integrity but not
non-repudiation and not public verifiability, unlike the Ed25519 attestation
path. Remove the module, its tests, and the `PAAC_CERT_KEY` row from the README
config table. Note the deletion in `AUDIT_FINDINGS.md`.

**0.3 Mark `PAPER_CLAIMS_CHECKLIST.md` as a historical v5 record** with a
one-line header, or delete it. Do not spend time reconciling it line by line.

**0.4 Relicense to Apache-2.0.** Replace `LICENSE`, adopt the
`SPDX-License-Identifier: Apache-2.0` header convention, and update the README
licence line. Required for LTFF and SFF reproducibility expectations, and
consistent with PAAC being described as open-source research.

**0.5 CONFIRMED CRITICAL: a vacuous precondition bypasses the entire verifier.**
Verified against the code on 2026-09-10. This is not a hypothesis. Fix it before
anything else in this plan.

The precondition is attacker-controlled end to end.
`AgentAdapter.propose_modification` reads it straight off the agent's JSON
(`src/monitor/agent_adapter.py`: `pre_cond=data.get("precondition", "true")`).
`CodeMonitor.intercept_modification` passes it unvalidated to the solver
(`src/monitor/code_monitor.py`: `checker.verify(ast, applicable,
timeout_ms=self.timeout_ms, pre_cond=mod.pre_cond)`). `_verify_inner` asserts it
as a hard constraint (`src/core/verifier.py`: `solver.add(_z3_pre)`).

The only gates upstream are the circuit breaker and a source-citation format rule
(20 or more characters containing a dot). Neither inspects `pre_cond`.

Attack, end to end:

1. Agent submits genuinely unsafe `new_code`, a citation such as
   `https://example.com/paper`, and `precondition = "1 == 0"`.
2. `_encode_axiom` compiles that to Z3 `False`, and `solver.add` asserts it.
3. Every later assertion, including the axiom violation disjunction, is now
   conjoined with `False`, so the query is trivially UNSAT.
4. `intercept_modification` reads `safe=True`, writes the payload to
   `_live_registry`, checkpoints it, and under PCM mode issues a signed
   attestation for it.

This is not a corner case. It is an unconditional bypass of the whole verifier
for an arbitrary payload, through the production entry point that is supposed to
be the trust boundary between agent and monitor. Every safety claim in the README
and the paper is void while it stands.

Two fixes, both required:

- **Satisfiability gate.** Before BMC, check `pre_cond` in isolation. If it is
  UNSAT, reject at parse time with a distinct error. An unsatisfiable
  precondition is never a legitimate submission: it is a bug or an attack, and
  in both cases the answer is rejection, not a vacuous pass.
- **Stop accepting preconditions from the agent.** A precondition is an
  obligation on the *caller*, so taking it from the callee's author inverts the
  trust relationship. Derive it, or source it from an operator-controlled
  location outside the agent's reach. Record which was chosen and why.

Regression tests, all of which must fail before the fix and pass after:
`"1 == 0"`, `"false"`, `"x != x"`, `"x > 0 and x < 0"`. Four spellings of the
same contradiction, so the gate is semantic rather than a string blocklist.

**0.6 CONFIRMED: calls are uninterpreted, so interprocedural composition is
unsound.** Also verified against the code. Paper section 3.3 says a precondition
holds at every call site. It does not.

In `ExprEncoder.encode`, a `CallExprNode` becomes an opaque Z3 function symbol
over the arguments, with no body, no precondition and no postcondition:

```python
if isinstance(node, CallExprNode):
    arg_exprs = [self.encode(a) for a in node.args]
    sorts = [z3.IntSort(self.ctx)] * len(arg_exprs) + [z3.IntSort(self.ctx)]
    fn = z3.Function(node.func_name, *sorts)
    return fn(*arg_exprs)
```

So `g(x)` means "some integer determined by x, otherwise unconstrained". The
callee's contract is invisible at the call site, and `pre_cond` constrains only
the entry parameters of the one function under verification. Related: `post_cond`
is collected on `CodeModification`, stored in the WAL, and never passed to the
verifier at all, so postconditions are currently dead weight.

The consequence is that this is accepted today:

```
func g(x: int) -> int
  pre x >= 1
  return x - 1

func f(x: int) -> int
  pre x >= 1
  y = g(x)        // ok, x >= 1
  return g(y)     // g(0) when x == 1, violating g's precondition
```

Under `result_bounded: result >= 0`, `f(1)` returns `-1`. Commit this as a
failing test now. It is the simplest decomposition attack that exists, and it is
Step 1's schema A already instantiated by hand.

Do **not** fix 0.6 here. The correct fix is caller-obligation enforcement, which
is T1 in Step 2. Building it twice is how this repo becomes the jungle the plan
exists to prevent. Log it, test it, let Step 2 close it.

**Acceptance:** every README number traceable to a command, `proof_cert.py` gone,
Apache-2.0 in place, 0.5 fixed with all four semantic regression tests passing,
0.6 captured as a failing test and deferred to T1.

---

## 5. Step 1: solver-synthesised decomposition witnesses (`src/decomp/`)

Build the attacker first: the witnesses become Step 2's test suite, and a defence
built without a demonstrated attack defends the wrong thing.

Per section 11 the attacker is **Z3, not a search loop**. Ask the solver for a
counterexample to closure:

```
find P, D  such that   A(P) and accept(D, P) and not A(apply(D, P))
```

SAT yields a **decomposition witness**: a program plus a modification, each
individually accepted, whose composition violates `A`. UNSAT over a schema yields
a bounded guarantee for that schema. There is no sampling and no tuning, so there
is nothing to bias.

**Deliverable:** `src/decomp/schema.py` (schema definitions and their encodings),
`src/decomp/synth.py` (the query driver), `tests/test_decomposition.py`.

### The three schemas to quantify over

These are **schema definitions the query ranges over**, not hand-written attack
strategies. Encode each as a constrained template with symbolic holes Z3 fills.

- **A. Call-chain composition.** Templates where a computation spans a caller and
  one or more callees, each satisfying its own precondition in isolation while a
  call chain violates one. Whether this schema is even satisfiable depends
  entirely on the answer to 0.5.
- **B. Sentinel-touching modification pairs.** `no_exit` (`exit_called == 0`) and
  `no_network` (`network_calls == 0`) resolve through the live `SSAEnv`. First
  determine whether sentinel state persists across *modifications* or resets per
  verification. If it resets, this schema is where an agent accumulates across
  modifications what it cannot do in one.
- **C. Precondition-narrowing pairs.** One modification legitimately narrows a
  precondition; a second leans on the narrowed form; the *pair* admits inputs
  neither admitted alone.

### Reporting rule

All three outcomes are results, and the wording matters because they are not
equally strong:

- **SAT:** minimise the witness, then commit it as a failing test case. State
  which schema produced it.
- **UNSAT:** report it as *"no decomposition exists within schema S"*, with `S`
  defined precisely in `docs/DECOMPOSITION.md`. This is a bounded proof, which is
  strictly stronger than "we sampled N programs and found nothing". Never state
  it as "PAAC is decomposition-resistant" without the schema qualifier.
- **unknown or timeout:** report it as unknown. Do not round a timeout to UNSAT.
  Record the timeout value and the query size.

**Acceptance:** each schema encoded and its boundary written down; every SAT
witness minimised into a failing test in `tests/test_decomposition.py`; every
UNSAT recorded against its schema; every timeout recorded as unknown with its
bound. Queries reproducible from a committed script.

---

## 6. Step 2: the defence, three tiers

Build in this order. Each tier is a fallback for the one after it, and T1 stays
permanently as the test oracle.

**T1, replay composition with caller obligations (baseline oracle).** Maintain
accepted state `P_k`; on modification `D`, form `P_k+1 = apply(D, P_k)` and run
BMC over the whole composed program. Obviously sound, obviously does not scale.
Keep it permanently as the oracle T3 is differentially tested against.

This tier is also where 0.6 gets fixed, because replaying the composed program is
the only context in which a callee's contract is visible at its call sites. Three
pieces, in this order, implementing Design-by-Contract semantics across the
verification boundary:

- **Call-site obligation injection.** When encoding a call to `g` inside `f`,
  emit `g`'s precondition as a *violation flag* over the actual argument
  expressions at that site, not as an assumption. Z3 must prove the state
  satisfies `pre_g` immediately before the call. This is the standard contract
  reading: a precondition is an assumption inside the callee and an obligation at
  the caller. Currently PAAC implements only the first half, which is exactly why
  0.6 exists.
- **Callee summarisation.** A call currently returns an unconstrained symbol.
  Replace it either by inlining the callee body, or by constraining the returned
  symbol with the callee's postcondition. Note `post_cond` already exists on
  `CodeModification` and is currently unused by the verifier, so wiring it here
  costs nothing new. The SIL compiler's no-recursion guarantee is what makes
  inlining terminate, so prefer inlining for the oracle and keep summarisation
  for T3 where cost matters.
- **Weakest-precondition propagation.** For transitive calls, propagate
  obligations upward so an inner callee's requirement surfaces as a constraint on
  the outermost entry parameters. Compute WP backwards along the call chain.
  Bounded loops and the absence of aliasing are what keep this tractable, which
  is the same argument as section 2.

State plainly which of the three landed. "Call-site obligations and inlining
done, WP propagation not implemented" is a fine and honest status. Shipping two
of three while describing all three is not.

Measure BMC wall-clock against accumulated modification count and publish where
it stops being practical.

**T2, summary invariant (cheap fallback).** Carry a fixed-size summary of
accepted history: per-variable interval bounds, sentinel counters, per-function
precondition-strength ledger. Check `D` against the summary. Only sound if the
summary is a sound abstraction, which must be argued explicitly, and you must
state which decompositions it cannot see. This is the tier closest to ordinary
monotone bookkeeping, so it is a fallback, not the contribution.

**T3, inductive invariance (the contribution).** Encode the section 2 step case
in Z3 and discharge it:

```
forall P, D .  A(P) and accept(D, P)  =>  A(apply(D, P))
```

Practical shape: quantify over modifications *within a declared modification
schema* rather than all syntactic programs, because unrestricted quantification
over program text is not tractable even in SIL. Define the schema precisely, and
state that the closure guarantee holds for modifications inside it and not
outside. A guarantee with a stated boundary is worth more than an unbounded one
nobody believes.

- On **UNSAT**: no accepted sequence within the schema can violate `A`. This is
  the result worth publishing.
- On **SAT**: Z3 hands back a witness, and that witness is a decomposition
  attack. Feed it straight into `tests/test_decomposition.py`. A failed proof
  attempt is still a finding.

**Metric.** *Decomposition resistance*: of the Step 1 witnesses, the fraction now
rejected, **with the denominator stated**. "12 of 12 witnesses synthesised by our
own schemas" is honest and useful. A bare "100%" is not.

**Acceptance:** every Step 1 witness rejected; no previously accepted safe
modification newly rejected; T3 differentially agrees with T1 across the whole
existing suite; measured cost table for all three tiers.

---

## 7. Step 3: PCM checker differential fuzzing (`tests/test_pcm_differential.py`)

Parallel to Step 2, smaller, high value. PCM is the component the Kolmogorov
result endorses, and its entire claim is *trust the checker, not the agent*.

PAAC has **two independent implementations of one specification**: the Z3 BMC
verifier, and the PCM proof checker (Python `ast` plus interval arithmetic, no
Z3). Two implementations diverge. If the checker is ever *more permissive*, an
adversarial agent submits a proof the checker accepts for a program Z3 rejects.
That is a soundness break in the component whose job is to be trustworthy.

Random generation is correct here, unlike in Step 1, because the target is
divergence between two implementations rather than a closure property, and there
is no schema to quantify over.

Methodology is established: Circuzz found 16 logic bugs across four
zero-knowledge pipelines with metamorphic differential fuzzing ([arXiv
2411.02077](https://arxiv.org/html/2411.02077v1)), and AValAnCHE found issues in
the VerCors deductive verifier by fuzzing it ([arXiv
2604.19448](https://arxiv.org/html/2604.19448v1)). Content rephrased for
licensing compliance. Applying it to an AI-safety proof checker appears
unpublished.

Generate random well-typed SIL programs from a seeded grammar; run both paths;
compare:

| Verifier | Checker | Meaning |
|---|---|---|
| UNSAT | accepts | agree, safe |
| SAT | rejects | agree, unsafe |
| SAT | **accepts** | **soundness bug, critical** |
| UNSAT | rejects | incompleteness, log it, not a security bug |

**Acceptance:** seeded generator, at least 10,000 programs, every divergence
triaged and classified, soundness bugs fixed with regression tests. Zero
divergences is a fine result if you report the count and the generator's grammar
coverage so the claim is bounded.

---

## 8. Step 4: documentation

**8.1 `docs/DECOMPOSITION.md`.** Problem, threat model, which schemas were
encoded and what each covers, what was found, what T3 proves, the **schema
boundary** of that proof, and what v8 does not close. The last two sections are
not optional; they are what a grant evaluator reads first.

**8.2 README.** Real test count, decomposition-resistance figure with
denominator, T3's guarantee stated with its schema boundary, Apache-2.0, and a
Known Limitations entry for what T3 still cannot reach.

**8.3 `KNOWN_ISSUES.md` and `AUDIT_FINDINGS.md`.** Feed everything Steps 0 to 3
uncover into these. `AUDIT_FINDINGS.md` existing at all is one of PAAC's
strongest signals to a funder.

---

## 9. The no-lie contract

1. **Every number traces to a command.** If nobody can rerun it, delete it.
2. **Every metric carries its denominator.**
3. **A test asserts a value, never merely that a call returned.**
4. **State what a mechanism does not establish adjacent to what it does**, same
   section, not an appendix.
5. **"First" claims are liabilities.** Prefer "we are not aware of prior work
   that does X", and be specific about X.
6. **A limitation you disclose is evidence of rigour; one a reviewer finds is
   evidence of the opposite.** The whole strategy rests on this.

---

## 10. Sequencing

| Step | Output | Blocks |
|---|---|---|
| 0 | Real test count, `proof_cert.py` deleted, Apache-2.0, 0.5 answered | Blocks 1 |
| 1 | Schemas encoded; SAT witnesses, or UNSAT bounded per schema | Blocks 2 |
| 2 | T1 oracle, then T3 inductive proof; resistance metric; cost table | none |
| 3 | PCM differential fuzzer; divergences triaged | parallel to 2 |
| 4 | `docs/DECOMPOSITION.md`, README, KNOWN_ISSUES | last |

**Done means:** suite passes, every claim traces to a command, every solver query
reruns from a committed script, T3's guarantee is stated with its schema
boundary, and `docs/DECOMPOSITION.md` says plainly what v8 does not close.

---

## 11. Resolved: the adversary is Z3, not an LLM and not random search

Decided. Step 1 does **not** need a real agent in the loop, and should not use
one as its primary method.

The attacker is the section 2 query run in the SAT direction:

```
find P, D  such that   A(P) and accept(D, P) and not A(apply(D, P))
```

SAT gives a decomposition witness. UNSAT over a schema gives the guarantee for
that schema. Same query, opposite directions.

Why this beats the alternatives:

- **Versus an LLM adversarial agent:** an LLM's findings are not reproducible, so
  a reviewer cannot replay them and the claim cannot be defended. A committed
  solver query can be rerun by anyone.
- **Versus random program search:** random sampling can only ever support "we
  tried N and found nothing", which is weak. A solver result is **exhaustive over
  the declared schema**, so a null result becomes a bounded proof rather than an
  absence of evidence.
- **It collapses two components into one.** No separate search heuristic to
  build, tune, or justify. Less code, stronger result.

An LLM-driven agent remains worthwhile later as a *demo* for a video or writeup,
clearly labelled as illustration rather than evidence. It is not on the v8 path.

Note the deliberate asymmetry with Step 3: random generation is wrong for Step 1,
where a schema-bounded proof is available, and right for Step 3, where the target
is divergence between two implementations and no schema exists to quantify over.
