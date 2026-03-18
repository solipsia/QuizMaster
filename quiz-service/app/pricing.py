"""Token pricing lookup for cost estimation.

Prices are in USD per million tokens: (input_per_mtok, output_per_mtok).
"""

from __future__ import annotations

PRICING: dict[str, tuple[float, float]] = {
    # ── Claude (Anthropic) ──
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-opus-4-1": (15.0, 75.0),
    "claude-opus-4": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-sonnet-3-7": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-3-5": (0.80, 4.0),
    "claude-haiku-3": (0.25, 1.25),
    # ── OpenAI ──
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.0, 30.0),
    "gpt-4": (30.0, 60.0),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o3-mini": (1.10, 4.40),
    # ── Groq (free tier — paid prices shown; set to 0 if on free plan) ──
    "llama-3.1-8b-instant": (0.0, 0.0),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-4-scout-17b-16e-instruct": (0.11, 0.34),
    "llama-4-maverick-17b-128e-instruct": (0.20, 0.60),
    "qwen-qwq-32b": (0.29, 0.59),
    "mixtral-8x7b-32768": (0.24, 0.24),
    # ── Google AI (Gemini) — paid tier ──
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.0),
}

# Runtime overrides from user config (set via set_overrides)
_overrides: dict[str, tuple[float, float]] = {}


def set_overrides(pricing_config: dict[str, list[float]]) -> None:
    """Load user price overrides from ServiceConfig.pricing."""
    global _overrides
    _overrides = {}
    for model, prices in pricing_config.items():
        if isinstance(prices, (list, tuple)) and len(prices) >= 2:
            _overrides[model] = (float(prices[0]), float(prices[1]))


def get_token_pricing(model: str) -> tuple[float, float] | None:
    """Return (input_$/MTok, output_$/MTok) or None if unknown.

    Checks user overrides first, then built-in defaults.
    Handles date-suffixed model IDs (e.g. claude-haiku-4-5-20251001)
    and 'models/' prefixed IDs (e.g. models/gemini-2.5-flash).
    """
    # Check overrides first (exact, then cleaned, then prefix)
    for table in (_overrides, PRICING):
        if model in table:
            return table[model]

        clean = model.removeprefix("models/")
        if clean in table:
            return table[clean]

        for key, price in table.items():
            if clean.startswith(key):
                return price

    return None


def get_all_pricing() -> list[dict]:
    """Return merged pricing table (defaults + overrides) for the config UI."""
    merged: dict[str, tuple[float, float]] = {}
    # Start with defaults
    for model, price in PRICING.items():
        merged[model] = price
    # Apply overrides (may add new models or update existing)
    for model, price in _overrides.items():
        merged[model] = price
    return [
        {"model": m, "input_per_mtok": p[0], "output_per_mtok": p[1]}
        for m, p in sorted(merged.items())
    ]
