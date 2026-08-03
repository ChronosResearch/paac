from src.axioms.axiom_loader import AxiomDatabase
from src.axioms.axiom_parser import Axiom
from src.monitor.interceptor import CodeModification, Interceptor


def test_serialization():
    mod = CodeModification(
        "src/foo.py", "bar", "func bar() -> int { return 1; }", "agent_1"
    )
    j = mod.to_json()
    mod2 = CodeModification.from_json(j)
    assert mod.file_path == mod2.file_path
    assert mod.proposed_sil == mod2.proposed_sil


def test_interceptor_accepts_safe():
    db = AxiomDatabase()
    db.axioms["AX1"] = Axiom("AX1", "", "true", ["*"])

    interceptor = Interceptor(db)
    mod = CodeModification("foo.py", "bar", "func bar() -> int { return 1; }", "agent")
    assert interceptor.intercept(mod) is True


def test_interceptor_rejects_unsafe():
    """A program that explicitly asserts false must be rejected."""
    db = AxiomDatabase()
    # No axioms needed — the program itself contains assert false.
    interceptor = Interceptor(db)
    mod = CodeModification(
        "foo.py",
        "bad",
        "func bad() -> int { assert false; return 0; }",
        "agent",
    )
    assert interceptor.intercept(mod) is False


def test_interceptor_rejects_axiom_violation():
    """A program that can make balance negative violates the no_negative_balance axiom."""
    db = AxiomDatabase()
    # Axiom: balance must be >= 0.  The withdraw function can produce balance < 0.
    db.axioms["AX_BAL"] = Axiom("AX_BAL", "", "balance >= 0", ["withdraw"])

    interceptor = Interceptor(db)
    mod = CodeModification(
        "foo.py",
        "withdraw",
        # balance is unconstrained — Z3 picks balance = -1 to violate the axiom.
        "func withdraw(balance: int, amount: int) -> int { return balance - amount; }",
        "agent",
    )
    assert interceptor.intercept(mod) is False


def test_interceptor_rejects_syntax_error():
    db = AxiomDatabase()
    interceptor = Interceptor(db)
    mod = CodeModification(
        "foo.py", "bar", "func bar() -> int { invalid syntax }", "agent"
    )
    assert interceptor.intercept(mod) is False
