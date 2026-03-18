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

## Firmware (ESP32 DevKitV1)

MCU is the ELEGOO ESP32 DevKitV1 (ESP32-WROOM-32, Xtensa dual-core, CP2102 USB-serial). Test sketches live in `firmware/`. Flash with arduino-cli:
```
arduino-cli compile --fqbn esp32:esp32:esp32doit-devkit-v1 firmware/<sketch>
arduino-cli upload  --fqbn esp32:esp32:esp32doit-devkit-v1 --port COM21 firmware/<sketch>
```

### ESP32 DevKitV1 Pin Assignments

On the standard ESP32, GPIO numbers match directly — no D-pin mapping indirection. Use raw GPIO numbers in firmware code.

| GPIO | Function | Connected To |
|---|---|---|
| 25 | I2S BCLK | MAX98357A BCLK |
| 26 | I2S LRC (WSEL) | MAX98357A LRC |
| 33 | I2S DIN (DOUT) | MAX98357A DIN |
| 32 | Amp shutdown | MAX98357A SD pin |
| 23 | SPI MOSI | ILI9488 SDI + XPT2046 T_DIN |
| 18 | SPI SCK | ILI9488 SCK + XPT2046 T_CLK |
| 19 | SPI MISO | XPT2046 T_DO only (display SDO disconnected) |
| 15 | Display CS | ILI9488 CS |
| 2 | Display DC/RS | ILI9488 DC |
| 16 | Display RST | ILI9488 RESET |
| 21 | Touch CS | XPT2046 T_CS |
| 4 | Touch IRQ | XPT2046 T_IRQ (RTC GPIO — deep sleep wake source) |
| 35 | Battery voltage ADC | Voltage divider midpoint (100kΩ + 100kΩ from battery B+) |

**No physical buttons** — all user input via XPT2046 resistive touchscreen.

**GPIOs to avoid on ESP32 DevKitV1:** 0 (boot), 1 (TX0), 3 (RX0), 6–11 (flash), 12 (boot strapping). GPIOs 34–39 are input-only with no internal pull-ups.

**Deep sleep wake:** GPIO 4 (touch IRQ) is an RTC GPIO (RTC_GPIO10) and can serve as an `ext0` wake source — a screen touch can wake the device.

### Display: ILI9488 4" TFT (480×320, SPI) with XPT2046 Touch

- Library: **TFT_eSPI** by Bodmer. Configure in `User_Setup.h` (see TechnicalDesign.md for settings).
- **Critical:** Do NOT connect the display's SDO/MISO pin — it doesn't tristate and will interfere with the touch controller on the shared SPI bus. Only connect XPT2046 T_DO to GPIO 19.
- ILI9488 over SPI uses 18-bit colour (not 16-bit like ILI9341) — no DMA support in TFT_eSPI, somewhat slower rendering.
- Backlight (LED pin): tie to 3V3 for always-on, or connect to a GPIO for PWM brightness control.
- SPI clock: 27 MHz is the safe maximum for ILI9488 (40 MHz may cause artifacts).
- **Touch Y-axis is inverted**: With rotation 1 (landscape), `tft.getTouch()` returns Y values flipped. Apply `ty = tft.height() - 1 - ty` after reading. Calibration data: `{ 300, 3600, 300, 3600, 3 }`.

### I2S — use ESP-IDF 5.x API
Use `driver/i2s_std.h` (same API as before):
- `i2s_new_channel` / `i2s_channel_init_std_mode` / `i2s_channel_enable`
- `I2S_STD_MSB_SLOT_DEFAULT_CONFIG` works with MAX98357A
- See `firmware/speaker_test/speaker_test.ino` for working reference

### Quiz API response shape
`GET /api/quiz` returns:
```json
{ "id": "...", "question_text": "...", "answer_text": "...",
  "question_audio_url": "http://synology.local:8080/audio/....wav",
  "answer_audio_url":   "http://synology.local:8080/audio/....wav" }
```
Audio URLs are fully qualified — do not prepend the base URL.

## Known Issues & Gotchas

- **New API key env vars**: Adding a new LLM provider requires adding its key to `docker-compose.yml` environment section AND redeploying — Portainer env vars alone are not enough
- **config.json on volume wins**: If something is broken in config, fix it via the `/config` page and save, or shell into the container and edit `/data/config.json` directly
- **Google AI intermittent 400 "API key expired"**: Usually resolves itself; also try stripping whitespace from the key. Confirmed fixed by adding `api_key.strip()` in `llm/google.py`
- **piper-tts first run**: The voice model download (from HuggingFace) happens on first synthesis call, not on startup — expect a long delay on the first question after a fresh deploy
- **ILI9488 display SDO/MISO**: Never connect the display's SDO pin to the SPI bus — it doesn't tristate when CS is high and will corrupt touch controller reads. Leave it disconnected.
