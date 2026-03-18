from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone

from .models import ErrorInfo, ErrorSummary, LatencyStats, SpendAnalytics, SpendEntry
from .pricing import get_token_pricing


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
        self._spend: dict[tuple[str, str], dict] = {}

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

    def record_spend(self, provider: str, model: str, input_tokens: int, output_tokens: int) -> None:
        key = (provider, model)
        if key not in self._spend:
            self._spend[key] = {"api_calls": 0, "input_tokens": 0, "output_tokens": 0}
        self._spend[key]["api_calls"] += 1
        self._spend[key]["input_tokens"] += input_tokens
        self._spend[key]["output_tokens"] += output_tokens

    def spend_analytics(self) -> SpendAnalytics:
        entries = []
        total_calls = 0
        total_in = 0
        total_out = 0
        total_cost = 0.0
        has_pricing = False

        for (provider, model), data in self._spend.items():
            input_tokens = data["input_tokens"]
            output_tokens = data["output_tokens"]

            pricing = get_token_pricing(model)
            cost = None
            if pricing:
                cost = round(
                    (input_tokens / 1_000_000) * pricing[0]
                    + (output_tokens / 1_000_000) * pricing[1],
                    6,
                )
                total_cost += cost
                has_pricing = True

            entries.append(SpendEntry(
                provider=provider,
                model=model,
                api_calls=data["api_calls"],
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=cost,
            ))
            total_calls += data["api_calls"]
            total_in += input_tokens
            total_out += output_tokens

        return SpendAnalytics(
            total_api_calls=total_calls,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_estimated_cost_usd=round(total_cost, 6) if has_pricing else None,
            by_model=entries,
        )

    def error_summary(self) -> ErrorSummary:
        cutoff = time.time() - 3600
        last_hour = sum(1 for t in self._error_timestamps if t >= cutoff)
        return ErrorSummary(
            last_hour=last_hour,
            total=self._error_total,
            last_error=self._last_error,
        )
