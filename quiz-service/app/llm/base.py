from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from ..models import LLMConfig


class LLMClient(ABC):
    @abstractmethod
    async def generate(self, system_prompt: str) -> dict:
        """Call the LLM and return parsed {"question": ..., "answer": ...}."""

    @staticmethod
    def parse_qa_response(text: str) -> dict:
        # Try to extract JSON from markdown code fences
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1)

        # Try to find a JSON object
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            text = brace_match.group(0)

        data = json.loads(text)
        if "question" not in data or "answer" not in data:
            raise ValueError("LLM response missing 'question' or 'answer' fields")
        return {"question": str(data["question"]), "answer": str(data["answer"])}


def create_llm_client(config: LLMConfig, api_key: str | None) -> LLMClient:
    if config.provider == "claude":
        from .claude import ClaudeClient
        return ClaudeClient(config, api_key)
    elif config.provider == "ollama":
        from .ollama import OllamaClient
        return OllamaClient(config)
    else:  # openai, custom
        from .openai_compat import OpenAICompatClient
        return OpenAICompatClient(config, api_key)
