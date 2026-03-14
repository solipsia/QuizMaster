from __future__ import annotations

import asyncio
import time
from pathlib import Path

from .models import ServiceConfig
from .pool import QuestionPool


async def audio_cleanup_loop(
    audio_dir: Path,
    pool: QuestionPool,
    config_ref: list[ServiceConfig],
    interval_seconds: int = 300,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            ttl_minutes = config_ref[0].pool.audio_ttl_minutes
            cutoff = time.time() - (ttl_minutes * 60)

            pool_contents = await pool.contents()
            referenced_files = set()
            for q in pool_contents:
                referenced_files.add(f"{q['id']}_q.wav")
                referenced_files.add(f"{q['id']}_a.wav")

            for f in audio_dir.glob("*.wav"):
                if f.name in referenced_files:
                    continue
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
        except Exception:
            pass
