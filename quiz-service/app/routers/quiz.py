from __future__ import annotations

import time
from datetime import datetime, timezone

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
    pool = request.app.state.pool
    metrics = request.app.state.metrics
    request_log = request.app.state.request_log
    worker = request.app.state.worker

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
