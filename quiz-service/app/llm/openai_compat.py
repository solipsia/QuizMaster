from __future__ import annotations

import httpx

from ..models import LLMConfig
from .base import LLMClient


class OpenAICompatClient(LLMClient):
    def __init__(self, config: LLMConfig, api_key: str | None):
        self._config = config
        self._api_key = api_key

    async def generate(self, system_prompt: str) -> dict:
        url = f"{self._config.api_base_url.rstrip('/')}/chat/completions"
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": self._config.model,
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate one trivia question now."},
            ],
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()

        data = resp.json()
        usage = data.get("usage", {})
        self.last_usage = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }
        text = data["choices"][0]["message"]["content"]
        return self.parse_qa_response(text)
