# QuizMaster — Design Reference

## Overview

Tabletop quiz device built around an ESP32 DevKitV1 (ELEGOO ESP32-WROOM-32). The user taps the touchscreen to receive a quiz question read aloud and shown on-screen, then taps again to hear and see the answer. A backend Quiz Service running on a local Synology NAS pre-generates questions using a configurable LLM and Piper TTS so they are available instantly when the device requests one.

## Functional Architecture

### System Components

1. **QuizMaster device** — ESP32 DevKitV1 with speaker, 4" ILI9488 TFT touchscreen display, and USB power.
2. **Quiz Service** — Web service running on the Synology NAS. Maintains a pool of pre-generated quiz questions. When the device requests a question, it returns one immediately from the pool and backfills asynchronously. Internally calls a configurable LLM API for question generation and Piper TTS for audio synthesis. Also serves the Debug Dashboard and Configuration page.
3. **Debug Dashboard** — Single-page web UI served by the Quiz Service at `/dashboard`. Mirrors the device quiz flow (same API), shows live queue state, service health, and request logs. Used to test and debug the backend without the hardware.
4. **Configuration page** — Web UI served at `/config`. All Quiz Service settings (LLM provider, API keys, TTS config, pool size, categories, etc.) are managed here and persisted to a local JSON file.
5. **Piper TTS** — Text-to-speech engine running on the NAS (Docker). Called by the Quiz Service, not directly by the device.
6. **LLM API** — Configurable provider (Claude, OpenAI, Ollama, etc.) called by the Quiz Service to generate quiz content. Provider and model are selected in the Configuration page.

### Quiz Service Pre-generation

The Quiz Service maintains a ready pool of N pre-generated Q&A pairs (target: 5–10). On startup and after each question is served, it backfills the pool asynchronously. This decouples the LLM + Piper latency (potentially 10–20s) from the device request latency (<1s).

```
[Pool: 5–10 ready Q&A pairs]
    Device requests question --> return one from pool instantly
    Pool drops below threshold --> background worker generates more
    Worker: LLM API (generate text) --> Piper TTS (generate audio) --> add to pool
```

The pool should track which questions have been served to avoid repeats within a session. Questions are ephemeral — no long-term storage is needed.

### Device State Machine

```
[IDLE / SPLASH] --Touch "New Question"--> [CONNECT WIFI if needed]
    --> [REQUEST QUESTION from Quiz Service]
    --> [RECEIVE JSON: question text, answer text, audio URLs]
    --> [DISPLAY question text on TFT]
    --> [STREAM question audio from URL via I2S]
    --> [WAITING FOR ANSWER TAP]
        --Touch "Reveal Answer"--> [DISPLAY answer text]
            --> [STREAM answer audio from URL via I2S]
            --> [PREFETCH next question JSON in background]
            --> [WAITING FOR NEXT]
        --Touch "New Question"--> [USE prefetched question, or REQUEST if none ready]
            --> (repeat cycle)
        --Touch "Category"--> [Cycle quiz category]
        --Timeout (no touch for N minutes)--> [AMP OFF] --> [DEEP SLEEP]
```

**Prefetch strategy**: After the answer is revealed, the device fetches the next question's JSON in the background while the user reads the answer. This makes the next "New Question" tap feel instant — only audio streaming remains. If the prefetch hasn't completed when the user taps, fall back to a synchronous request.

### Quiz Service API

**Get a question:**

```
GET http://<NAS_IP>:<PORT>/api/quiz?category=<CATEGORY>
```

The `category` parameter is optional. If omitted, the service picks from all categories. The device cycles the category via a touchscreen button and displays the current category on screen.

Response:

```json
{
  "id": "a1b2c3",
  "category": "science",
  "difficulty": "medium",
  "question_text": "...",
  "answer_text": "...",
  "question_audio_url": "http://<NAS_IP>:<PORT>/audio/a1b2c3_q.wav",
  "answer_audio_url": "http://<NAS_IP>:<PORT>/audio/a1b2c3_a.wav"
}
```

**Stream audio:**

```
GET http://<NAS_IP>:<PORT>/audio/<id>_q.wav
GET http://<NAS_IP>:<PORT>/audio/<id>_a.wav
```

Audio is streamed on demand — question audio immediately after receiving the JSON, answer audio on "Reveal Answer" tap. The Quiz Service keeps generated audio files available for a reasonable TTL (e.g. 1 hour) before cleanup.

### Admin API

These endpoints are used by the Debug Dashboard and are not called by the device.

**Service status:**

```
GET /api/admin/status
```

```json
{
  "uptime_seconds": 84320,
  "pool_size": 7,
  "pool_target": 10,
  "pool_generating": true,
  "categories": ["science", "history", "geography", "general"],
  "difficulty": "medium",
  "questions_served": 42,
  "llm_api": {
    "status": "ok",
    "provider": "claude",
    "model": "claude-sonnet-4-20250514"
  },
  "piper_tts": {
    "status": "ok"
  },
  "latency": {
    "llm": { "last_ms": 3200, "avg_ms": 2950, "min_ms": 1800, "max_ms": 5400, "p95_ms": 4800, "sample_count": 42 },
    "piper_tts": { "last_ms": 1800, "avg_ms": 1650, "min_ms": 900, "max_ms": 3100, "p95_ms": 2700, "sample_count": 84 },
    "total_generation": { "last_ms": 6500, "avg_ms": 6100, "min_ms": 3800, "max_ms": 9200, "p95_ms": 8500, "sample_count": 42 },
    "api_quiz_response": { "last_ms": 45, "avg_ms": 38, "min_ms": 12, "max_ms": 210, "p95_ms": 85, "sample_count": 42 }
  },
  "errors": {
    "last_hour": 0,
    "total": 3,
    "last_error": { "timestamp": "2026-03-14T08:12:33Z", "stage": "llm", "message": "timeout after 30s" }
  }
}
```

Latency metrics are computed over a rolling window (last 100 samples or last hour, whichever is smaller). The four latency categories track:
- `llm` — time for the LLM API to return generated text
- `piper_tts` — time for Piper to synthesize one audio clip (tracked per clip, so ~2x the question count)
- `total_generation` — end-to-end time to produce one complete Q&A pair (LLM + question audio + answer audio)
- `api_quiz_response` — time for the Quiz Service to respond to a device `/api/quiz` request (should be fast if pool has ready items)

**Queue contents:**

```
GET /api/admin/queue
```

```json
[
  {
    "id": "a1b2c3",
    "category": "science",
    "difficulty": "medium",
    "question_text": "What is the speed of light?",
    "answer_text": "Approximately 299,792 km/s",
    "question_audio_url": "/audio/a1b2c3_q.wav",
    "answer_audio_url": "/audio/a1b2c3_a.wav",
    "created_at": "2026-03-14T10:23:45Z",
    "served": false,
    "generation_time_ms": { "llm": 3200, "piper_question": 1800, "piper_answer": 1500, "total": 6500 }
  }
]
```

**Request log (recent activity):**

```
GET /api/admin/log?limit=50
```

```json
[
  {
    "timestamp": "2026-03-14T10:30:12Z",
    "endpoint": "/api/quiz",
    "source": "device",
    "question_id": "a1b2c3",
    "response_ms": 45,
    "status": 200
  },
  {
    "timestamp": "2026-03-14T10:30:08Z",
    "endpoint": "internal/generate",
    "source": "pool-worker",
    "question_id": "d4e5f6",
    "llm_ms": 3100,
    "piper_ms": 3400,
    "total_ms": 6500,
    "status": "ok"
  }
]
```

**Force-generate a question (bypass pool):**

```
POST /api/admin/generate?category=<CATEGORY>
```

Returns the generated question JSON immediately (synchronous — will take 5–20s). Useful for testing LLM prompt changes or Piper voice settings without waiting for pool rotation.

**Flush the queue:**

```
DELETE /api/admin/queue
```

Clears all pre-generated questions and triggers a fresh pool fill. Useful after changing prompts or categories.

### Debug Dashboard

Served as a single HTML page at `http://<NAS_IP>:<PORT>/dashboard`. No build step — vanilla HTML, CSS, and JavaScript served directly by the Quiz Service. All data comes from the device API (`/api/quiz`, `/audio/*`) and admin API (`/api/admin/*`).

The dashboard is a single-page technical interface with the following panels:

#### Panel Layout

```
+-----------------------------------------------------------------------+
|  QuizMaster Debug Dashboard                          [Auto-refresh: 5s]|
+-----------------------------------------------------------------------+
|                           |                                            |
|   SERVICE STATUS          |   QUIZ PLAYER                              |
|   - Uptime: 23h 25m      |   - [Get Question] [Reveal Answer] [Next] |
|   - Questions served: 42  |   - Category: [All ▼]  Difficulty: medium |
|   - Errors (1h/total):   |   - Question text display area             |
|     0 / 3                 |   - Answer text display area (hidden       |
|   - Last error:           |     until revealed)                        |
|     08:12 llm timeout     |   - Audio player: question ▶               |
|                           |   - Audio player: answer ▶                 |
|   POOL STATUS             |   - Raw JSON response (collapsible)        |
|   - Pool: 7/10 ready      |                                            |
|   - Generating: yes       |                                            |
|   - [Force Generate]      |                                            |
|   - [Flush Queue]         |                                            |
|                           |                                            |
+-----------------------------------------------------------------------+
|                                                                        |
|   LATENCY METRICS (rolling window)                                     |
|   +--------------------+--------+--------+--------+--------+--------+ |
|   | Stage              | Last   | Avg    | Min    | Max    | P95    | |
|   +--------------------+--------+--------+--------+--------+--------+ |
|   | LLM API            | 3.2s   | 2.95s  | 1.8s   | 5.4s   | 4.8s   | |
|   | Piper TTS          | 1.8s   | 1.65s  | 0.9s   | 3.1s   | 2.7s   | |
|   | Total generation   | 6.5s   | 6.1s   | 3.8s   | 9.2s   | 8.5s   | |
|   | Quiz API response  | 45ms   | 38ms   | 12ms   | 210ms  | 85ms   | |
|   +--------------------+--------+--------+--------+--------+--------+ |
|   LLM: claude / claude-sonnet-4  |  Piper: ✓ connected                |
|                                                                        |
+-----------------------------------------------------------------------+
|                                                                        |
|   QUESTION QUEUE                                                       |
|   +----+----------+--------+---------------------------+------+------+ |
|   | ID | Category | Diff.  | Question (truncated)      | Status| Gen | |
|   +----+----------+--------+---------------------------+------+------+ |
|   | a1 | science  | medium | What is the speed of...   | ready | 6.5s| |
|   | b2 | history  | medium | In what year did the...   | ready | 5.8s| |
|   | c3 | science  | medium | Which element has the...  | gen...| --  | |
|   +----+----------+--------+---------------------------+------+------+ |
|   Click row to expand full question/answer text and play audio         |
|                                                                        |
+-----------------------------------------------------------------------+
|                                                                        |
|   REQUEST LOG                                                          |
|   +---------------------+----------------+--------+--------+------+   |
|   | Timestamp           | Endpoint       | Source | Resp   | HTTP |   |
|   +---------------------+----------------+--------+--------+------+   |
|   | 10:30:12            | /api/quiz      | device | 45ms   | 200  |   |
|   | 10:30:08            | internal/gen   | worker | 6500ms | ok   |   |
|   | 10:29:55            | /api/quiz      | dash   | 38ms   | 200  |   |
|   +---------------------+----------------+--------+--------+------+   |
|                                                                        |
+-----------------------------------------------------------------------+
```

#### Panel Details

**Service Status** — Auto-refreshes via polling `/api/admin/status`. Shows uptime, questions served, error counts (last hour and total), and last error details. Status indicators use colour: green = ok, red = error, yellow = slow (>5s).

**Pool Status** — Shows current pool count vs target, whether the background worker is actively generating, and action buttons to force-generate or flush. Part of the status panel.

**Latency Metrics** — Table showing measured performance for every stage of the pipeline: LLM API call, Piper TTS synthesis, total end-to-end generation, and Quiz API response time to the device. Each row shows last, average, min, max, and P95 values over a rolling window. Also shows the current LLM provider/model and Piper connection status. This is the primary tool for identifying bottlenecks — if LLM latency is high, consider a faster model; if Quiz API response is high, the pool may be draining faster than it fills.

**Quiz Player** — Mirrors the device UX using the same `/api/quiz` and `/audio/*` endpoints. Three buttons match the touchscreen UI: Get Question, Reveal Answer, and a category dropdown. Shows the current difficulty level. Audio plays through the browser using `<audio>` elements pointed at the audio URLs. Shows the raw JSON response in a collapsible block for debugging.

**Question Queue** — Table showing every item in the pre-generated pool. Each row shows ID, category, difficulty, truncated question text, status (ready/generating/error), and generation time. Click a row to expand the full question and answer text with inline audio players and per-stage timing breakdown (LLM ms, Piper question ms, Piper answer ms).

**Request Log** — Reverse-chronological table of all API requests (both device and dashboard). Shows timestamp, endpoint, source (device IP, dashboard, pool-worker), response time, and HTTP status. Distinguishes device requests from dashboard requests so you can see real device traffic. Auto-refreshes with the status poll.

#### Implementation Notes

- Single static HTML file, no dependencies, no build step
- Polls `/api/admin/status`, `/api/admin/queue`, and `/api/admin/log` every 5 seconds (configurable)
- Quiz Player calls the same `/api/quiz` endpoint the device uses — requests are visible in the log with source "dashboard"
- The Quiz Service should tag requests from the dashboard vs device (e.g. via User-Agent or a `?source=dashboard` parameter) so the log can distinguish them

### Configuration Page

Served at `http://<NAS_IP>:<PORT>/config`. Provides a form-based UI for all Quiz Service settings. Changes are saved to a local JSON file (`config.json` in the Quiz Service data directory) and take effect immediately — no service restart required.

#### Configuration API

**Get current config:**

```
GET /api/admin/config
```

**Update config:**

```
PUT /api/admin/config
Content-Type: application/json
```

Accepts a partial or full config object. Returns the merged result. The Quiz Service validates all fields before saving — invalid values return 400 with an error message.

#### Config Schema

```json
{
  "llm": {
    "provider": "claude",
    "model": "claude-sonnet-4-20250514",
    "api_base_url": "https://api.anthropic.com",
    "api_key_env": "ANTHROPIC_API_KEY",
    "temperature": 0.9,
    "max_tokens": 1024
  },
  "tts": {
    "piper_url": "http://localhost:10200",
    "voice_model": "en_US-lessac-medium",
    "sample_rate": 22050,
    "output_format": "wav"
  },
  "pool": {
    "target_size": 10,
    "min_ready": 3,
    "backfill_trigger": 5,
    "audio_ttl_minutes": 60
  },
  "quiz": {
    "categories": ["general", "science", "history", "geography", "entertainment", "sports"],
    "difficulty": "medium",
    "system_prompt": "You are a quiz master. Generate a trivia question and answer. The category is {{category}} and the difficulty level is {{difficulty}}. Return JSON with 'question' and 'answer' fields."
  },
  "device": {
    "idle_timeout_seconds": 300
  }
}
```

#### Config Field Reference

| Section | Field | Description | Default |
|---|---|---|---|
| `llm.provider` | LLM provider | `claude`, `openai`, `ollama`, or `custom` | `claude` |
| `llm.model` | Model identifier | Provider-specific model name | `claude-sonnet-4-20250514` |
| `llm.api_base_url` | API endpoint | Base URL for the LLM API | Provider default |
| `llm.api_key_env` | API key env var | Name of the environment variable holding the API key. Keys are never stored in `config.json` — only the env var name is stored. | `ANTHROPIC_API_KEY` |
| `llm.temperature` | Creativity | Higher = more varied questions | `0.9` |
| `llm.max_tokens` | Response limit | Max tokens for LLM response | `1024` |
| `tts.piper_url` | Piper TTS URL | URL of the Piper TTS instance | `http://localhost:10200` |
| `tts.voice_model` | Piper voice | Voice model for speech synthesis | `en_US-lessac-medium` |
| `tts.sample_rate` | Audio sample rate | Must match Piper output and I2S config | `22050` |
| `pool.target_size` | Pool target | Number of ready questions to maintain | `10` |
| `pool.min_ready` | Minimum ready | Warn on dashboard if pool drops below this | `3` |
| `pool.backfill_trigger` | Backfill at | Start generating when pool drops to this count | `5` |
| `pool.audio_ttl_minutes` | Audio TTL | Minutes before unused audio files are cleaned up | `60` |
| `quiz.categories` | Quiz categories | List of available categories. Device cycles through these via touchscreen. | (see default list) |
| `quiz.difficulty` | Difficulty level | `easy`, `medium`, or `hard`. Passed to the LLM prompt via `{{difficulty}}` placeholder. | `medium` |
| `quiz.system_prompt` | LLM prompt | System prompt template for generating Q&A pairs. Supports `{{category}}` and `{{difficulty}}` placeholders that are substituted at generation time. Editable for tuning question style, format, and tone. | (built-in default) |
| `device.idle_timeout_seconds` | Sleep timeout | Seconds of inactivity before device enters deep sleep | `300` |

#### API Key Security

API keys are **never stored in `config.json`**. The config stores only the name of the environment variable (e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). The Quiz Service reads the key from the environment at runtime. The config page shows whether the referenced env var is set (yes/no) but never displays the key value.

#### LLM Provider Details

| Provider | `provider` value | `api_base_url` default | `api_key_env` default | Notes |
|---|---|---|---|---|
| Anthropic Claude | `claude` | `https://api.anthropic.com` | `ANTHROPIC_API_KEY` | Uses Messages API |
| OpenAI / compatible | `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` | Chat Completions API. Also works with any OpenAI-compatible endpoint (e.g. local proxies). |
| Ollama | `ollama` | `http://localhost:11434` | (none required) | Local models, no API key needed. Good for offline/testing. |
| Custom | `custom` | (must be set) | (must be set) | Any endpoint that accepts OpenAI-compatible chat completions format. |

#### Config Page Layout

```
+-----------------------------------------------------------------------+
|  QuizMaster Configuration                            [Save] [Reset]   |
+-----------------------------------------------------------------------+
|                                                                        |
|  LLM PROVIDER                                                         |
|  Provider:    [claude ▼]                                               |
|  Model:       [claude-sonnet-4-20250514        ]                       |
|  API Base URL: [https://api.anthropic.com      ]                       |
|  API Key Env:  [ANTHROPIC_API_KEY              ]  Status: ✓ Set       |
|  Temperature:  [0.9    ]                                               |
|  Max Tokens:   [1024   ]                                               |
|                                                                        |
+-----------------------------------------------------------------------+
|                                                                        |
|  QUIZ CONTENT                                                          |
|  Difficulty:  ( ) Easy  (•) Medium  ( ) Hard                           |
|                                                                        |
|  Categories:                                                           |
|  [general] [science] [history] [geography] [entertainment] [sports]    |
|  [+ Add category]                                                      |
|  Click to remove. Changes flush the queue.                             |
|                                                                        |
|  System Prompt:                                                        |
|  +----------------------------------------------------------------+   |
|  | You are a quiz master. Generate a trivia question and answer.   |   |
|  | The category is {{category}} and the difficulty level is        |   |
|  | {{difficulty}}.                                                  |   |
|  | Return JSON with 'question' and 'answer' fields.                |   |
|  +----------------------------------------------------------------+   |
|  Available placeholders: {{category}}, {{difficulty}}                   |
|  [Test Prompt] — generates one question using current settings         |
|  [Reset to Default] — restores the built-in prompt                     |
|                                                                        |
+-----------------------------------------------------------------------+
|                                                                        |
|  TEXT-TO-SPEECH                                                        |
|  Piper URL:    [http://localhost:10200          ]  Status: ✓ Connected |
|  Voice Model:  [en_US-lessac-medium ▼]                                 |
|  Sample Rate:  [22050  ] Hz                                            |
|  [Test TTS] — speaks a sample sentence                                 |
|                                                                        |
+-----------------------------------------------------------------------+
|                                                                        |
|  QUESTION POOL                                                         |
|  Target Size:       [10  ]                                             |
|  Min Ready Warning: [3   ]                                             |
|  Backfill Trigger:  [5   ]                                             |
|  Audio TTL:         [60  ] minutes                                     |
|                                                                        |
+-----------------------------------------------------------------------+
|                                                                        |
|  DEVICE                                                                |
|  Idle Timeout: [300] seconds                                           |
|                                                                        |
+-----------------------------------------------------------------------+
```

**Test buttons**: "Test Prompt" calls `POST /api/admin/generate` with the current prompt, category, and difficulty settings and displays the generated Q&A inline. "Test TTS" sends a sample sentence to Piper and plays the audio in the browser. Both let you verify settings before saving. "Reset to Default" restores the built-in system prompt template.

**Save behaviour**: Save validates all fields, writes to `config.json`, and applies changes immediately. If quiz content settings change (categories, difficulty, system prompt), the queue is automatically flushed and refilled with questions matching the new settings. A confirmation banner shows what changed.

### Display Behaviour

- On startup: show splash screen or "Loading..." status
- After question received: display question text (word-wrapped), category in header
- After "Reveal Answer" touch: show answer text
- After "Category" touch: cycle category, display new category name, request next question
- Before deep sleep: show last answer or "Tap to play"
- On error: show brief error message (e.g. "No WiFi — retrying...", "Service unavailable")

## Components

| Component | Part | Notes |
|---|---|---|
| MCU | ESP32 DevKitV1 (ELEGOO) | ESP32-WROOM-32, Xtensa dual-core 240MHz, 520KB SRAM, WiFi + Bluetooth, CP2102 USB-serial, onboard 3.3V regulator |
| Amplifier | Adafruit MAX98357A I2S breakout | Class D, 1.8W @ 8Ω at 5V. Powered from 5V rail (MT3608 output) |
| Speaker | 8Ω 5W, 66mm diameter | Matched to amp; MAX98357A at 5V delivers up to 1.8W into 8Ω |
| Display | 4" ILI9488 TFT IPS (480×320) with XPT2046 resistive touch | SPI interface, 3.3V/5V, 14-pin header |
| Power | USB 5V (via DevKitV1 USB-C) | No battery — powered from USB during development |
| Battery monitor | 2× 100kΩ resistors (voltage divider) | Divides battery voltage (3.0–4.2V) to 1.5–2.1V for ADC1 on GPIO 35 |

## Pin Assignments

| ESP32 GPIO | Function | Direction | Connected To | Bus |
|---|---|---|---|---|
| 25 | I2S BCLK | Output | MAX98357A BCLK | I2S |
| 26 | I2S LRC (WSEL) | Output | MAX98357A LRC | I2S |
| 33 | I2S DIN (DOUT) | Output | MAX98357A DIN | I2S |
| 32 | Amp shutdown | Output | MAX98357A SD pin | — |
| 23 | SPI MOSI | Output | ILI9488 SDI + XPT2046 T_DIN | SPI (VSPI) |
| 18 | SPI SCK | Output | ILI9488 SCK + XPT2046 T_CLK | SPI (VSPI) |
| 19 | SPI MISO | Input | XPT2046 T_DO only | SPI (VSPI) |
| 15 | Display CS | Output | ILI9488 CS | — |
| 2 | Display DC/RS | Output | ILI9488 DC | — |
| 16 | Display RST | Output | ILI9488 RESET | — |
| 21 | Touch CS | Output | XPT2046 T_CS | — |
| 4 | Touch IRQ | Input | XPT2046 T_IRQ | — |
| 35 | Battery voltage ADC | Input | Voltage divider midpoint (100kΩ + 100kΩ from battery) | ADC1_CH7 |
| 3V3 | Power out | — | ILI9488 VCC, ILI9488 LED | — |
| GND | Ground | — | All components | — |
| 5V (VIN) | Power in | — | ESP32 VIN + MAX98357A VIN (from MT3608 via power switch) | — |

**GPIOs to avoid:** 0 (boot button), 1 (TX0/USB), 3 (RX0/USB), 6–11 (internal flash), 12 (MTDI boot strapping — pulling high prevents boot). GPIOs 34–39 are input-only with no internal pull-ups.

**Deep sleep wake:** GPIO 4 (touch IRQ) is an RTC GPIO (RTC_GPIO10) and can serve as an `ext0` wake source — a touch on the screen can wake the device from deep sleep.

## MAX98357A Wiring

| Amp Pin | Connected To | Notes |
|---|---|---|
| VIN | 5V rail | 5V from MT3608 boost converter (via power switch). Delivers ~1.8W into 8Ω at 5V vs ~0.5W at 3.3V. |
| GND | ESP32 GND | Common ground |
| BCLK | GPIO 25 | I2S bit clock |
| LRC | GPIO 26 | I2S word select (left/right clock) |
| DIN | GPIO 33 | I2S serial data |
| SD | GPIO 32 | Shutdown control. LOW = amp off, HIGH/float = amp on |
| GAIN | Float (NC) | 12dB gain. For 9dB: solder to GND. For 6dB: 100kΩ to GND. For 15dB: 100kΩ to VIN |
| SPK+ | Speaker + | 8Ω 5W speaker |
| SPK− | Speaker − | 8Ω 5W speaker |

The Adafruit breakout has a 1MΩ internal pull-up on SD, so the amp is enabled by default. Drive GPIO 32 LOW before entering deep sleep to cut amp quiescent current.

## ILI9488 Display + XPT2046 Touch Wiring

| Display Pin | Connected To | Notes |
|---|---|---|
| VCC | ESP32 3V3 | 3.3V supply (module has onboard regulator, accepts 3.3V or 5V) |
| GND | ESP32 GND | Common ground |
| CS | GPIO 15 | LCD chip select (active low) |
| RESET | GPIO 16 | LCD reset (active low) |
| DC/RS | GPIO 2 | Data/Command select. Note: GPIO 2 also drives the ESP32 onboard LED — it will flicker during SPI transactions (harmless) |
| SDI (MOSI) | GPIO 23 | SPI data in (shared with touch) |
| SCK | GPIO 18 | SPI clock (shared with touch) |
| LED | ESP32 3V3 | Backlight always on. Can connect to a GPIO for PWM brightness control. |
| SDO (MISO) | **DO NOT CONNECT** | ILI9488 SDO does not tristate when CS is high — it will interfere with the XPT2046 touch controller on the shared SPI bus. Leave disconnected. |
| T_CLK | GPIO 18 | Touch SPI clock (shared with display SCK) |
| T_CS | GPIO 21 | Touch chip select (active low) |
| T_DIN | GPIO 23 | Touch SPI data in (shared with display MOSI) |
| T_DO | GPIO 19 | Touch SPI data out — this is the ONLY device connected to MISO |
| T_IRQ | GPIO 4 | Touch interrupt (low when touch detected). RTC_GPIO10 — can wake from deep sleep. |

## Battery Voltage Monitoring

A resistive voltage divider allows the ESP32 to measure the Li-ion battery voltage via its ADC.

### Circuit

```
Battery B+ (3.0–4.2V)
    │
   [R1: 100kΩ]
    │
    ├──── GPIO 35 (ADC1_CH7)
    │
   [R2: 100kΩ]
    │
   GND
```

### Design Rationale

- **Voltage divider ratio**: 1:2 — `Vadc = Vbat × R2 / (R1 + R2) = Vbat / 2`
- **ADC range**: At 4.2V (full charge) the ADC sees 2.1V; at 3.0V (empty) it sees 1.5V — well within the ESP32 ADC's 0–3.3V range with 11dB attenuation
- **GPIO 35**: Input-only pin on ADC1 (channels on ADC1 work while WiFi is active; ADC2 channels do not). Currently unused.
- **Divider impedance**: 200kΩ total, drawing only ~21µA from the battery at full charge — negligible drain
- **Tap point**: Connect R1 to the battery B+ terminal (TP4056 B+ pad / battery positive), not after the boost converter — this reads the true cell voltage regardless of the MT3608 output
- **No extra capacitor needed**: The ESP32 ADC input has internal sample-and-hold; the 100kΩ source impedance is acceptable for the default 12-bit ADC at moderate sample rates

### Firmware Notes

- Use `analogReadMilliVolts(35)` (Arduino) or `adc1_get_raw(ADC1_CHANNEL_7)` (ESP-IDF) to read the ADC
- Multiply the reading by 2 to recover the actual battery voltage: `Vbat = Vadc × 2`
- For better accuracy, calibrate against a multimeter reading and apply a linear correction factor
- Sample periodically (e.g. every 30s) and display a battery icon/percentage on the TFT
- Typical Li-ion thresholds: 4.2V = 100%, 3.7V = ~50%, 3.3V = ~10%, 3.0V = empty (shut down)

### TFT_eSPI Library Configuration

The display uses the **TFT_eSPI** library by Bodmer. Create/edit `User_Setup.h` in the TFT_eSPI library folder:

```cpp
#define ILI9488_DRIVER

#define TFT_MISO  19
#define TFT_MOSI  23
#define TFT_SCLK  18
#define TFT_CS    15
#define TFT_DC     2
#define TFT_RST   16

#define TOUCH_CS  21

#define LOAD_GLCD
#define LOAD_FONT2
#define LOAD_FONT4
#define LOAD_FONT6
#define LOAD_FONT7
#define LOAD_FONT8
#define LOAD_GFXFF
#define SMOOTH_FONT

#define SPI_FREQUENCY       27000000   // 27 MHz — safe max for ILI9488
#define SPI_READ_FREQUENCY  16000000
#define SPI_TOUCH_FREQUENCY  2500000   // 2.5 MHz for XPT2046
```

**Important notes:**
- 27 MHz SPI is the reliable maximum for ILI9488. 40 MHz may cause visual artifacts. 80 MHz is too fast.
- ILI9488 over SPI uses 18-bit colour (not 16-bit like ILI9341), so DMA is not supported in TFT_eSPI and rendering is somewhat slower.
- Touch calibration is required after wiring — run the TFT_eSPI `Touch_calibrate` example sketch to get calibration values for your specific display and orientation.
- XPT2046 touch SPI must run at 2.5 MHz (max spec).

## Power Budget

| State | Current Draw | Notes |
|---|---|---|
| Deep sleep (total) | ~30–35µA | ESP32 ~10µA + voltage divider ~21µA (no display backlight in sleep) |
| Active idle (display on, WiFi connected) | ~120–180mA | ESP32 active + display backlight + WiFi |
| Active burst (audio playing) | ~300–450mA | WiFi + amp playing speech (~150–250mA at 5V into 8Ω) + display |

The device is USB-powered during development. Battery operation is not currently planned but could be added later — the ESP32 DevKitV1's onboard CP2102 and voltage regulator draw ~10–20mA even in deep sleep, making it unsuitable for ultra-low-power battery use without hardware modifications.

## I2S Configuration

```
Sample rate:    22050 Hz (match Piper TTS output config)
Bit depth:      16-bit
Channels:       Mono
Format:         I2S Philips standard
```

The sample rate must match what the Quiz Service / Piper produces. 22050 Hz is the Piper default for most voice models. The I2S driver sample rate should be set dynamically from the WAV header if possible.

The MAX98357A automatically sums stereo to mono if a stereo stream is sent, but configuring Piper and the I2S driver for mono halves the data rate.

## Software Architecture Notes

- **Quiz flow**: Device sends HTTP GET to Quiz Service → receives JSON with text + audio URLs → displays question text on TFT → streams question audio from URL via I2S → waits for touch → streams answer audio → prefetches next question JSON.
- **Audio pipeline**: Audio is streamed directly from the Quiz Service URLs via HTTP, not buffered into RAM. WAV headers are parsed to configure I2S sample rate dynamically. See `firmware/quiz_test/quiz_test.ino` for the working streaming implementation.
- **Deep sleep cycle**: After idle timeout, drive GPIO 32 LOW (amp off), turn off display backlight, then enter deep sleep with touch IRQ (GPIO 4) as wake source.
- **Display updates**: Write question/answer text to ILI9488 TFT via TFT_eSPI library. Touch input via XPT2046 replaces physical buttons.
- **WiFi strategy**: Full modem sleep in deep sleep. Cold connect on wake. Keep WiFi active during a quiz session to avoid reconnection overhead. Use `esp_wifi_set_ps(WIFI_PS_MIN_MODEM)` during active periods.
- **Quiz Service endpoint**: `http://<NAS_IP>:<PORT>/api/quiz?category=<CATEGORY>` — returns JSON with text and audio URLs. The Quiz Service internally manages a pre-generated question pool, the configured LLM API, and Piper TTS (default Piper Docker port 10200).

## Error Handling

The device operates on an unreliable wireless link and depends on external services. Error handling should be simple and user-visible.

| Scenario | Device Behaviour |
|---|---|
| WiFi connect fails | Display "No WiFi" on TFT. Retry 3 times with 2s backoff. If still failing, display "No WiFi — tap to retry" and wait for touch. |
| Quiz Service unreachable | Display "Service unavailable". Retry once. If still failing, show message and wait for touch. |
| Quiz Service returns error (5xx, empty pool) | Display "No questions available — try again shortly". Wait for touch. |
| Audio stream fails mid-playback | Stop playback. Question/answer text remains visible on TFT (user can still read it). No retry — user taps for next question. |
| Audio stream fails before playback starts | Display text normally (text is already available from JSON). Show "(audio unavailable)" on TFT. |
| Idle timeout during error state | Enter deep sleep normally. |

**Design principle**: Never hang silently. Always show status on the display so the user knows what's happening. Text is more resilient than audio — if the JSON was received, the question/answer text can always be displayed even if audio fails.

**Visual Design principles**: Use the front-end design skill to design any web user interface.
