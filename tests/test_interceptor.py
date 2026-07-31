import pytest
from src.monitor.interceptor import CodeModification, Interceptor
from src.axioms.axiom_loader import AxiomDatabase
from src.axioms.axiom_parser import Axiom

def test_serialization():
    mod = CodeModification("src/foo.py", "bar", "func bar() -> int { return 1; }", "agent_1")
    j = mod.to_json()
    mod2 = CodeModification.from_json(j)
    assert mod.file_path == mod2.file_path
    assert mod.proposed_sil == mod2.proposed_sil

def test_interceptor_accepts_safe():
    db = AxiomDatabase()
    db.axioms["AX1"] = Axiom("AX1", "", "true", ["*"])
    
    interceptor = Interceptor(db)
    mod = CodeModification("foo.py", "bar", "func bar() -> int { return 1; }", "agent")
    
    # Should compile fine and verify as safe (since true axiom)
    assert interceptor.intercept(mod) is True

def test_interceptor_rejects_unsafe():
    db = AxiomDatabase()
    db.axioms["AX1"] = Axiom("AX1", "", "balance >= 0", ["*"])
    
    interceptor = Interceptor(db)
    mod = CodeModification("foo.py", "bar", "func bar() -> int { return 1; }", "agent")
    
    # Unsafe due to mock logic in BMC for balance >= 0
    assert interceptor.intercept(mod) is False

def test_interceptor_rejects_syntax_error():
    db = AxiomDatabase()
    interceptor = Interceptor(db)
    mod = CodeModification("foo.py", "bar", "func bar() -> int { invalid syntax }", "agent")
    
    # Syntax error in compiler caught by interceptor
    assert interceptor.intercept(mod) is False
