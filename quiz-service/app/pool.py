from __future__ import annotations

import asyncio
import os
from pathlib import Path

from .models import QuizQuestion, ServiceConfig


class QuestionPool:
    def __init__(self, audio_dir: Path):
        self._questions: list[QuizQuestion] = []
        self._lock = asyncio.Lock()
        self._audio_dir = audio_dir

    async def pop(self, category: str | None = None) -> QuizQuestion | None:
        async with self._lock:
            for i, q in enumerate(self._questions):
                if category is None or q.category == category:
                    return self._questions.pop(i)
            return None

    async def add(self, question: QuizQuestion) -> None:
        async with self._lock:
            self._questions.append(question)

    async def flush(self) -> None:
        async with self._lock:
            for q in self._questions:
                self._delete_audio(q)
            self._questions.clear()

    async def contents(self) -> list[dict]:
        async with self._lock:
            return [q.model_dump() for q in self._questions]

    async def size(self, category: str | None = None) -> int:
        async with self._lock:
            if category is None:
                return len(self._questions)
            return sum(1 for q in self._questions if q.category == category)

    async def needs_backfill(self, config: ServiceConfig) -> bool:
        async with self._lock:
            return len(self._questions) < config.pool.backfill_trigger

    async def is_below_target(self, config: ServiceConfig) -> bool:
        async with self._lock:
            return len(self._questions) < config.pool.target_size

    def _delete_audio(self, q: QuizQuestion) -> None:
        for suffix in ("_q.wav", "_a.wav"):
            path = self._audio_dir / f"{q.id}{suffix}"
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
