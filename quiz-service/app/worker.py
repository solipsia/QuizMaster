from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import datetime, timezone

from .generator import QuestionGenerator
from .models import LogEntry, ServiceConfig
from .pool import QuestionPool
from .request_log import RequestLog

logger = logging.getLogger(__name__)

_MIN_GENERATION_DELAY = 3.0
_AUTO_PAUSE_AFTER_ERRORS = 3


def _parse_retry_after(error_msg: str) -> float | None:
    m = re.search(r"retry in ([\d.]+)s", error_msg, re.IGNORECASE)
    return float(m.group(1)) if m else None


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
        self._paused = False
        self._pause_reason: str = ""
        self._consecutive_errors = 0
        self._backoff = 2

    @property
    def is_generating(self) -> bool:
        return self._generating

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def pause_reason(self) -> str:
        return self._pause_reason

    def pause(self, reason: str = "Manual") -> None:
        self._paused = True
        self._pause_reason = reason
        logger.info("Worker paused: %s", reason)

    def resume(self) -> None:
        self._paused = False
        self._pause_reason = ""
        self._consecutive_errors = 0
        self._backoff = 2
        logger.info("Worker resumed")
        self._wake.set()

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
                # Wait while paused
                if self._paused:
                    self._generating = False
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        pass
                    continue

                config = self.config_ref[0]
                enabled = [c for c in config.quiz.categories
                           if c not in config.quiz.disabled_categories]
                if not enabled:
                    enabled = config.quiz.categories
                missing = await self.pool.missing_categories(enabled)
                below_target = await self.pool.is_below_target(config)

                if below_target or missing:
                    self._generating = True
                    self._backoff = 2
                    # Prioritize categories that have zero questions
                    category = random.choice(missing) if missing else None
                    try:
                        q = await self.generator.generate_one(category)
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
                        self._consecutive_errors = 0
                        await asyncio.sleep(_MIN_GENERATION_DELAY)
                        continue
                    except Exception as e:
                        err = str(e)
                        logger.error("Backfill generation failed: %s", err)
                        self._consecutive_errors += 1

                        if self._consecutive_errors >= _AUTO_PAUSE_AFTER_ERRORS:
                            self.pause(
                                f"Auto-paused after {self._consecutive_errors} consecutive errors. "
                                f"Last: {err[:120]}"
                            )
                            continue

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
