import pytest
from src.axioms.axiom_parser import AxiomParser, AxiomError
from src.axioms.axiom_loader import AxiomDatabase

def test_axiom_parser_valid():
    yaml_content = """
    axioms:
      - id: "TEST_AXIOM"
        condition: "x > 0"
        target_functions: ["foo"]
    """
    axioms = AxiomParser.parse(yaml_content)
    assert len(axioms) == 1
    assert axioms[0].id == "TEST_AXIOM"
    assert axioms[0].condition == "x > 0"

def test_axiom_parser_missing_fields():
    yaml_content = """
    axioms:
      - id: "TEST_AXIOM"
    """
    with pytest.raises(AxiomError):
        AxiomParser.parse(yaml_content)

def test_axiom_database_load(tmp_path):
    d = tmp_path / "config"
    d.mkdir()
    p = d / "test.yaml"
    p.write_text("""
    axioms:
      - id: "AX_1"
        condition: "true"
    """)
    db = AxiomDatabase()
    db.load_directory(str(d))
    assert len(db.axioms) == 1
    assert "AX_1" in db.axioms

def test_axiom_template():
    yaml_content = """
    axioms:
      - id: "TPL"
        condition: "val == {x}"
        is_template: true
    """
    axioms = AxiomParser.parse(yaml_content)
    ax = axioms[0].apply_template(x=5, name="FIVE")
    assert ax.id == "TPL_FIVE"
    assert ax.condition == "val == 5"
