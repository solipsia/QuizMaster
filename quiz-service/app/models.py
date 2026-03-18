from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class GenerationTime(BaseModel):
    llm: int = 0
    piper_question: int = 0
    piper_answer: int = 0
    total: int = 0


class QuizQuestion(BaseModel):
    id: str
    category: str
    difficulty: str
    question_text: str
    answer_text: str
    question_audio_url: str = ""
    answer_audio_url: str = ""
    created_at: str = ""
    served: bool = False
    generation_time_ms: GenerationTime = GenerationTime()


class QuizResponse(BaseModel):
    id: str
    category: str
    difficulty: str
    question_text: str
    answer_text: str
    question_audio_url: str
    answer_audio_url: str


class LatencyStats(BaseModel):
    last_ms: int = 0
    avg_ms: int = 0
    min_ms: int = 0
    max_ms: int = 0
    p95_ms: int = 0
    sample_count: int = 0


class ErrorInfo(BaseModel):
    timestamp: str = ""
    stage: str = ""
    message: str = ""


class ErrorSummary(BaseModel):
    last_hour: int = 0
    total: int = 0
    last_error: Optional[ErrorInfo] = None


class LLMStatus(BaseModel):
    status: str = "unknown"
    provider: str = ""
    model: str = ""


class PiperStatus(BaseModel):
    status: str = "unknown"


class LatencyMetrics(BaseModel):
    llm: LatencyStats = LatencyStats()
    piper_tts: LatencyStats = LatencyStats()
    total_generation: LatencyStats = LatencyStats()
    api_quiz_response: LatencyStats = LatencyStats()


class SpendEntry(BaseModel):
    provider: str = ""
    model: str = ""
    api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: Optional[float] = None


class SpendAnalytics(BaseModel):
    total_api_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_estimated_cost_usd: Optional[float] = None
    by_model: list[SpendEntry] = []


class StatusResponse(BaseModel):
    uptime_seconds: int = 0
    pool_size: int = 0
    pool_target: int = 0
    pool_generating: bool = False
    pool_paused: bool = False
    pool_pause_reason: str = ""
    categories: list[str] = []
    difficulty: str = "medium"
    questions_served: int = 0
    llm_api: LLMStatus = LLMStatus()
    piper_tts: PiperStatus = PiperStatus()
    latency: LatencyMetrics = LatencyMetrics()
    errors: ErrorSummary = ErrorSummary()
    spend: SpendAnalytics = SpendAnalytics()


class LogEntry(BaseModel):
    timestamp: str
    endpoint: str
    source: str
    question_id: str = ""
    response_ms: int = 0
    llm_ms: int = 0
    piper_ms: int = 0
    total_ms: int = 0
    status: str | int = 200


class LLMConfig(BaseModel):
    provider: str = "claude"
    model: str = "claude-sonnet-4-20250514"
    api_base_url: str = "https://api.anthropic.com"
    api_key_env: str = "ANTHROPIC_API_KEY"
    temperature: float = 0.9
    max_tokens: int = 1024


class TTSConfig(BaseModel):
    piper_url: str = "piper:10300"
    voice_model: str = "en_US-lessac-medium"
    sample_rate: int = 22050
    output_format: str = "wav"


class PoolConfig(BaseModel):
    target_size: int = 10
    min_ready: int = 3
    backfill_trigger: int = 5
    audio_ttl_minutes: int = 60


class QuizConfig(BaseModel):
    categories: list[str] = [
        "general", "science", "history", "geography", "entertainment", "sports"
    ]
    difficulty: str = "medium"
    system_prompt: str = (
        "You are a quiz master. Generate a trivia question and answer. "
        "The category is {{category}} and the difficulty level is {{difficulty}}. "
        "Return JSON with 'question' and 'answer' fields."
    )


class DeviceConfig(BaseModel):
    idle_timeout_seconds: int = 300
    welcome_text: str = "Welcome to Quiz Master"


class ServiceConfig(BaseModel):
    llm: LLMConfig = LLMConfig()
    tts: TTSConfig = TTSConfig()
    pool: PoolConfig = PoolConfig()
    quiz: QuizConfig = QuizConfig()
    device: DeviceConfig = DeviceConfig()
