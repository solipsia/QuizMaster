from __future__ import annotations

from collections import deque

from .models import LogEntry


class RequestLog:
    def __init__(self, maxlen: int = 500):
        self._entries: deque[dict] = deque(maxlen=maxlen)

    def add(self, entry: LogEntry) -> None:
        self._entries.appendleft(entry.model_dump())

    def get(self, limit: int = 50) -> list[dict]:
        return list(self._entries)[:limit]
