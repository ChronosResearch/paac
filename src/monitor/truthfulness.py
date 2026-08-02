import json
import logging
from typing import Any


class HallucinationError(Exception):
    pass


class TruthfulnessEnforcer:
    def __init__(self):
        self.logger = logging.getLogger("audit_logger")
        handler = logging.FileHandler("audit.log")
        handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

    def parse_structured_output(self, llm_response: str) -> dict[str, Any]:
        """Step 47: Implement Structured Output Schema"""
        try:
            data = json.loads(llm_response)
        except json.JSONDecodeError:
            raise HallucinationError("Response is not valid JSON")

        required_keys = ["modification", "reasoning", "citations"]
        for key in required_keys:
            if key not in data:
                raise HallucinationError(f"Missing required key: {key}")

        return data

    def enforce_citations(self, citations: list[str]):
        """Step 48: Implement Source Citation Enforcement"""
        if not citations:
            raise HallucinationError(
                "Zero citations provided. Must cite sources for safety modifications."
            )
        for citation in citations:
            if not isinstance(citation, str) or len(citation) < 10:
                raise HallucinationError(f"Invalid citation: {citation}")

    def detect_hallucination_heuristics(self, reasoning: str) -> bool:
        """Step 50: Implement Hallucination Detection Heuristics"""
        hallucination_phrases = ["i think", "maybe", "probably", "could be", "i guess"]
        reasoning_lower = reasoning.lower()
        for phrase in hallucination_phrases:
            if phrase in reasoning_lower:
                return True
        return False

    def validate_modification(self, llm_response: str) -> bool:
        """Step 49: Implement Runtime Cross-Validation"""
        try:
            data = self.parse_structured_output(llm_response)
            self.enforce_citations(data["citations"])

            if self.detect_hallucination_heuristics(data["reasoning"]):
                raise HallucinationError(
                    "Uncertain reasoning detected - potential hallucination."
                )

            self.logger.info(
                f"ACCEPTED_MODIFICATION: {data['modification']} CITATIONS: {data['citations']}"
            )
            return True
        except HallucinationError as e:
            self.logger.warning(f"REJECTED_HALLUCINATION: {e!s}")
            return False
