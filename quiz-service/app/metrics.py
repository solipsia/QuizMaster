from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone

from .models import ErrorInfo, ErrorSummary, LatencyStats


class LatencyTracker:
    def __init__(self, maxlen: int = 100):
        self._samples: deque[tuple[float, int]] = deque(maxlen=maxlen)

    def record(self, value_ms: int) -> None:
        self._samples.append((time.time(), value_ms))

    def stats(self) -> LatencyStats:
        cutoff = time.time() - 3600
        values = [v for t, v in self._samples if t >= cutoff]
        if not values:
            return LatencyStats()
        values_sorted = sorted(values)
        p95_idx = max(0, int(len(values_sorted) * 0.95) - 1)
        return LatencyStats(
            last_ms=values[-1],
            avg_ms=int(sum(values) / len(values)),
            min_ms=min(values),
            max_ms=max(values),
            p95_ms=values_sorted[p95_idx],
            sample_count=len(values),
        )


class MetricsCollector:
    def __init__(self):
        self.llm = LatencyTracker()
        self.piper_tts = LatencyTracker()
        self.total_generation = LatencyTracker()
        self.api_quiz_response = LatencyTracker()
        self.questions_served: int = 0
        self.start_time: float = time.time()
        self._error_total: int = 0
        self._error_timestamps: deque[float] = deque(maxlen=500)
        self._last_error: ErrorInfo | None = None

    @property
    def uptime_seconds(self) -> int:
        return int(time.time() - self.start_time)

    def record_error(self, stage: str, message: str) -> None:
        now = time.time()
        self._error_total += 1
        self._error_timestamps.append(now)
        self._last_error = ErrorInfo(
            timestamp=datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            stage=stage,
            message=message,
        )

    def error_summary(self) -> ErrorSummary:
        cutoff = time.time() - 3600
        last_hour = sum(1 for t in self._error_timestamps if t >= cutoff)
        return ErrorSummary(
            last_hour=last_hour,
            total=self._error_total,
            last_error=self._last_error,
        )
