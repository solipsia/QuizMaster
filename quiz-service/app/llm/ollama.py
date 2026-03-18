from __future__ import annotations

import httpx

from ..models import LLMConfig
from .base import LLMClient


class OllamaClient(LLMClient):
    def __init__(self, config: LLMConfig):
        self._config = config

    async def generate(self, system_prompt: str) -> dict:
        url = f"{self._config.api_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self._config.model,
            "stream": False,
            "options": {
                "temperature": self._config.temperature,
            },
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate one trivia question now."},
            ],
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()

        data = resp.json()
        self.last_usage = {
            "input_tokens": data.get("prompt_eval_count", 0),
            "output_tokens": data.get("eval_count", 0),
        }
        text = data["message"]["content"]
        return self.parse_qa_response(text)
