import pytest
from src.core.verifier import BoundedModelChecker, VerificationError
from src.axioms.axiom_parser import Axiom
from src.core.sil_compiler import ProgramNode

def test_bmc_verification_safe():
    bmc = BoundedModelChecker()
    # Mock safe condition: axiom is trivially true
    axioms = [Axiom("AX_1", "", "true", ["*"])]
    ast = ProgramNode([])
    safe, ce = bmc.verify(ast, axioms)
    assert safe is True
    assert ce is None

def test_bmc_verification_unsafe():
    bmc = BoundedModelChecker()
    # Mock unsafe condition: balance can be -100 but axiom requires balance >= 0
    axioms = [Axiom("AX_2", "", "balance >= 0", ["*"])]
    ast = ProgramNode([])
    safe, ce = bmc.verify(ast, axioms)
    assert safe is False
    assert ce is not None
    assert "balance" in ce.assignments

def test_bmc_caching():
    bmc = BoundedModelChecker()
    axioms = [Axiom("AX_1", "", "true", ["*"])]
    ast = ProgramNode([])
    
    # First run takes normal time
    safe1, _ = bmc.verify(ast, axioms)
    
    # Second run should hit cache
    safe2, _ = bmc.verify(ast, axioms)
    
    assert safe1 is True
    assert safe2 is True
