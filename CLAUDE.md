# QuizMaster — Claude Code Reference

Full system design is in `TechnicalDesign.md`. This file covers operational knowledge needed to work on the codebase.

## Repository & Deployment

- **Repo**: `https://github.com/solipsia/QuizMaster` (branch: `master`)
- **Deploy workflow**: `git push` → Portainer → Pull and Redeploy (Git stack, Repository build method)
- **NAS**: `http://synology.local/` — Portainer at port 9000
- **Service URL**: `http://synology.local:8080` (host 8080 → container 8000)
- **Dashboard**: `http://synology.local:8080/dashboard`
- **Config page**: `http://synology.local:8080/config`

## Project Layout

```
quiz-service/
  app/
    main.py           # FastAPI app factory, lifespan, CORS, all state on app.state
    models.py         # All Pydantic models (StatusResponse, QuizQuestion, ServiceConfig, etc.)
    config.py         # Config load/save, deep merge, get_api_key(), check_api_key_set()
    pool.py           # Async-safe QuestionPool (asyncio.Lock)
    worker.py         # BackfillWorker — pause/resume, auto-pause after 3 errors, 429 handling
    generator.py      # Orchestrates LLM → TTS question → TTS answer → QuizQuestion
    tts.py            # piper-tts Python library, auto-downloads voice from HuggingFace
    metrics.py        # LatencyTracker (rolling deque), MetricsCollector
    request_log.py    # Ring buffer deque(maxlen=500)
    cleanup.py        # Audio TTL cleanup loop
    llm/
      base.py         # Abstract LLMClient, parse_qa_response, create_llm_client() factory
      google.py       # Google AI (Gemini) — x-goog-api-key header
      claude.py       # Anthropic Messages API
      openai_compat.py# OpenAI / Groq / any OpenAI-compatible (Bearer token)
      ollama.py       # Ollama /api/chat
    routers/
      admin.py        # All /api/admin/* and /dashboard, /config endpoints
      quiz.py         # GET /api/quiz
      audio.py        # GET /audio/{filename} with path traversal protection
  static/
    dashboard.html    # Debug dashboard — single-file vanilla HTML/CSS/JS, no dependencies
    config.html       # Config page — same
  Dockerfile          # python:3.11-slim (NOT 3.12 — piper-phonemize has no py3.12 wheels)
  docker-compose.yml  # Single service, named volume quiz-data, all API key env vars
  requirements.txt    # includes piper-tts==1.2.0
  config.default.json # Default config (Google AI / Gemini)
```

## Key Architectural Decisions

### TTS: piper-tts Python library (not Wyoming protocol)
`piper-tts` runs inside the quiz-service container. There is no separate piper container.
- Voice models auto-download from HuggingFace to `/data/models` on first use
- `espeak-ng` and `libespeak-ng1` must be installed in the Dockerfile (required by piper-phonemize)
- The `tts.piper_url` config field is vestigial (kept for config schema compatibility) — it is not used

### Config persistence
- `/data/config.json` on the Docker named volume overrides `config.default.json` at startup
- API keys are **never stored in config.json** — only the env var name (e.g. `GOOGLE_API_KEY`) is stored
- All four API key env vars must be explicitly listed in `docker-compose.yml` environment section, otherwise they are not passed to the container even if set in Portainer

### State
All runtime state lives on `app.state`: `pool`, `worker`, `generator`, `llm_client`, `tts_client`, `metrics`, `request_log`, `config_ref` (a one-element list so it can be mutated in place).

## LLM Providers

| Provider | `provider` value | Notes |
|---|---|---|
| Google AI (Gemini) | `google` | Default. `x-goog-api-key` header. Free tier: 30 RPD on gemini-2.5-flash |
| Anthropic Claude | `claude` | Messages API |
| Groq | `openai` | OpenAI-compatible. Base URL: `https://api.groq.com/openai/v1`, env: `GROQ_API_KEY` |
| OpenAI | `openai` | Standard |
| Ollama | `ollama` | Local, no key needed |

Default config uses `models/gemini-2.5-flash` with `GOOGLE_API_KEY`.

## Worker Behaviour

- Generates one question at a time, 3s minimum delay between generations (`_MIN_GENERATION_DELAY`)
- Auto-pauses after 3 consecutive errors (`_AUTO_PAUSE_AFTER_ERRORS`) with reason shown on dashboard
- Parses `retry in Xs` from 429 responses and waits that long
- Manual pause/resume via dashboard buttons or `POST /api/admin/worker/pause|resume`
- On resume: resets consecutive error count and backoff timer

## Frontends

Both pages are single self-contained HTML files with inline CSS and JS. No build step, no external dependencies.
- **Aesthetic**: dark industrial/mission-control theme, JetBrains Mono + DM Sans fonts
- **Auto-refresh**: dashboard polls every 5s (`/api/admin/status`, `/api/admin/queue`, `/api/admin/log`)
- When editing either HTML file, preserve the existing aesthetic exactly — only change what was asked

## Docker & Build

- Base image: `python:3.11-slim` — must stay on 3.11, not 3.12
- `apt-get install espeak-ng libespeak-ng1` required before `pip install`
- Named volume `quiz-data` persists: audio files, voice models, config.json
- Port mapping: `8080:8000`

## Known Issues & Gotchas

- **New API key env vars**: Adding a new LLM provider requires adding its key to `docker-compose.yml` environment section AND redeploying — Portainer env vars alone are not enough
- **config.json on volume wins**: If something is broken in config, fix it via the `/config` page and save, or shell into the container and edit `/data/config.json` directly
- **Google AI intermittent 400 "API key expired"**: Usually resolves itself; also try stripping whitespace from the key. Confirmed fixed by adding `api_key.strip()` in `llm/google.py`
- **piper-tts first run**: The voice model download (from HuggingFace) happens on first synthesis call, not on startup — expect a long delay on the first question after a fresh deploy
