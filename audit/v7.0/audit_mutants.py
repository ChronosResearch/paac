import sys, types, importlib.util, collections
import pathlib as _pl

_REPO = _pl.Path(__file__).resolve().parents[2]

# ---- stub out pyyaml (not installed) so axiom_parser imports -------------
fake_yaml = types.ModuleType("yaml")
fake_yaml.safe_load = lambda *a, **k: {}
sys.modules["yaml"] = fake_yaml

sys.path.insert(0, str(_REPO))
from src.axioms.axiom_parser import Axiom
from src.mutation.axiom_mutator import generate_mutations as generate_mutants

# EXACT current production axiom set from config/axioms.yaml
CURRENT = [
    Axiom("no_negative_balance", "Account balance must remain non-negative.",
          "balance >= 0", ["withdraw", "deposit", "transfer"]),
    Axiom("counter_in_range", "Counter must be non-negative.",
          "counter >= 0", ["increment", "decrement", "reset_counter"]),
    Axiom("result_bounded", "Computed result must not exceed 1000000.",
          "result >= 0", ["compute", "calculate"]),
    Axiom("no_exit", "Code must not call exit() or terminate the process.",
          "exit_called == 0", ["*"]),
    Axiom("no_network", "Code must not make network calls.",
          "network_calls == 0", ["*"]),
]

# The STALE axiom set recorded in docs/axiom_mutation_results.json
STALE = [
    Axiom("no_negative_balance", "", "balance >= 0", ["*"]),
    Axiom("counter_in_range", "", "counter >= 0", ["*"]),
    Axiom("result_bounded", "", "result >= 0", ["*"]),
    Axiom("amount_positive", "", "amount > 0", ["*"]),
    Axiom("index_nonneg", "", "index >= 0", ["*"]),
]


def tally(label, axiom_set):
    print("=" * 78)
    print(label)
    print("=" * 78)
    grand_all = grand_nonnoop = 0
    for ax in axiom_set:
        muts = generate_mutants(ax)
        kinds = [str(getattr(m, "kind", "?")) for m in muts]
        kinds = [k.split(".")[-1].lower() for k in kinds]
        n_all = len(muts)
        n_noop = sum(1 for k in kinds if k == "noop")
        n_non = n_all - n_noop
        grand_all += n_all
        grand_nonnoop += n_non
        print(f"  {ax.id:22} {ax.condition:22} "
              f"total={n_all:2}  noop={n_noop}  non-noop={n_non}")
        print(f"      kinds: {kinds}")
    print()
    print(f"  >>> GRAND TOTAL including noop : {grand_all}")
    print(f"  >>> GRAND TOTAL excluding noop : {grand_nonnoop}")
    print()
    return grand_all, grand_nonnoop


cur_all, cur_non = tally("CURRENT production axiom set (config/axioms.yaml)", CURRENT)
stale_all, stale_non = tally("STALE axiom set recorded in docs/axiom_mutation_results.json", STALE)

print("=" * 78)
print("RECONCILIATION AGAINST PUBLISHED CLAIMS")
print("=" * 78)
print(f"  Paper §5.2 / README / abstract claim ......... 43 mutants, 100% robustness")
print(f"  docs/axiom_mutation_results.json says ....... {stale_non} mutants (total_mutants field)")
print(f"  docs/AXIOM_MUTATION_REPORT.md says .......... 40 mutants")
print(f"  docs/axiom_mutation_results.csv rows ........ {stale_all} (9 per axiom, incl. noop)")
print()
print(f"  Generator, CURRENT axiom set, incl. noop .... {cur_all}")
print(f"  Generator, CURRENT axiom set, excl. noop .... {cur_non}")
print(f"  Generator, STALE   axiom set, incl. noop .... {stale_all}")
print(f"  Generator, STALE   axiom set, excl. noop .... {stale_non}")
print()
print("  Note: robustness_score denominator EXCLUDES noop")
print("        (mutation_runner.py: 'Fraction of non-noop mutants that were killed')")
print("        and every noop mutant is recorded survived=True by construction.")
print(f"  => If 43 counts noop, then 5 noop mutants survive and the score over 43")
print(f"     is {cur_all - 5}/{cur_all} = {(cur_all-5)/cur_all:.1%}, NOT 100%.")
