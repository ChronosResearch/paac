# PAAC Axiom Mutation Testing Report

Generated: 2026-08-03 09:02 UTC

## Executive Summary

| Metric | Value |
|--------|-------|
| Axioms tested | 5 |
| Total mutants | 40 |
| Mutants killed | 40 |
| **Suite Mutation Score** | **100.0%** |
| **Suite Robustness Score** | **100.0%** |
| Vacuous axioms | 0 |
| Critical axiom | no_negative_balance |

**Verdict**: STRONG — axiom set is robust and non-vacuous.

> 🔴 **Most critical axiom**: `no_negative_balance`
> Weakening this axiom causes the largest degradation in safety coverage.

## Per-Axiom Results

| Axiom ID | Condition | Mutants | Killed | Mutation Score | Robustness | Vacuous |
|----------|-----------|---------|--------|----------------|------------|---------|
| `no_negative_balance` | `balance >= 0` | 8 | 8 | 100.0% | 100.0% | No |
| `counter_in_range` | `counter >= 0` | 8 | 8 | 100.0% | 100.0% | No |
| `result_bounded` | `result >= 0` | 8 | 8 | 100.0% | 100.0% | No |
| `amount_positive` | `amount > 0` | 8 | 8 | 100.0% | 100.0% | No |
| `index_nonneg` | `index >= 0` | 8 | 8 | 100.0% | 100.0% | No |

## Mutation Detail

### Axiom: `no_negative_balance`

- **Condition**: `balance >= 0`
- **Target functions**: ['withdraw', 'deposit', 'transfer']
- **Probes**: 6
- **Mutation score**: 100.0%
- **Robustness score**: 100.0%
- **Vacuous**: No

#### Probe Suite

| # | Description | Expected Safe | Baseline Actual |
|---|-------------|---------------|-----------------|
| 1 | Assign balance=0 (satisfies 'balance >= 0') | True | True ✓ |
| 2 | Assign balance=1 (satisfies 'balance >= 0') | True | True ✓ |
| 3 | Assign balance=-1 (violates 'balance >= 0') | False | False ✓ |
| 4 | Assign balance=-5 (violates 'balance >= 0') | False | False ✓ |
| 5 | Boundary: balance=0 (exactly at boundary of 'balance >= 0') | True | True ✓ |
| 6 | Unconstrained balance (Z3 picks violating value for 'balance >= 0') | False | False ✓ |

#### Mutant Results

| Kind | Mutant Condition | Probes Killed | Kill Rate | Survived |
|------|-----------------|---------------|-----------|----------|
| noop | `balance >= 0` | 0/6 | 0.0% | ✓ Survived |
| vacuous | `true` | 3/6 | 50.0% | ✗ Killed |
| negate | `not (balance >= 0)` | 5/6 | 83.3% | ✗ Killed |
| weaken_op | `balance > 0` | 2/6 | 33.3% | ✗ Killed |
| strengthen_op | `balance > 0` | 2/6 | 33.3% | ✗ Killed |
| shift_const | `balance >= -1` | 1/6 | 16.7% | ✗ Killed |
| shift_const | `balance >= 1` | 2/6 | 33.3% | ✗ Killed |
| shift_const | `balance >= -5` | 2/6 | 33.3% | ✗ Killed |
| shift_const | `balance >= 5` | 3/6 | 50.0% | ✗ Killed |

### Axiom: `counter_in_range`

- **Condition**: `counter >= 0`
- **Target functions**: ['increment', 'decrement', 'reset_counter']
- **Probes**: 6
- **Mutation score**: 100.0%
- **Robustness score**: 100.0%
- **Vacuous**: No

#### Probe Suite

| # | Description | Expected Safe | Baseline Actual |
|---|-------------|---------------|-----------------|
| 1 | Assign counter=0 (satisfies 'counter >= 0') | True | True ✓ |
| 2 | Assign counter=1 (satisfies 'counter >= 0') | True | True ✓ |
| 3 | Assign counter=-1 (violates 'counter >= 0') | False | False ✓ |
| 4 | Assign counter=-5 (violates 'counter >= 0') | False | False ✓ |
| 5 | Boundary: counter=0 (exactly at boundary of 'counter >= 0') | True | True ✓ |
| 6 | Unconstrained counter (Z3 picks violating value for 'counter >= 0') | False | False ✓ |

#### Mutant Results

| Kind | Mutant Condition | Probes Killed | Kill Rate | Survived |
|------|-----------------|---------------|-----------|----------|
| noop | `counter >= 0` | 0/6 | 0.0% | ✓ Survived |
| vacuous | `true` | 3/6 | 50.0% | ✗ Killed |
| negate | `not (counter >= 0)` | 5/6 | 83.3% | ✗ Killed |
| weaken_op | `counter > 0` | 2/6 | 33.3% | ✗ Killed |
| strengthen_op | `counter > 0` | 2/6 | 33.3% | ✗ Killed |
| shift_const | `counter >= -1` | 1/6 | 16.7% | ✗ Killed |
| shift_const | `counter >= 1` | 2/6 | 33.3% | ✗ Killed |
| shift_const | `counter >= -5` | 2/6 | 33.3% | ✗ Killed |
| shift_const | `counter >= 5` | 3/6 | 50.0% | ✗ Killed |

### Axiom: `result_bounded`

- **Condition**: `result >= 0`
- **Target functions**: ['compute', 'calculate']
- **Probes**: 6
- **Mutation score**: 100.0%
- **Robustness score**: 100.0%
- **Vacuous**: No

#### Probe Suite

| # | Description | Expected Safe | Baseline Actual |
|---|-------------|---------------|-----------------|
| 1 | Assign result=0 (satisfies 'result >= 0') | True | True ✓ |
| 2 | Assign result=1 (satisfies 'result >= 0') | True | True ✓ |
| 3 | Assign result=-1 (violates 'result >= 0') | False | False ✓ |
| 4 | Assign result=-5 (violates 'result >= 0') | False | False ✓ |
| 5 | Boundary: result=0 (exactly at boundary of 'result >= 0') | True | True ✓ |
| 6 | Unconstrained result (Z3 picks violating value for 'result >= 0') | False | False ✓ |

#### Mutant Results

| Kind | Mutant Condition | Probes Killed | Kill Rate | Survived |
|------|-----------------|---------------|-----------|----------|
| noop | `result >= 0` | 0/6 | 0.0% | ✓ Survived |
| vacuous | `true` | 3/6 | 50.0% | ✗ Killed |
| negate | `not (result >= 0)` | 5/6 | 83.3% | ✗ Killed |
| weaken_op | `result > 0` | 2/6 | 33.3% | ✗ Killed |
| strengthen_op | `result > 0` | 2/6 | 33.3% | ✗ Killed |
| shift_const | `result >= -1` | 1/6 | 16.7% | ✗ Killed |
| shift_const | `result >= 1` | 2/6 | 33.3% | ✗ Killed |
| shift_const | `result >= -5` | 2/6 | 33.3% | ✗ Killed |
| shift_const | `result >= 5` | 3/6 | 50.0% | ✗ Killed |

### Axiom: `amount_positive`

- **Condition**: `amount > 0`
- **Target functions**: ['withdraw', 'deposit']
- **Probes**: 6
- **Mutation score**: 100.0%
- **Robustness score**: 100.0%
- **Vacuous**: No

#### Probe Suite

| # | Description | Expected Safe | Baseline Actual |
|---|-------------|---------------|-----------------|
| 1 | Assign amount=1 (satisfies 'amount > 0') | True | True ✓ |
| 2 | Assign amount=2 (satisfies 'amount > 0') | True | True ✓ |
| 3 | Assign amount=0 (violates 'amount > 0') | False | False ✓ |
| 4 | Assign amount=-1 (violates 'amount > 0') | False | False ✓ |
| 5 | Boundary: amount=1 (exactly at boundary of 'amount > 0') | True | True ✓ |
| 6 | Unconstrained amount (Z3 picks violating value for 'amount > 0') | False | False ✓ |

#### Mutant Results

| Kind | Mutant Condition | Probes Killed | Kill Rate | Survived |
|------|-----------------|---------------|-----------|----------|
| noop | `amount > 0` | 0/6 | 0.0% | ✓ Survived |
| vacuous | `true` | 3/6 | 50.0% | ✗ Killed |
| negate | `not (amount > 0)` | 5/6 | 83.3% | ✗ Killed |
| weaken_op | `amount >= 0` | 1/6 | 16.7% | ✗ Killed |
| strengthen_op | `amount == 0` | 4/6 | 66.7% | ✗ Killed |
| shift_const | `amount > -1` | 1/6 | 16.7% | ✗ Killed |
| shift_const | `amount > 1` | 2/6 | 33.3% | ✗ Killed |
| shift_const | `amount > -5` | 2/6 | 33.3% | ✗ Killed |
| shift_const | `amount > 5` | 3/6 | 50.0% | ✗ Killed |

### Axiom: `index_nonneg`

- **Condition**: `index >= 0`
- **Target functions**: ['get_elem', 'set_elem']
- **Probes**: 6
- **Mutation score**: 100.0%
- **Robustness score**: 100.0%
- **Vacuous**: No

#### Probe Suite

| # | Description | Expected Safe | Baseline Actual |
|---|-------------|---------------|-----------------|
| 1 | Assign index=0 (satisfies 'index >= 0') | True | True ✓ |
| 2 | Assign index=1 (satisfies 'index >= 0') | True | True ✓ |
| 3 | Assign index=-1 (violates 'index >= 0') | False | False ✓ |
| 4 | Assign index=-5 (violates 'index >= 0') | False | False ✓ |
| 5 | Boundary: index=0 (exactly at boundary of 'index >= 0') | True | True ✓ |
| 6 | Unconstrained index (Z3 picks violating value for 'index >= 0') | False | False ✓ |

#### Mutant Results

| Kind | Mutant Condition | Probes Killed | Kill Rate | Survived |
|------|-----------------|---------------|-----------|----------|
| noop | `index >= 0` | 0/6 | 0.0% | ✓ Survived |
| vacuous | `true` | 3/6 | 50.0% | ✗ Killed |
| negate | `not (index >= 0)` | 5/6 | 83.3% | ✗ Killed |
| weaken_op | `index > 0` | 2/6 | 33.3% | ✗ Killed |
| strengthen_op | `index > 0` | 2/6 | 33.3% | ✗ Killed |
| shift_const | `index >= -1` | 1/6 | 16.7% | ✗ Killed |
| shift_const | `index >= 1` | 2/6 | 33.3% | ✗ Killed |
| shift_const | `index >= -5` | 2/6 | 33.3% | ✗ Killed |
| shift_const | `index >= 5` | 3/6 | 50.0% | ✗ Killed |

---

## Paper Section: Axiom Robustness via Mutation Testing

We introduce *axiom mutation testing* as a quantitative method to evaluate the robustness of a safety axiom set. Inspired by mutation testing in software engineering [Jia & Harman, 2011], we apply six mutation operators to each axiom and measure how many mutations are *killed* — i.e., cause a change in verification outcome on a targeted probe suite.

**Mutation operators:**

| Operator | Description | Expected Effect |
|----------|-------------|-----------------|
| `negate` | Wrap condition in `not(...)` | Many probes killed (proves axiom is active) |
| `weaken_op` | Replace `>=` with `>`, `==` with `>=`, etc. | Few probes killed (measures boundary tightness) |
| `strengthen_op` | Replace `>` with `>=`, `>=` with `==`, etc. | More probes killed (measures over-constraint) |
| `shift_const` | Shift integer constants by ±1, ±5 | Measures sensitivity to threshold values |
| `vacuous` | Replace condition with `true` | Zero probes killed → axiom is vacuous |
| `noop` | Identity (baseline) | Zero probes killed (sanity check) |

**Robustness Score** is defined as the fraction of non-noop mutants that are killed, with a penalty of 0 for any vacuous axiom. A score of 1.0 means every mutation changes at least one verification outcome — the axiom set is maximally discriminating.

**Results**: Our axiom set achieves a Suite Robustness Score of **100.0%** across 5 axioms and 40 mutants. 40 of 40 mutants were killed (Mutation Score: 100.0%).
No vacuous axioms were detected — every axiom actively constrains at least one program.

To our knowledge, no prior AI safety monitor has applied mutation testing to formally evaluate axiom robustness. This metric directly answers the reviewer question: *'How do we know your axioms are good?'*
