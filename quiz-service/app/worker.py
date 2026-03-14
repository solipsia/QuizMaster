from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from .generator import QuestionGenerator
from .models import LogEntry, ServiceConfig
from .pool import QuestionPool
from .request_log import RequestLog

logger = logging.getLogger(__name__)

# Minimum seconds between successive generation calls.
# Free tier Gemini is 10-20 RPM; 7s gives ~8 RPM, well within limits.
_MIN_GENERATION_DELAY = 7.0


def _parse_retry_after(error_msg: str) -> float | None:
    """Extract retry delay in seconds from a 429 error message."""
    m = re.search(r"retry in ([\d.]+)s", error_msg, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


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
                        # Pace successive generations to respect API rate limits
                        await asyncio.sleep(_MIN_GENERATION_DELAY)
                        continue
                    except Exception as e:
                        err = str(e)
                        logger.error("Backfill generation failed: %s", err)

                        # Honour 429 retry-after if present
                        if "429" in err:
                            retry_after = _parse_retry_after(err) or 60.0
                            logger.warning("Rate limited — waiting %.0fs", retry_after)
                            await asyncio.sleep(retry_after)
                        else:
                            self._backoff = min(self._backoff * 2, 60)
                            await asyncio.sleep(self._backoff)
                        continue
                    finally:
                        self._generating = False
                else:
                    self._generating = False
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
