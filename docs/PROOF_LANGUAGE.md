# PAAC Proof Language Specification v1.0

## Overview

The PAAC Proof Language (PPL) is a lightweight, JSON-encoded formal language for
expressing safety proofs of SIL programs. A proof is a structured argument that a
SIL function satisfies a set of safety axioms. The proof checker validates each step
without calling Z3 — it is a pure symbolic evaluator over integer arithmetic.

---

## Design Goals

| Goal | Rationale |
|------|-----------|
| Self-contained | Checker needs no SIL source, only the proof |
| No Z3 | Proof checking must be < 10ms |
| Auditable | Every step is human-readable JSON |
| Composable | Proofs for sub-expressions compose into function proofs |

---

## Proof Structure

A proof is a JSON object:

```json
{
  "version": "1.0",
  "function": "<func_name>",
  "axioms": ["<axiom_id>", ...],
  "preconditions": { "<var>": "<constraint>" },
  "steps": [ <ProofStep>, ... ],
  "conclusion": "safe"
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Always `"1.0"` |
| `function` | string | Name of the SIL function being proved |
| `axioms` | list[string] | IDs of axioms this proof covers |
| `preconditions` | dict | Variable name → symbolic constraint at function entry |
| `steps` | list | Ordered proof steps (see below) |
| `conclusion` | string | `"safe"` if all axioms are satisfied, `"unsafe"` otherwise |

---

## Proof Steps

Each step is a JSON object with a `"type"` field. The checker processes steps
in order, maintaining a symbolic environment mapping variable names to
constraint sets.

### 1. `Assume`

Introduce a fact into the proof context without justification (used for
function parameters and loop invariants).

```json
{ "type": "Assume", "var": "balance", "constraint": "balance >= 0" }
```

### 2. `Assign`

Record a variable assignment. The checker updates the symbolic environment.

```json
{ "type": "Assign", "var": "balance", "expr": "balance - amount" }
```

### 3. `Assert`

Assert that a condition holds in the current environment. The checker
evaluates the condition symbolically. Fails if the condition cannot be
established from the current context.

```json
{ "type": "Assert", "condition": "balance >= 0", "justification": "by Assume[balance >= 0]" }
```

### 4. `ApplyAxiom`

Apply a named axiom to the current environment. The checker verifies that
the axiom's condition is entailed by the current symbolic state.

```json
{ "type": "ApplyAxiom", "axiom_id": "no_negative_balance", "condition": "balance >= 0" }
```

### 5. `BranchSafe`

Assert that both branches of a conditional preserve the safety property.
The checker records that the branch was analysed.

```json
{
  "type": "BranchSafe",
  "condition": "amount > 0",
  "then_safe": true,
  "else_safe": true
}
```

### 6. `LoopInvariant`

Declare a loop invariant. The checker records it and verifies it is
consistent with the current environment.

```json
{
  "type": "LoopInvariant",
  "invariant": "counter >= 0",
  "bound": 100
}
```

### 7. `Conclude`

Final step — asserts the function is safe with respect to all declared axioms.

```json
{ "type": "Conclude", "result": "safe", "covered_axioms": ["no_negative_balance"] }
```

---

## Symbolic Constraint Language

Constraints are strings using SIL expression syntax:

| Syntax | Meaning |
|--------|---------|
| `x >= 0` | x is non-negative |
| `x > 0` | x is strictly positive |
| `x == 5` | x equals 5 |
| `x >= y` | x is at least y |
| `x >= a + b` | x is at least a+b |
| `not (x < 0)` | x is non-negative (alternative form) |

Supported operators: `>=`, `>`, `<=`, `<`, `==`, `!=`, `+`, `-`, `*`, `and`, `or`, `not`

---

## Proof Checker Algorithm

The checker maintains a `SymbolicEnv`: a mapping from variable names to
known lower/upper bounds (integers or symbolic expressions).

For each step:

- **Assume**: add `var → constraint` to env
- **Assign**: update env with new expression for var
- **Assert**: check if condition is entailed by env (see Entailment below)
- **ApplyAxiom**: check axiom condition is entailed; mark axiom as covered
- **BranchSafe**: record branch analysis
- **LoopInvariant**: record invariant
- **Conclude**: verify all declared axioms are covered; set result

### Entailment Rules

The checker uses a lightweight interval-based entailment:

1. If `x >= k` is in env and condition is `x >= j` where `k >= j` → **entailed**
2. If `x > k` is in env and condition is `x >= j` where `k >= j` → **entailed**
3. If condition is a tautology (`x == x`, `true`) → **entailed**
4. If condition matches an Assume step exactly → **entailed**
5. If condition is `x >= 0` and env has `x = expr` where expr is a sum of
   non-negative terms → **entailed**
6. Otherwise → **not entailed** (checker returns REJECT with reason)

---

## Example Proof

SIL function:
```
func withdraw(balance: int, amount: int) -> int {
    assert balance >= 0;
    return balance - amount;
}
```

Axiom: `no_negative_balance: balance >= 0`

Proof:
```json
{
  "version": "1.0",
  "function": "withdraw",
  "axioms": ["no_negative_balance"],
  "preconditions": { "balance": "balance >= 0" },
  "steps": [
    { "type": "Assume", "var": "balance", "constraint": "balance >= 0" },
    { "type": "Assume", "var": "amount", "constraint": "amount >= 0" },
    { "type": "Assert", "condition": "balance >= 0", "justification": "by Assume[balance >= 0]" },
    { "type": "ApplyAxiom", "axiom_id": "no_negative_balance", "condition": "balance >= 0" },
    { "type": "Conclude", "result": "safe", "covered_axioms": ["no_negative_balance"] }
  ],
  "conclusion": "safe"
}
```

---

## Proof Validity

A proof is **valid** if and only if:
1. All `Assert` steps are entailed by the current environment
2. All `ApplyAxiom` steps reference axioms declared in `axioms`
3. All axioms in `axioms` are covered by at least one `ApplyAxiom` step
4. The final `Conclude` step has `result: "safe"`
5. `covered_axioms` in `Conclude` matches the `axioms` list

A proof is **invalid** if any of the above conditions fail. The checker
returns `REJECT` with the first failing step and reason.

---

## Proof Completeness

A proof is **complete** if it covers all safety axioms applicable to the
function. The proof generator ensures completeness by iterating over all
axioms and generating an `ApplyAxiom` step for each applicable one.

---

## Wire Format

Proofs are transmitted as compact JSON (no indentation). The proof hash
(SHA-256 of the canonical JSON) is included in the PCM certificate.

Maximum proof size: 64 KB (enforced by the checker).
