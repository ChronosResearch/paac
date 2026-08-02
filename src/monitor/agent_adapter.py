# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned Core) project.
# See LICENSE for terms.

import json
import os

import google.generativeai as genai

from .code_monitor import CodeModification


class AgentAdapter:
    def __init__(self, api_key: str, config: dict):
        self.api_key = api_key
        if api_key and api_key != "${AGENT_API_KEY}":
            genai.configure(api_key=api_key)

        # Fallback to standard model for baseline reasoning capability in prototype
        model_name = config.get("agent_model", "advanced-reasoner")
        if model_name == "advanced-reasoner-pro":
            model_name = "advanced-reasoner"  # fallback mapping for prototype

        grounding = config.get("grounding", {})

        self.model = genai.GenerativeModel(
            model_name=model_name,
            generation_config=genai.types.GenerationConfig(
                temperature=grounding.get("temperature", 0.0),
                top_p=0.0,
                top_k=1,
                response_mime_type="application/json",
            ),
        )

    def propose_modification(self, prompt: str) -> CodeModification:
        system_prompt_path = os.path.join(os.getcwd(), "config", "default.yaml")
        system_prompt = "You are a PAAC Inner Agent. Output must be structured JSON."
        if os.path.exists(system_prompt_path):
            with open(system_prompt_path, "r") as f:
                system_prompt = f.read()

        full_prompt = f"{system_prompt}\nUser Request:\n{prompt}\nReturn JSON with keys: function_name, new_code, precondition, postcondition, source_citation"

        try:
            if not self.api_key or self.api_key == "${AGENT_API_KEY}":
                # Mock return for unauthenticated environments
                return CodeModification(
                    func_name="generated_func",
                    old_code="",
                    new_code="func generated_func() -> int { while(x) bound 100 { x = x - 1; } }",
                    pre_cond="true",
                    post_cond="true",
                    source_citation="Cleanroom mock implementation",
                )

            response = self.model.generate_content(full_prompt)
            data = json.loads(response.text)

            return CodeModification(
                func_name=data.get("function_name", "generated_func"),
                old_code="",
                new_code=data.get("new_code", ""),
                pre_cond=data.get("precondition", "true"),
                post_cond=data.get("postcondition", "true"),
                source_citation=data.get("source_citation", ""),
            )
        except json.JSONDecodeError:
            raise RuntimeError("Agent failed to return valid JSON.")
        except Exception as e:
            raise RuntimeError(f"Agent failed to propose modification: {e}")
