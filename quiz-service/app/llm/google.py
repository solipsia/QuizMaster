from __future__ import annotations

import httpx

from ..models import LLMConfig
from .base import LLMClient


class GoogleAIClient(LLMClient):
    def __init__(self, config: LLMConfig, api_key: str | None):
        self._config = config
        self._api_key = api_key

    async def generate(self, system_prompt: str) -> dict:
        if not self._api_key:
            raise RuntimeError(f"API key env var {self._config.api_key_env} is not set")
        api_key = self._api_key.strip()

        base = self._config.api_base_url.rstrip("/")
        model = self._config.model  # e.g. "models/gemini-2.5-flash"
        url = f"{base}/{model}:generateContent"

        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt}]
            },
            "contents": [
                {"role": "user", "parts": [{"text": "Generate one trivia question now."}]}
            ],
            "generationConfig": {
                "temperature": self._config.temperature,
                "maxOutputTokens": self._config.max_tokens,
            },
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                headers={"x-goog-api-key": api_key, "content-type": "application/json"},
                json=payload,
            )
            if not resp.is_success:
                try:
                    detail = resp.json()
                    msg = detail.get("error", {}).get("message", resp.text)
                except Exception:
                    msg = resp.text
                raise RuntimeError(f"Google AI {resp.status_code}: {msg}")

        data = resp.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected Google AI response: {data}") from e
        return self.parse_qa_response(text)
