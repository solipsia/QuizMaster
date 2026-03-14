from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .cleanup import audio_cleanup_loop
from .config import get_api_key, load_config
from .generator import QuestionGenerator
from .llm.base import create_llm_client
from .metrics import MetricsCollector
from .pool import QuestionPool
from .request_log import RequestLog
from .tts import PiperTTSClient
from .worker import BackfillWorker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load config
    config = load_config()
    config_ref = [config]  # Mutable ref for hot-reload

    # Audio directory
    audio_dir = Path(os.environ.get("QUIZ_AUDIO_DIR", "data/audio"))
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Core components
    metrics = MetricsCollector()
    request_log = RequestLog()
    pool = QuestionPool(audio_dir)

    # LLM + TTS clients
    api_key = get_api_key(config.llm.api_key_env)
    llm_client = create_llm_client(config.llm, api_key)
    tts_client = PiperTTSClient(config.tts)

    # Generator
    generator = QuestionGenerator(config, llm_client, tts_client, metrics, audio_dir)

    # Worker
    worker = BackfillWorker(pool, generator, config_ref, request_log)

    # Store on app state
    app.state.config_ref = config_ref
    app.state.audio_dir = audio_dir
    app.state.metrics = metrics
    app.state.request_log = request_log
    app.state.pool = pool
    app.state.llm_client = llm_client
    app.state.tts_client = tts_client
    app.state.generator = generator
    app.state.worker = worker

    # Start background tasks
    worker.start()
    cleanup_task = asyncio.create_task(
        audio_cleanup_loop(audio_dir, pool, config_ref)
    )

    logger.info("Quiz Service started — pool target: %d", config.pool.target_size)

    yield

    # Shutdown
    await worker.stop()
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    logger.info("Quiz Service stopped")


app = FastAPI(title="QuizMaster Quiz Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from .routers import admin, audio, quiz  # noqa: E402

app.include_router(quiz.router)
app.include_router(audio.router)
app.include_router(admin.router)
