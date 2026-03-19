from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..models import LogEntry

router = APIRouter()


@router.get("/api/quiz")
async def get_quiz(
    request: Request,
    category: str | None = Query(None),
    source: str = Query("device"),
):
    start = time.time()
    state = request.app.state
    pool = state.pool
    metrics = state.metrics
    request_log = state.request_log
    worker = state.worker
    config = state.config_ref[0]

    # Easter egg injection
    ee = config.easter_egg
    if ee.enabled and ee.question_text and ee.answer_text and ee.probability_percent > 0:
        audio_dir: Path = state.audio_dir
        q_audio = audio_dir / "easter_egg_q.wav"
        a_audio = audio_dir / "easter_egg_a.wav"
        if q_audio.exists() and a_audio.exists():
            if random.randint(1, 100) <= ee.probability_percent:
                base = str(request.base_url).rstrip("/")
                response_ms = int((time.time() - start) * 1000)
                metrics.api_quiz_response.record(response_ms)
                metrics.record_question_served()
                request_log.add(LogEntry(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    endpoint="/api/quiz",
                    source=source,
                    question_id="easter_egg",
                    response_ms=response_ms,
                    status=200,
                ))
                return {
                    "id": "easter_egg",
                    "category": "easter_egg",
                    "difficulty": config.quiz.difficulty,
                    "question_text": ee.question_text,
                    "answer_text": ee.answer_text,
                    "question_audio_url": f"{base}/audio/easter_egg_q.wav",
                    "answer_audio_url": f"{base}/audio/easter_egg_a.wav",
                }

    question = await pool.pop(category)
    if question is None:
        return JSONResponse(
            status_code=503,
            content={"error": "No questions available"},
        )

    # Build full audio URLs
    base = str(request.base_url).rstrip("/")
    question.question_audio_url = f"{base}/audio/{question.id}_q.wav"
    question.answer_audio_url = f"{base}/audio/{question.id}_a.wav"
    question.served = True

    response_ms = int((time.time() - start) * 1000)
    metrics.api_quiz_response.record(response_ms)
    metrics.record_question_served()

    request_log.add(LogEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        endpoint="/api/quiz",
        source=source,
        question_id=question.id,
        response_ms=response_ms,
        status=200,
    ))

    # Trigger backfill
    worker.trigger()

    return {
        "id": question.id,
        "category": question.category,
        "difficulty": question.difficulty,
        "question_text": question.question_text,
        "answer_text": question.answer_text,
        "question_audio_url": question.question_audio_url,
        "answer_audio_url": question.answer_audio_url,
    }
