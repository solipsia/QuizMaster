from __future__ import annotations

import asyncio
import logging

from .generator import QuestionGenerator
from .models import ServiceConfig
from .pool import QuestionPool
from .request_log import RequestLog
from .models import LogEntry
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class BackfillWorker:
    def __init__(
        self,
        pool: QuestionPool,
        generator: QuestionGenerator,
        config_ref: list[ServiceConfig],
        request_log: RequestLog,
    ):
        self.pool = pool
        self.generator = generator
        self.config_ref = config_ref
        self.request_log = request_log
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._generating = False
        self._backoff = 2

    @property
    def is_generating(self) -> bool:
        return self._generating

    def trigger(self) -> None:
        self._wake.set()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            try:
                config = self.config_ref[0]
                if await self.pool.is_below_target(config):
                    self._generating = True
                    self._backoff = 2
                    try:
                        q = await self.generator.generate_one()
                        await self.pool.add(q)
                        self.request_log.add(LogEntry(
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            endpoint="internal/generate",
                            source="pool-worker",
                            question_id=q.id,
                            llm_ms=q.generation_time_ms.llm,
                            piper_ms=q.generation_time_ms.piper_question + q.generation_time_ms.piper_answer,
                            total_ms=q.generation_time_ms.total,
                            status="ok",
                        ))
                        continue  # Check if more needed immediately
                    except Exception as e:
                        logger.error("Backfill generation failed: %s", e)
                        self._backoff = min(self._backoff * 2, 60)
                        await asyncio.sleep(self._backoff)
                        continue
                    finally:
                        self._generating = False
                else:
                    self._generating = False
                    # Wait for trigger or poll interval
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Worker loop error: %s", e)
                await asyncio.sleep(5)
