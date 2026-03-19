# QuizMaster — Functional Design (Device UI/UX)

## Overview

This document specifies the user interface and experience for the QuizMaster physical device: an ESP32-based tabletop quiz game with a 4" ILI9488 TFT touchscreen (480x320, landscape) and speaker. All interaction is via resistive touchscreen — there are no physical buttons.

## Visual Design System

### Aesthetic Direction: "Quiz Night Noir"

Inspired by upscale pub quiz nights and vintage game show sets. Deep, dark backgrounds anchor the interface while warm gold accents evoke the drama of a quiz show spotlight. The overall feel is confident and inviting — sophisticated enough for adults, bold enough to feel like a game.

Key principles:
- **High contrast** — white text on dark backgrounds for readability on a small TFT
- **Solid colors only** — no gradients (ILI9488 SPI limitation), no transparency
- **Large touch targets** — minimum 60px height for resistive touchscreen reliability
- **Geometric clarity** — rounded rectangles, clean dividing lines, no decorative clutter
- **Gold as hero color** — used sparingly for headings, active elements, and the logo

### Color Palette

All colors specified as RGB hex. Use `tft.color565(r, g, b)` to convert for TFT_eSPI.

| Token | Hex | RGB | Usage |
|---|---|---|---|
| `BG_PRIMARY` | `#0C1021` | 12, 16, 33 | Screen background — deep blue-black |
| `BG_PANEL` | `#161B30` | 22, 27, 48 | Card/panel backgrounds, header bar |
| `BG_BUTTON` | `#1E2545` | 30, 37, 69 | Default button fill |
| `GOLD` | `#FFB800` | 255, 184, 0 | Logo, headings, primary accent |
| `GOLD_DIM` | `#8A6400` | 138, 100, 0 | Inactive/disabled gold elements |
| `CYAN` | `#00D4AA` | 0, 212, 170 | Category badges, informational highlights |
| `TEXT_PRIMARY` | `#F0F0F0` | 240, 240, 240 | Body text, question/answer content |
| `TEXT_SECONDARY` | `#707A90` | 112, 122, 144 | Labels, secondary info |
| `BTN_PRIMARY` | `#FFB800` | 255, 184, 0 | Primary action button fill |
| `BTN_PRIMARY_TEXT` | `#0C1021` | 12, 16, 33 | Text on primary buttons (dark on gold) |
| `GREEN` | `#00E676` | 0, 230, 118 | Answer reveal flash, success states |
| `RED` | `#FF3D57` | 255, 61, 87 | Error messages, connection failures |
| `AUDIO_PULSE` | `#00AAFF` | 0, 170, 255 | Audio playback indicator |

### Typography

Using TFT_eSPI built-in fonts (loaded via `LOAD_FONT2`, `LOAD_FONT4`, `LOAD_GFXFF`):

| Role | Font | Size | Color | Usage |
|---|---|---|---|---|
| Logo | FreeSansBold24pt | 24pt | `GOLD` | Splash screen title |
| Screen Title | Font 4 (26px) | 26px | `GOLD` | Section headings |
| Question Text | FreeSans18pt | 18pt | `TEXT_PRIMARY` | Question and answer body |
| Button Label | FreeSansBold12pt | 12pt | varies | Button text |
| Category Badge | Font 2 (16px) | 16px | `BG_PRIMARY` on `CYAN` | Category indicator |
| Score/Count | Font 7 (48px, 7-seg) | 48px | `GOLD` | Score display on main screen |
| Status Text | Font 2 (16px) | 16px | `TEXT_SECONDARY` | WiFi status, errors |

**Note:** Exact font choices will be refined during implementation based on what renders well at 480x320. Free fonts (via `LOAD_GFXFF`) give the best results for larger text. Fall back to built-in Font 4 if memory is tight.

### Layout Grid

The 480x320 display is divided into three persistent zones:

```
+----------------------------------------------+
|  HEADER BAR (40px)                            |
+----------------------------------------------+
|                                               |
|  CONTENT AREA (200px)                         |
|                                               |
+----------------------------------------------+
|  ACTION BAR (80px)                            |
+----------------------------------------------+
```

- **Header bar** (y: 0–39): Category badge, question counter, status icons. Background: `BG_PANEL`.
- **Content area** (y: 40–239): Question/answer text, logo, messages. Background: `BG_PRIMARY`.
- **Action bar** (y: 240–319): Touch buttons. Buttons are large (minimum 60px tall) for reliable resistive touch input.

Horizontal padding: 12px on each side (usable width: 456px).

### UI Components

#### Primary Button
Full-width gold button for the main action on each screen.

```
+----------------------------------------------+
|              REVEAL ANSWER                    |  60px tall
+----------------------------------------------+
```
- Fill: `BTN_PRIMARY` (gold)
- Text: `BTN_PRIMARY_TEXT` (dark), centered, FreeSansBold12pt
- Corner radius: 8px (`fillRoundRect`)
- Position: centered in action bar with 12px horizontal margin
- Touch target: entire action bar width (generous hit zone)

#### Secondary Button
Smaller button for non-primary actions (category change, settings).

```
+-----------+
| CATEGORY  |  50px tall, variable width
+-----------+
```
- Fill: `BG_BUTTON`
- Border: 2px `GOLD_DIM`
- Text: `TEXT_PRIMARY`, centered
- Corner radius: 6px

#### Category Badge
Compact colored tag showing the current quiz category.

```
 [ SCIENCE ]
```
- Fill: `CYAN`
- Text: `BG_PRIMARY` (dark on teal), Font 2, uppercase
- Corner radius: 4px
- Padding: 6px horizontal, 2px vertical
- Position: left side of header bar

#### Audio Indicator
Animated dot or simple bar visualization shown during audio playback.

```
 )) Playing...
```
- Three small arcs or bars in `AUDIO_PULSE` color
- Toggles visibility every 500ms to create a pulse effect (simple timer, no complex animation)
- Position: right side of header bar during playback, hidden otherwise

#### Status Icons
Small indicators in the header bar for WiFi and battery.

- WiFi: simple antenna icon (3 arcs) drawn with `drawLine` — `GREEN` when connected, `RED` when disconnected
- Battery voltage: bare numeric readout in Font 2 (16px), `TEXT_SECONDARY`, right-aligned in header — e.g., "3.8V". Deliberately understated — no icon, no percentage, no color coding. Just the voltage. Updates every 30 seconds via `analogReadMilliVolts(35) * 2`. Displayed to one decimal place. Reads "---" if ADC returns an implausible value (<2.5V or >4.5V, indicating no battery connected).

---

## Screen Specifications

### 1. Splash Screen

Shown on power-on. Establishes brand identity and plays the welcome audio.

**Duration:** Displays for the full length of the "Welcome to Quiz Master" audio clip (~2–3 seconds), then auto-transitions to Main Screen.

**Layout:**

```
+----------------------------------------------+
|                                               |
|                                               |
|                                               |
|           ◆  Q U I Z M A S T E R             |
|                                               |
|              ─────────────────                |
|                                               |
|                                               |
|                                               |
+----------------------------------------------+
```

**Specification:**
- Background: `BG_PRIMARY` (full screen, no header/action bars)
- Logo text: "QUIZMASTER" in FreeSansBold24pt, `GOLD`, centered horizontally and vertically
- Diamond glyph (◆) rendered as a small filled rotated square (8x8px) to the left of the text, also `GOLD`
- Decorative line: horizontal line below the text, 200px wide, 2px thick, `GOLD_DIM`, centered
- No touch interaction — this screen is non-interactive

**Sequence:**
1. Screen fills with `BG_PRIMARY`
2. Logo text draws immediately (no animation — keep it simple on embedded)
3. Audio plays: "Welcome to Quiz Master" (TTS from server, pre-cached or generated on first boot)
4. After audio completes → transition to Main Screen
5. If audio fails (no WiFi yet), hold splash for 2 seconds then proceed

**Transition out:** Quick wipe — fill screen top-to-bottom with `BG_PRIMARY` (8 horizontal bands, 40px each, drawn sequentially with ~30ms delay between each — creates a fast "dissolve down" effect).

---

### 2. Main Screen

The home/idle screen. Invites the user to start playing. This is shown after the splash, after returning from deep sleep, and as the default resting state.

**Layout:**

```
+----------------------------------------------+
| [ GENERAL ]         ? 0    )))  WiFi    3.8V |  HEADER
+----------------------------------------------+
|                                               |
|                                               |
|            Q U I Z M A S T E R               |
|                  ready                        |
|                                               |
|                                               |
+----------------------------------------------+
|         [    ▶  NEW QUESTION    ]             |  ACTION
+----------------------------------------------+
```

**Specification:**

Header bar:
- Left: Category badge showing current category (e.g., "GENERAL"). Tappable — touch cycles to next category.
- Center-right: Question count — "? 0" in `TEXT_SECONDARY` (number of questions answered this session), using Font 4
- Right: WiFi status icon + audio indicator (when playing)

Content area:
- "QUIZMASTER" in FreeSansBold18pt, `GOLD`, centered
- Below: "ready" in Font 2, `TEXT_SECONDARY`, centered
- If WiFi is not connected, instead show "connecting..." in `GOLD_DIM`, then update to "ready" once connected

Action bar:
- Single primary button: "NEW QUESTION" with a ▶ play symbol
- Full width (456px), 60px tall, gold fill, dark text

**Touch targets:**
- Category badge area (left 1/3 of header): cycles category
- Action bar (full width): fetches and starts a new question

**WiFi connection:** Happens automatically after splash. If already connected (warm wake from sleep), "ready" shows immediately. If connecting, show "connecting..." and swap to "ready" once WiFi is up. The "NEW QUESTION" button is always tappable — if WiFi isn't ready when pressed, show a brief "Connecting..." state before fetching.

---

### 3. Question Screen

Displayed after fetching a question. Shows the question text and plays question audio through the speaker.

**Layout:**

```
+----------------------------------------------+
| [ SCIENCE ]     ? 3  ))) Playing  WiFi  3.8V |  HEADER
+----------------------------------------------+
|                                               |
|  In which year did the first successful       |
|  human-to-human heart transplant take         |
|  place?                                       |
|                                               |
|                                               |
|                                               |
+----------------------------------------------+
|         [    REVEAL ANSWER    ]               |  ACTION
+----------------------------------------------+
```

**Specification:**

Header bar:
- Left: Category badge (current category, still tappable to change)
- Center-right: Question count (incremented — e.g., "? 3")
- Right: Audio indicator — animated pulse while question audio plays, disappears when audio finishes

Content area:
- Question text in FreeSans18pt (or Font 4 if free fonts aren't available), `TEXT_PRIMARY`
- Left-aligned, word-wrapped within 12px margins
- Top padding: 16px from header bar
- If text is too long for the content area (~6 lines max at 18pt), reduce font to FreeSans12pt and re-render. Truncation is a last resort — the quiz service prompt should constrain question length.

Action bar:
- Single primary button: "REVEAL ANSWER"
- Gold fill, dark text, full width

**Behavior:**
1. Screen draws immediately with question text
2. Question audio begins streaming via I2S simultaneously
3. Audio indicator pulses in header during playback
4. User can tap "REVEAL ANSWER" at any time — they don't have to wait for audio to finish
5. If audio is still playing when user taps reveal, audio stops and answer audio begins

**Touch targets:**
- Category badge area: cycles category (takes effect on the *next* question)
- Action bar: reveals the answer

---

### 4. Answer Screen

Shows the answer after the user taps "REVEAL ANSWER". Plays answer audio. Offers to continue to the next question.

**Layout:**

```
+----------------------------------------------+
| [ SCIENCE ]     ? 3  ))) Playing  WiFi  3.8V |  HEADER
+----------------------------------------------+
|                                               |
|  In which year did the first successful       |
|  human-to-human heart transplant take         |
|  place?                                       |
|  ──────────────────────────────────           |
|  1967 — Dr. Christiaan Barnard               |
|  performed it in Cape Town, South Africa.     |
|                                               |
+----------------------------------------------+
|  [ CATEGORY ]     [  ▶  NEXT QUESTION  ]     |  ACTION
+----------------------------------------------+
```

**Specification:**

Header bar:
- Same as Question Screen
- Audio indicator shows during answer audio playback

Content area:
- Question text remains visible at top, but rendered in `TEXT_SECONDARY` (dimmed) and reduced to Font 2 (16px) to make room
- Horizontal divider line: 2px, `GOLD`, full content width, separating question from answer
- Answer text below divider in FreeSans18pt, `GREEN` (bright green for the "reveal" moment)
- Answer text left-aligned, word-wrapped
- If combined question + answer text overflows, the question text is hidden entirely and only the answer is shown (with a small "Q: ..." truncated reference at the top)

Action bar — split into two buttons:
- Left (1/3 width): Secondary button — "CATEGORY" (cycles category for next question)
- Right (2/3 width): Primary button — "NEXT QUESTION" with ▶ symbol, gold fill

**Behavior:**
1. **Reveal transition:** Content area redraws with a brief "flash" effect — fill the content area with `GOLD` for ~80ms, then draw the answer layout. This creates a satisfying game-show reveal moment.
2. Answer audio begins playing immediately after the flash
3. Background prefetch of the next question starts (HTTP GET to quiz service)
4. User reads the answer and taps "NEXT QUESTION" when ready
5. If prefetch is complete, next question appears instantly. If not, show brief "Loading..." text in content area.

**Touch targets:**
- Left 1/3 of action bar: category cycle
- Right 2/3 of action bar: next question

---

### 5. Loading State

Shown briefly if a question is not yet available (prefetch incomplete, first question of session, or service slow).

**Layout:**

```
+----------------------------------------------+
| [ GENERAL ]          ? 0         WiFi  3.8V  |  HEADER
+----------------------------------------------+
|                                               |
|                                               |
|               Loading...                      |
|                ●                              |
|                                               |
|                                               |
+----------------------------------------------+
|                                               |  ACTION (empty)
+----------------------------------------------+
```

**Specification:**
- "Loading..." in Font 4, `TEXT_SECONDARY`, centered
- Below: a single dot that cycles through three positions (left, center, right) every 300ms — simple animation using `fillCircle` and `fillRect` to erase. Three dots at fixed positions, one filled at a time.
- No touch interaction during loading
- Timeout: if loading exceeds 10 seconds, transition to error state

This state should be rare — the prefetch strategy means questions are usually ready before the user taps.

---

### 6. Category Selection

Category is changed by tapping the category badge in the header. This does **not** open a separate screen — instead, it cycles inline.

**Behavior:**
1. User taps the category badge (left 1/3 of header bar)
2. Category advances to the next in the configured list: General → Science → History → Geography → Entertainment → Sports → All → General → ...
3. The badge redraws immediately with the new category name and a brief color flash (`GOLD` fill for ~150ms, then back to `CYAN`)
4. On the Main Screen or Answer Screen: the next question fetched will use the new category
5. On the Question Screen: category change is noted but doesn't interrupt the current question — takes effect on next fetch
6. "All" category sends no category parameter to the API (server picks randomly)

**Visual feedback:**
- Badge background flashes `GOLD` briefly on tap, then returns to `CYAN`
- If the category name is longer than the badge width, truncate with "..." (e.g., "ENTERTAINM...")

---

### 7. Error States

Errors are shown in the content area with a clear message and recovery action. The header bar remains visible. Errors never hang silently.

#### WiFi Connection Failed

```
+----------------------------------------------+
| [ GENERAL ]                  ✕ WiFi    3.8V |  HEADER
+----------------------------------------------+
|                                               |
|              ✕  No WiFi                       |
|                                               |
|     Could not connect to network.             |
|     Check that WiFi is available.             |
|                                               |
+----------------------------------------------+
|         [      TAP TO RETRY      ]            |  ACTION
+----------------------------------------------+
```

- WiFi icon in header: `RED`
- Error icon (✕) and "No WiFi" heading: `RED`, Font 4
- Detail text: `TEXT_SECONDARY`, Font 2
- Action button: "TAP TO RETRY" — secondary style (not gold, uses `BG_BUTTON` with `RED` border)
- On tap: retries WiFi connection. If successful, transitions to Main Screen.

#### Service Unavailable

```
+----------------------------------------------+
| [ SCIENCE ]                  WiFi      3.8V  |  HEADER
+----------------------------------------------+
|                                               |
|          ✕  Service Unavailable               |
|                                               |
|     Quiz service is not responding.           |
|     It may be starting up.                    |
|                                               |
+----------------------------------------------+
|         [      TAP TO RETRY      ]            |  ACTION
+----------------------------------------------+
```

- Same layout pattern as WiFi error
- "Service Unavailable" in `RED`
- Retry button attempts to fetch a question again

#### No Questions Available (Empty Pool)

```
+----------------------------------------------+
| [ SCIENCE ]                  WiFi      3.8V  |  HEADER
+----------------------------------------------+
|                                               |
|          ⏳  No Questions Ready               |
|                                               |
|     The quiz service is generating            |
|     questions. Try again shortly.             |
|                                               |
+----------------------------------------------+
|         [      TAP TO RETRY      ]            |  ACTION
+----------------------------------------------+
```

- Hourglass and heading in `GOLD` (not red — this is a transient state, not a failure)
- User retries manually

#### Audio Unavailable

Not a separate screen. If audio fails but the question/answer JSON was received:
- Show "(audio unavailable)" in `TEXT_SECONDARY`, Font 2, below the question/answer text
- The question/answer text is always displayed — audio is supplementary
- No retry for audio — user proceeds normally by reading the text

---

### 8. Sleep and Wake

#### Entering Deep Sleep

After `idle_timeout_seconds` (default: 300s / 5 minutes) of no touch input:

1. Display dims: fill screen with `BG_PRIMARY` (instant clear)
2. Brief "Sleeping..." text in `TEXT_SECONDARY`, centered, for 500ms
3. Drive amp shutdown pin (GPIO 32) LOW
4. Enter ESP32 deep sleep with touch IRQ (GPIO 4) as `ext0` wake source

No dramatic animation — the user isn't watching. Just clean shutdown.

#### Waking from Deep Sleep

A touch on the screen triggers wake via GPIO 4 (touch IRQ):

1. ESP32 wakes from deep sleep
2. Display initializes (TFT_eSPI init, set rotation)
3. Splash screen plays (same as power-on boot)
4. WiFi reconnects during/after splash
5. Main Screen appears
6. Session question count resets to 0

The wake flow is identical to a cold boot from the user's perspective.

---

## Transitions

Screen transitions on an embedded device must be fast and simple. All transitions are implemented with basic TFT_eSPI draw calls.

| From | To | Transition |
|---|---|---|
| Splash → Main | Band wipe down | 8 horizontal bands fill top-to-bottom, 30ms apart |
| Main → Question | Instant redraw | Clear content + action areas and redraw (fast, no animation) |
| Question → Answer | Gold flash reveal | Content area fills `GOLD` for 80ms, then redraws with answer |
| Answer → Question | Instant redraw | Clear and redraw (prefetched question appears immediately) |
| Any → Error | Instant redraw | Clear content + action and show error |
| Error → Main/Question | Instant redraw | On successful retry |
| Any → Sleep | Fade to black | Fill screen with `BG_PRIMARY` |

**Why minimal transitions:** The ILI9488 over SPI at 27 MHz is relatively slow for full-screen redraws (~100ms for a full 480x320 fill). Complex animations would look choppy. The gold flash on answer reveal is the one deliberate "moment" — everything else prioritizes speed and responsiveness.

---

## Touch Interaction Design

### Touch Zones

The screen is divided into touch zones by screen state:

**Main Screen:**
```
+--------------------+-------------------------+
|   CATEGORY ZONE    |     (no action)         |  0–39px (header)
|   taps = cycle     |                         |
+--------------------+-------------------------+
|                                               |
|              (no action)                      |  40–239px (content)
|                                               |
+----------------------------------------------+
|           NEW QUESTION ZONE                   |  240–319px (action)
|           taps = fetch question               |
+----------------------------------------------+
```

**Question Screen:**
```
+--------------------+-------------------------+
|   CATEGORY ZONE    |     (no action)         |  0–39px
+--------------------+-------------------------+
|                                               |
|              (no action)                      |  40–239px
|                                               |
+----------------------------------------------+
|           REVEAL ANSWER ZONE                  |  240–319px
+----------------------------------------------+
```

**Answer Screen:**
```
+--------------------+-------------------------+
|   CATEGORY ZONE    |     (no action)         |  0–39px
+--------------------+-------------------------+
|                                               |
|              (no action)                      |  40–239px
|                                               |
+--------------+-------------------------------+
| CATEGORY     |       NEXT QUESTION ZONE      |  240–319px
| ZONE (alt)   |                               |
+--------------+-------------------------------+
```

### Touch Handling

- **Debounce:** 300ms minimum between accepted touches (resistive touchscreens are noisy)
- **Touch detection:** Use `tft.getTouch(&x, &y)` with calibration data `{ 300, 3600, 300, 3600, 3 }`
- **Y-axis correction:** Apply `y = tft.height() - 1 - y` after reading (Y is inverted with rotation 1)
- **Touch feedback:** On any valid touch, briefly invert the tapped button colors (swap fill and text colors) for ~100ms, then execute the action. This gives immediate tactile confirmation.
- **Idle timer reset:** Every valid touch resets the deep sleep idle timer

### Accessibility Considerations

- All text content is also spoken via audio — the device is usable by visually impaired users (though touch navigation is basic)
- High contrast ratios: gold on dark exceeds 7:1, white on dark exceeds 15:1
- Large button sizes (60–80px tall) accommodate imprecise touch input
- No time-limited interactions — the user is never rushed (no countdown timers)

---

## Audio-Visual Synchronization

### Question Flow
1. Screen draws question text **immediately** — do not wait for audio
2. Audio streaming begins in parallel with the screen draw
3. Audio indicator appears in header once audio data starts flowing
4. If audio finishes before user taps "Reveal Answer," indicator disappears — screen remains static
5. User reads and/or listens, then taps at their own pace

### Answer Flow
1. User taps "Reveal Answer"
2. If question audio is still playing, stop it immediately
3. Gold flash (80ms)
4. Screen redraws with answer text
5. Answer audio begins streaming
6. Prefetch of next question JSON starts in background (non-blocking)

### Audio Indicator States
| State | Indicator |
|---|---|
| No audio playing | Hidden (no indicator in header) |
| Audio streaming/playing | Pulsing arcs in `AUDIO_PULSE`, toggling every 500ms |
| Audio finished | Hidden |
| Audio error | "(audio unavailable)" shown below text content |

---

## Screen Pixel Specifications

Exact coordinates for implementation reference. Origin (0,0) is top-left. Display is 480x320 in landscape (rotation 1).

### Header Bar
| Element | X | Y | W | H | Notes |
|---|---|---|---|---|---|
| Header background | 0 | 0 | 480 | 40 | `BG_PANEL` fill |
| Category badge | 12 | 8 | auto | 24 | `CYAN` fill, 4px radius, 6px h-padding |
| Question count | 340 | 10 | auto | 20 | Right-aligned, Font 2, `TEXT_SECONDARY` |
| WiFi icon | 430 | 10 | 20 | 20 | Simple drawn icon |
| Battery voltage | 454 | 12 | auto | 16 | Font 2, `TEXT_SECONDARY`, e.g., "3.8V" |
| Audio indicator | 390 | 10 | 30 | 20 | Three arcs/bars |

### Content Area
| Element | X | Y | W | H | Notes |
|---|---|---|---|---|---|
| Content background | 0 | 40 | 480 | 200 | `BG_PRIMARY` fill |
| Text area | 12 | 56 | 456 | 168 | Word-wrapped text region |
| Divider line (answer) | 12 | varies | 456 | 2 | `GOLD`, between question and answer |

### Action Bar
| Element | X | Y | W | H | Notes |
|---|---|---|---|---|---|
| Action background | 0 | 240 | 480 | 80 | `BG_PRIMARY` fill |
| Primary button | 12 | 250 | 456 | 60 | `BTN_PRIMARY` fill, 8px radius |
| Split: secondary btn | 12 | 250 | 145 | 60 | `BG_BUTTON` fill, `GOLD_DIM` 2px border |
| Split: primary btn | 169 | 250 | 299 | 60 | `BTN_PRIMARY` fill |

---

## Session State

The device tracks minimal state during a quiz session:

| Variable | Type | Default | Description |
|---|---|---|---|
| `current_category` | string | "general" | Currently selected category |
| `questions_answered` | int | 0 | Count of questions seen this session (resets on wake) |
| `current_question` | QuizQuestion | null | The currently displayed question (JSON from API) |
| `prefetched_question` | QuizQuestion | null | The next question, fetched in background |
| `screen_state` | enum | SPLASH | Current screen: SPLASH, MAIN, QUESTION, ANSWER, LOADING, ERROR |
| `audio_playing` | bool | false | Whether audio is currently streaming |
| `last_touch_ms` | uint32 | 0 | Timestamp of last touch (for idle timeout) |
| `wifi_connected` | bool | false | WiFi connection status |

---

## Complete User Flow

```
                    POWER ON
                       │
                       ▼
                 ┌───────────┐
                 │  SPLASH   │  Logo + "Welcome to Quiz Master" audio
                 │  (2-3s)   │
                 └─────┬─────┘
                       │  band wipe transition
                       ▼
              ┌──────────────────┐
     ┌───────│   MAIN SCREEN    │◄──────────────────┐
     │       │  "NEW QUESTION"  │                    │
     │       └────────┬─────────┘                    │
     │                │  tap NEW QUESTION             │
     │                ▼                               │
     │       ┌──────────────────┐                    │
     │       │    LOADING...    │  (if no prefetch)  │
     │       │    (0-10s)       │                    │
     │       └────────┬─────────┘                    │
     │                │  question received            │
     │                ▼                               │
     │       ┌──────────────────┐                    │
     │       │ QUESTION SCREEN  │◄────────┐          │
     │       │  text + audio    │         │          │
     │       └────────┬─────────┘         │          │
     │                │  tap REVEAL        │          │
     │                │  gold flash        │          │
     │                ▼                    │          │
     │       ┌──────────────────┐         │          │
     │       │  ANSWER SCREEN   │         │          │
     │       │  text + audio    │         │          │
     │       │  (prefetch next) │         │          │
     │       └───┬─────────┬────┘         │          │
     │           │         │               │          │
     │      tap NEXT   tap CATEGORY        │          │
     │           │         │               │          │
     │           │         └── cycle ───────┘          │
     │           │             (next Q uses            │
     │           │              new category)          │
     │           └── if prefetched: ─── QUESTION ─────┘
     │              if not: ─── LOADING ──────────────┘
     │
     │  idle timeout (300s no touch)
     │
     ▼
┌───────────┐
│   SLEEP   │  amp off, display off, deep sleep
│           │  touch IRQ wake → POWER ON flow
└───────────┘
```

**Error paths** (not shown above): Any network/service error during LOADING or prefetch transitions to the appropriate ERROR screen. User taps "RETRY" to attempt recovery, which loops back to the triggering action.
