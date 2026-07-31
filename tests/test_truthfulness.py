import pytest
import json
from src.monitor.truthfulness import TruthfulnessEnforcer, HallucinationError

def test_valid_structured_output():
    enforcer = TruthfulnessEnforcer()
    response = json.dumps({
        "modification": "x = x + 1",
        "reasoning": "Incrementing counter based on axiom.",
        "citations": ["Axiom AX_01, PAAC Paper pg 4"]
    })
    assert enforcer.validate_modification(response) is True

def test_missing_citations_fails():
    enforcer = TruthfulnessEnforcer()
    response = json.dumps({
        "modification": "x = x + 1",
        "reasoning": "Incrementing counter based on axiom.",
        "citations": []
    })
    assert enforcer.validate_modification(response) is False

def test_hallucination_heuristic_fails():
    enforcer = TruthfulnessEnforcer()
    response = json.dumps({
        "modification": "x = x + 1",
        "reasoning": "I guess this is safe.",
        "citations": ["Axiom AX_01, PAAC Paper pg 4"]
    })
    assert enforcer.validate_modification(response) is False

def test_adversarial_truth_testing():
    # Step 51: Adversarial test - LLM tries to bypass by providing fake JSON string
    enforcer = TruthfulnessEnforcer()
    response = "```json\n" + json.dumps({
        "modification": "x = x + 1",
        "reasoning": "Incrementing counter based on axiom.",
        "citations": ["Axiom AX_01, PAAC Paper pg 4"]
    }) + "\n```"
    # Will fail because it's not raw JSON
    assert enforcer.validate_modification(response) is False
