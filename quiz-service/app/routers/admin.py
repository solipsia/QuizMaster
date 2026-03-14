from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from ..config import check_api_key_set, get_api_key, merge_config_update, save_config
from ..llm.base import create_llm_client
from ..models import (
    LatencyMetrics,
    LLMStatus,
    LogEntry,
    PiperStatus,
    StatusResponse,
)
from ..tts import PiperTTSClient

router = APIRouter()

STATIC_DIR = Path(__file__).parent.parent.parent / "static"


@router.get("/dashboard")
async def dashboard():
    return FileResponse(str(STATIC_DIR / "dashboard.html"), media_type="text/html")


@router.get("/config")
async def config_page():
    return FileResponse(str(STATIC_DIR / "config.html"), media_type="text/html")


@router.get("/api/admin/status")
async def get_status(request: Request):
    state = request.app.state
    config = state.config_ref[0]
    metrics = state.metrics
    pool = state.pool
    worker = state.worker

    pool_size = await pool.size()

    return StatusResponse(
        uptime_seconds=metrics.uptime_seconds,
        pool_size=pool_size,
        pool_target=config.pool.target_size,
        pool_generating=worker.is_generating,
        categories=config.quiz.categories,
        difficulty=config.quiz.difficulty,
        questions_served=metrics.questions_served,
        llm_api=LLMStatus(
            status="ok",
            provider=config.llm.provider,
            model=config.llm.model,
        ),
        piper_tts=PiperStatus(status="ok"),
        latency=LatencyMetrics(
            llm=metrics.llm.stats(),
            piper_tts=metrics.piper_tts.stats(),
            total_generation=metrics.total_generation.stats(),
            api_quiz_response=metrics.api_quiz_response.stats(),
        ),
        errors=metrics.error_summary(),
    ).model_dump()


@router.get("/api/admin/queue")
async def get_queue(request: Request):
    pool = request.app.state.pool
    return await pool.contents()


@router.get("/api/admin/log")
async def get_log(request: Request, limit: int = Query(50, ge=1, le=500)):
    return request.app.state.request_log.get(limit)


@router.post("/api/admin/test-llm")
async def test_llm(request: Request):
    """Test the LLM connection using the config submitted in the request body.
    Does not save config or affect the pool."""
    body = await request.json()
    try:
        from ..models import LLMConfig
        llm_cfg = LLMConfig(**body)
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": f"Invalid config: {e}"})

    api_key = get_api_key(llm_cfg.api_key_env)
    try:
        client = create_llm_client(llm_cfg, api_key)
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})

    test_prompt = "Reply with a single valid JSON object: {\"question\": \"What is 2+2?\", \"answer\": \"4\"}. No other text."
    t0 = time.time()
    try:
        result = await client.generate(test_prompt)
        latency_ms = int((time.time() - t0) * 1000)
        return {
            "ok": True,
            "latency_ms": latency_ms,
            "provider": llm_cfg.provider,
            "model": llm_cfg.model,
            "response": result,
        }
    except Exception as e:
        latency_ms = int((time.time() - t0) * 1000)
        return JSONResponse(
            status_code=200,
            content={"ok": False, "latency_ms": latency_ms, "error": str(e)},
        )


@router.post("/api/admin/generate")
async def force_generate(request: Request, category: str | None = Query(None)):
    state = request.app.state
    generator = state.generator
    pool = state.pool
    request_log = state.request_log

    start = time.time()
    try:
        question = await generator.generate_one(category)
        await pool.add(question)

        request_log.add(LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            endpoint="internal/generate",
            source="admin",
            question_id=question.id,
            llm_ms=question.generation_time_ms.llm,
            piper_ms=question.generation_time_ms.piper_question + question.generation_time_ms.piper_answer,
            total_ms=question.generation_time_ms.total,
            status="ok",
        ))

        base = str(request.base_url).rstrip("/")
        question.question_audio_url = f"{base}/audio/{question.id}_q.wav"
        question.answer_audio_url = f"{base}/audio/{question.id}_a.wav"
        return question.model_dump()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.delete("/api/admin/queue")
async def flush_queue(request: Request):
    state = request.app.state
    await state.pool.flush()
    state.worker.trigger()
    return {"status": "flushed"}


@router.get("/api/admin/config")
async def get_config(request: Request):
    config = request.app.state.config_ref[0]
    data = config.model_dump()
    # Replace API key with set/not-set status
    data["llm"]["api_key_set"] = check_api_key_set(config.llm.api_key_env)
    return data


@router.put("/api/admin/config")
async def update_config(request: Request):
    state = request.app.state
    body = await request.json()

    current = state.config_ref[0]
    old_quiz = current.quiz.model_dump()
    old_llm = current.llm.model_dump()

    try:
        new_config = merge_config_update(current, body)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    save_config(new_config)
    state.config_ref[0] = new_config

    # Rebuild LLM client if provider/model changed
    new_llm = new_config.llm.model_dump()
    if new_llm != old_llm:
        api_key = get_api_key(new_config.llm.api_key_env)
        state.llm_client = create_llm_client(new_config.llm, api_key)
        state.generator.llm_client = state.llm_client
        state.generator.config = new_config

    # Rebuild TTS client if settings changed
    state.tts_client = PiperTTSClient(new_config.tts)
    state.generator.tts_client = state.tts_client

    # Flush pool if quiz settings changed
    new_quiz = new_config.quiz.model_dump()
    if new_quiz != old_quiz:
        await state.pool.flush()
        state.worker.trigger()

    data = new_config.model_dump()
    data["llm"]["api_key_set"] = check_api_key_set(new_config.llm.api_key_env)
    return data
