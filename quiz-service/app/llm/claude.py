from __future__ import annotations

import httpx

from ..models import LLMConfig
from .base import LLMClient


class ClaudeClient(LLMClient):
    def __init__(self, config: LLMConfig, api_key: str | None):
        self._config = config
        self._api_key = api_key

    async def generate(self, system_prompt: str) -> dict:
        if not self._api_key:
            raise RuntimeError(f"API key env var {self._config.api_key_env} is not set")

        url = f"{self._config.api_base_url.rstrip('/')}/v1/messages"
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": self._config.model,
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": "Generate one trivia question now."}
            ],
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()

        data = resp.json()
        usage = data.get("usage", {})
        self.last_usage = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }
        text = data["content"][0]["text"]
        return self.parse_qa_response(text)
