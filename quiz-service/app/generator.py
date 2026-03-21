from __future__ import annotations

import json
import logging
import random
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

_RECENT_QUESTIONS_MAX = 50
_RECENT_QUESTIONS_FILE = "recent_questions.json"

logger = logging.getLogger(__name__)

from .config import get_api_key
from .llm.base import LLMClient
from .metrics import MetricsCollector
from .models import GenerationTime, QuizQuestion, ServiceConfig
from .tts import PiperTTSClient


class QuestionGenerator:
    def __init__(
        self,
        config: ServiceConfig,
        llm_client: LLMClient,
        tts_client: PiperTTSClient,
        metrics: MetricsCollector,
        audio_dir: Path,
    ):
        self.config = config
        self.llm_client = llm_client
        self.tts_client = tts_client
        self.metrics = metrics
        self.audio_dir = audio_dir
        self._recent: deque[str] = deque(maxlen=_RECENT_QUESTIONS_MAX)
        self._recent_path = audio_dir.parent / _RECENT_QUESTIONS_FILE
        self._load_recent()

    def _load_recent(self) -> None:
        try:
            data = json.loads(self._recent_path.read_text())
            for q in data[-_RECENT_QUESTIONS_MAX:]:
                self._recent.append(q)
            logger.info("Loaded %d recent questions from %s", len(self._recent), self._recent_path)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_recent(self) -> None:
        try:
            self._recent_path.write_text(json.dumps(list(self._recent)))
        except OSError as e:
            logger.warning("Failed to save recent questions: %s", e)

    async def generate_one(self, category: str | None = None) -> QuizQuestion:
        total_start = time.time()

        if category is None:
            enabled = [c for c in self.config.quiz.categories
                       if c not in self.config.quiz.disabled_categories]
            if not enabled:
                enabled = self.config.quiz.categories
            category = random.choice(enabled)

        # Build prompt with recent-question exclusion list
        prompt = self.config.quiz.system_prompt.replace(
            "{{category}}", category
        ).replace("{{difficulty}}", self.config.quiz.difficulty)

        if self._recent:
            recent_list = "\n".join(f"- {q}" for q in self._recent)
            prompt += (
                "\n\nDo NOT repeat any of these recently asked questions — "
                "generate something completely different:\n" + recent_list
            )

        # Call LLM
        llm_start = time.time()
        try:
            qa = await self.llm_client.generate(prompt)
        except Exception as e:
            self.metrics.record_error("llm", str(e))
            raise
        llm_ms = int((time.time() - llm_start) * 1000)
        self.metrics.llm.record(llm_ms)

        # Record spend/token usage
        usage = getattr(self.llm_client, "last_usage", {})
        if usage:
            self.metrics.record_spend(
                provider=self.config.llm.provider,
                model=self.config.llm.model,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )

        # Track to avoid repeats
        self._recent.append(qa["question"])
        self._save_recent()

        # Generate unique ID
        qid = uuid.uuid4().hex[:6]

        # TTS for question
        q_audio_path = self.audio_dir / f"{qid}_q.wav"
        tts_q_start = time.time()
        try:
            await self.tts_client.synthesize(qa["question"], q_audio_path)
        except Exception as e:
            self.metrics.record_error("piper_tts", str(e))
            raise
        tts_q_ms = int((time.time() - tts_q_start) * 1000)
        self.metrics.piper_tts.record(tts_q_ms)

        # TTS for answer
        a_audio_path = self.audio_dir / f"{qid}_a.wav"
        tts_a_start = time.time()
        try:
            await self.tts_client.synthesize(qa["answer"], a_audio_path)
        except Exception as e:
            self.metrics.record_error("piper_tts", str(e))
            raise
        tts_a_ms = int((time.time() - tts_a_start) * 1000)
        self.metrics.piper_tts.record(tts_a_ms)

        total_ms = int((time.time() - total_start) * 1000)
        self.metrics.total_generation.record(total_ms)

        return QuizQuestion(
            id=qid,
            category=category,
            difficulty=self.config.quiz.difficulty,
            question_text=qa["question"],
            answer_text=qa["answer"],
            question_audio_url=f"/audio/{qid}_q.wav",
            answer_audio_url=f"/audio/{qid}_a.wav",
            created_at=datetime.now(timezone.utc).isoformat(),
            generation_time_ms=GenerationTime(
                llm=llm_ms,
                piper_question=tts_q_ms,
                piper_answer=tts_a_ms,
                total=total_ms,
            ),
        )
