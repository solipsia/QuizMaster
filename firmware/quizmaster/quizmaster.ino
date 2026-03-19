// QuizMaster — Main Device Firmware
// ESP32 DevKitV1 + ILI9488 480x320 + XPT2046 Touch + MAX98357A I2S Audio
//
// See FunctionalDesign.md for full UI/UX specification.
// See TechnicalDesign.md for hardware and architecture details.
//
// Requires TFT_eSPI User_Setup.h configured per TechnicalDesign.md:
//   ILI9488_DRIVER, TFT_MISO=19, TFT_MOSI=23, TFT_SCLK=18,
//   TFT_CS=15, TFT_DC=2, TFT_RST=16, TOUCH_CS=21,
//   SPI_FREQUENCY=27000000, SPI_TOUCH_FREQUENCY=2500000,
//   LOAD_GLCD, LOAD_FONT2, LOAD_FONT4, LOAD_GFXFF, SMOOTH_FONT

#include <SPI.h>
#include <TFT_eSPI.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "driver/i2s_std.h"
#include "esp_sleep.h"
#include "logo_bitmap.h"

// ═══════════════════════════════════════════════════════════════════════════
// Configuration
// ═══════════════════════════════════════════════════════════════════════════

static const char* WIFI_SSID     = "Solipsia";
static const char* WIFI_PASSWORD = "313920Airport";
static const char* SERVICE_BASE  = "http://synology.local:8080";

static const uint32_t IDLE_TIMEOUT_MS       = 300000;  // 5 min → deep sleep
static const uint32_t TOUCH_DEBOUNCE_MS     = 300;
static const uint32_t BATTERY_INTERVAL_MS   = 30000;
static const uint32_t WIFI_TIMEOUT_MS       = 10000;
static const uint32_t FETCH_TIMEOUT_MS      = 10000;
static const uint32_t INDICATOR_TOGGLE_MS   = 500;
static const uint32_t SPLASH_HOLD_MS        = 2500;

// ═══════════════════════════════════════════════════════════════════════════
// Pin Assignments (ESP32 DevKitV1 — raw GPIO numbers)
// ═══════════════════════════════════════════════════════════════════════════

#define PIN_BCLK      ((gpio_num_t)25)
#define PIN_LRC       ((gpio_num_t)26)
#define PIN_DIN       ((gpio_num_t)33)
#define PIN_AMP_SD    32
#define PIN_TOUCH_IRQ 4
#define PIN_BATTERY   35

// ═══════════════════════════════════════════════════════════════════════════
// Color Palette (RGB565)  —  "Quiz Night Noir" theme
// ═══════════════════════════════════════════════════════════════════════════

#define RGB565(r, g, b) (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))

static const uint16_t COL_BG         = RGB565(12, 16, 33);     // #0C1021
static const uint16_t COL_PANEL      = RGB565(22, 27, 48);     // #161B30
static const uint16_t COL_BTN_BG     = RGB565(30, 37, 69);     // #1E2545
static const uint16_t COL_GOLD       = RGB565(255, 184, 0);    // #FFB800
static const uint16_t COL_GOLD_DIM   = RGB565(138, 100, 0);    // #8A6400
static const uint16_t COL_CYAN       = RGB565(0, 212, 170);    // #00D4AA
static const uint16_t COL_TEXT       = RGB565(240, 240, 240);   // #F0F0F0
static const uint16_t COL_TEXT_DIM   = RGB565(112, 122, 144);   // #707A90
static const uint16_t COL_GREEN      = RGB565(0, 230, 118);    // #00E676
static const uint16_t COL_RED        = RGB565(255, 61, 87);    // #FF3D57
static const uint16_t COL_AUDIO      = RGB565(0, 170, 255);    // #00AAFF
static const uint16_t COL_LOGO_RED   = RGB565(255, 0, 0);      // #FF0000

// ═══════════════════════════════════════════════════════════════════════════
// Layout Constants (480 x 320 landscape)
// ═══════════════════════════════════════════════════════════════════════════

static const int SCR_W = 480, SCR_H = 320;
static const int HDR_H = 40;                          // header bar height
static const int CTN_Y = 40, CTN_H = 200;             // content area
static const int ACT_Y = 240, ACT_H = 80;             // action bar
static const int PAD   = 12;                           // horizontal padding
static const int USE_W = SCR_W - 2 * PAD;             // 456 usable width
static const int BTN_Y = 250, BTN_H = 60, BTN_R = 8; // button geometry

// Answer-screen split: CATEGORY (left) + NEXT QUESTION (middle) + REPLAY (right)
static const int SPLIT_W   = 145;                     // secondary button width
static const int SPLIT_GAP = 12;
static const int SPLIT_R_X = PAD + SPLIT_W + SPLIT_GAP;

// Replay button
static const int REPLAY_W   = 50;
static const int REPLAY_GAP = 8;
static const int REPLAY_X   = PAD + USE_W - REPLAY_W; // 418

// ═══════════════════════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════════════════════

enum Screen { S_SPLASH, S_MAIN, S_LOADING, S_QUESTION, S_ANSWER, S_ERROR };
enum Error  { E_NONE, E_WIFI, E_SERVICE, E_EMPTY };

struct QuizQ {
    String id, category, q_text, a_text, q_audio, a_audio;
    bool valid = false;
};

// Audio command: URL to stream
#define AUDIO_URL_MAX 256
struct AudioCmd { char url[AUDIO_URL_MAX]; };

// ═══════════════════════════════════════════════════════════════════════════
// Categories (dynamic, fetched from service)
// ═══════════════════════════════════════════════════════════════════════════

#define MAX_CATS 12
static char  cat_names[MAX_CATS][24];
static bool  cat_enabled[MAX_CATS];
static int   num_cats = 0;

// Count enabled categories
static int count_enabled_cats() {
    int n = 0;
    for (int i = 0; i < num_cats; i++) if (cat_enabled[i]) n++;
    return n;
}

// ═══════════════════════════════════════════════════════════════════════════
// Global State
// ═══════════════════════════════════════════════════════════════════════════

static TFT_eSPI tft = TFT_eSPI();
static uint16_t calData[5] = { 300, 3600, 300, 3600, 3 };

// Screen / UI state
static Screen   cur_screen   = S_SPLASH;
static Error    cur_error    = E_NONE;
static int      err_http     = 0;        // HTTP code from last failed fetch
static char     err_cat[24]  = "";       // category requested when error occurred
static int      q_count      = 0;       // questions answered this session
static bool     wifi_up      = false;
static bool     prev_wifi_up = false;

// Current + prefetched questions
static QuizQ    cur_q, pre_q;
static bool     pre_started = false, pre_done = false;

// Touch
static uint32_t last_touch = 0;

// Battery
static float    bat_v = -1.0f;
static uint32_t last_bat = 0;

// Audio (I2S + FreeRTOS task)
static i2s_chan_handle_t tx_handle      = NULL;
#define AUDIO_PRE_SIZE (64 * 1024)              // 64 KB pre-buffer (~1.45s at 22050 Hz mono)
static uint8_t*          audio_pre     = NULL;  // pre-allocated once in setup()
static QueueHandle_t     audio_q        = NULL;
static TaskHandle_t      audio_th       = NULL;
static volatile bool     audio_playing  = false;
static volatile bool     audio_stop     = false;

// Audio indicator animation
static bool     ind_vis   = false;
static uint32_t ind_last  = 0;

// Loading animation
static int      load_dot   = 0;
static uint32_t load_last  = 0;

// ═══════════════════════════════════════════════════════════════════════════
//  AUDIO SYSTEM  — runs on core 0
// ═══════════════════════════════════════════════════════════════════════════

static void i2s_setup(uint32_t rate, uint8_t ch, uint8_t bits) {
    if (tx_handle) { i2s_channel_disable(tx_handle); i2s_del_channel(tx_handle); tx_handle = NULL; }

    i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_AUTO, I2S_ROLE_MASTER);
    cc.dma_desc_num  = 12;
    cc.dma_frame_num = 1024;
    cc.auto_clear    = true;
    i2s_new_channel(&cc, &tx_handle, NULL);

    i2s_std_config_t sc = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(rate),
        .slot_cfg = I2S_STD_MSB_SLOT_DEFAULT_CONFIG(
                        I2S_DATA_BIT_WIDTH_16BIT,
                        ch == 1 ? I2S_SLOT_MODE_MONO : I2S_SLOT_MODE_STEREO),
        .gpio_cfg = { .mclk = I2S_GPIO_UNUSED, .bclk = PIN_BCLK, .ws = PIN_LRC,
                       .dout = PIN_DIN, .din = I2S_GPIO_UNUSED,
                       .invert_flags = { false, false, false } },
    };
    i2s_channel_init_std_mode(tx_handle, &sc);
    i2s_channel_enable(tx_handle);
}

static void atten6dB(uint8_t* b, size_t len) {
    int16_t* s = (int16_t*)b;
    for (size_t i = 0; i < len / 2; i++) s[i] >>= 1;
}

// Blocking read — uses readBytes (respects stream timeout) + stop check
static bool aread(WiFiClient& st, uint8_t* dst, size_t n) {
    size_t got = 0;
    while (got < n && !audio_stop) {
        size_t want = min((size_t)64, n - got);
        size_t r = st.readBytes(dst + got, want);
        got += r;
        if (r == 0) return false;   // stream timeout — connection dead
    }
    return got == n;
}

static uint16_t u16le(uint8_t* b) { return b[0] | (b[1] << 8); }
static uint32_t u32le(uint8_t* b) { return b[0]|(b[1]<<8)|(b[2]<<16)|(b[3]<<24); }

// Parse WAV header, configure I2S, return PCM data byte count (0 on error)
static uint32_t wav_parse(WiFiClient& st) {
    uint8_t h[12];
    if (!aread(st, h, 12)) return 0;
    if (memcmp(h, "RIFF", 4) || memcmp(h + 8, "WAVE", 4)) return 0;

    uint32_t rate = 22050;  uint16_t ch = 1, bits = 16;  uint32_t dlen = 0;
    uint8_t ch8[8];
    while (aread(st, ch8, 8) && !audio_stop) {
        uint32_t csz = u32le(ch8 + 4);
        if (!memcmp(ch8, "fmt ", 4)) {
            uint8_t f[16]; uint32_t r = min((uint32_t)16, csz);
            if (!aread(st, f, r)) return 0;
            for (uint32_t i = r; i < csz; i++) { uint8_t b; aread(st, &b, 1); }
            ch   = u16le(f + 2);
            rate = u32le(f + 4);
            bits = u16le(f + 14);
            i2s_setup(rate, ch, bits);
        } else if (!memcmp(ch8, "data", 4)) {
            dlen = csz; break;
        } else {
            for (uint32_t i = 0; i < csz && !audio_stop; i++) { uint8_t b; aread(st, &b, 1); }
        }
    }
    return dlen;
}

// Stream audio: pre-buffer 64KB for smooth start, then stream the rest.
// Runs entirely on core 0 (audio task). No large contiguous alloc needed.
static void stream_audio(const char* url) {
    HTTPClient http;
    http.begin(url);
    http.setTimeout(15000);
    int code = http.GET();
    if (code != HTTP_CODE_OK) {
        Serial.printf("[audio] HTTP %d\n", code);
        http.end();
        return;
    }

    WiFiClient* st = http.getStreamPtr();
    st->setTimeout(3000);
    uint32_t dlen = wav_parse(*st);
    if (!dlen || audio_stop) { http.end(); return; }

    // ── Phase 1: fill pre-buffer (64 KB) ──
    size_t pre_target = min((size_t)dlen, (size_t)AUDIO_PRE_SIZE);
    size_t pre = 0;
    uint32_t dl = millis() + 10000;
    while (pre < pre_target && millis() < dl && !audio_stop) {
        size_t want = min((size_t)4096, pre_target - pre);
        size_t n = st->readBytes(audio_pre + pre, want);
        pre += n;
        if (n == 0 && !st->connected()) break;
    }
    if (audio_stop || pre == 0) { http.end(); return; }

    Serial.printf("[audio] pre-buffered %u/%u bytes, streaming %u total\n", pre, pre_target, dlen);
    atten6dB(audio_pre, pre);

    // ── Phase 2: start playback ──
    digitalWrite(PIN_AMP_SD, HIGH);
    delayMicroseconds(100);

    size_t wr;
    i2s_channel_write(tx_handle, audio_pre, pre, &wr, portMAX_DELAY);
    uint32_t remaining = dlen - pre;

    // ── Phase 3: stream remainder with non-blocking reads ──
    // The 64 KB pre-buffer gave I2S a ~1.4s head start.
    // WiFi fills faster than I2S drains, so the DMA stays fed.
    uint8_t chunk[4096];
    while (remaining > 0 && !audio_stop) {
        int avail = st->available();
        if (avail > 0) {
            size_t toRead = min((size_t)avail, min(sizeof(chunk), (size_t)remaining));
            size_t n = st->read(chunk, toRead);
            if (n > 0) {
                atten6dB(chunk, n);
                i2s_channel_write(tx_handle, chunk, n, &wr, portMAX_DELAY);
                remaining -= n;
            }
        } else if (!st->connected()) {
            break;   // server closed connection
        } else {
            delay(1);  // brief yield — TCP data in flight
        }
    }

    if (!audio_stop) delay(700);   // flush DMA tail (12×1024 frames ≈ 0.56s at 22050 Hz)
    digitalWrite(PIN_AMP_SD, LOW);
    http.end();
    Serial.printf("[audio] done (remaining=%u)\n", remaining);
}

// Audio task on core 0 — receives URL, does HTTP + I2S streaming
static void audio_task(void*) {
    AudioCmd cmd;
    while (true) {
        if (xQueueReceive(audio_q, &cmd, portMAX_DELAY) == pdTRUE) {
            audio_playing = true;
            audio_stop    = false;
            stream_audio(cmd.url);
            audio_playing = false;
        }
    }
}

static void play_audio(const String& url) {
    AudioCmd cmd;
    url.toCharArray(cmd.url, AUDIO_URL_MAX);
    xQueueSend(audio_q, &cmd, 0);
}

static void stop_audio() {
    AudioCmd dummy;
    while (xQueueReceive(audio_q, &dummy, 0) == pdTRUE) {}
    if (!audio_playing) return;
    audio_stop = true;
    uint32_t t = millis();
    while (audio_playing && millis() - t < 2000) delay(10);
    audio_stop = false;
}

// ═══════════════════════════════════════════════════════════════════════════
//  BATTERY
// ═══════════════════════════════════════════════════════════════════════════

static void update_battery() {
    if (millis() - last_bat < BATTERY_INTERVAL_MS) return;
    last_bat = millis();
    float v = analogReadMilliVolts(PIN_BATTERY) * 2.0f / 1000.0f;
    bat_v = (v >= 2.5f && v <= 4.5f) ? v : -1.0f;
}

// ═══════════════════════════════════════════════════════════════════════════
//  WIFI
// ═══════════════════════════════════════════════════════════════════════════

static bool connect_wifi(uint32_t timeout) {
    if (WiFi.status() == WL_CONNECTED) { wifi_up = true; return true; }
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t0 < timeout) delay(100);
    wifi_up = (WiFi.status() == WL_CONNECTED);
    return wifi_up;
}

// ═══════════════════════════════════════════════════════════════════════════
//  QUIZ API
// ═══════════════════════════════════════════════════════════════════════════

// Fetch categories from service status endpoint
static void fetch_categories() {
    HTTPClient http;
    http.begin(String(SERVICE_BASE) + "/api/admin/status");
    http.setTimeout(FETCH_TIMEOUT_MS);
    int code = http.GET();
    if (code == HTTP_CODE_OK) {
        String body = http.getString();
        JsonDocument doc;
        if (!deserializeJson(doc, body)) {
            JsonArray cats = doc["categories"];
            num_cats = 0;
            for (JsonVariant c : cats) {
                if (num_cats >= MAX_CATS) break;
                const char* name = c.as<const char*>();
                if (name) {
                    strncpy(cat_names[num_cats], name, 23);
                    cat_names[num_cats][23] = 0;
                    cat_enabled[num_cats] = true;
                    num_cats++;
                }
            }
        }
    }
    http.end();

    // Fallback if fetch fails
    if (num_cats == 0) {
        const char* defaults[] = {"general", "science", "history", "geography", "entertainment", "sports"};
        for (int i = 0; i < 6; i++) {
            strncpy(cat_names[i], defaults[i], 23);
            cat_names[i][23] = 0;
            cat_enabled[i] = true;
        }
        num_cats = 6;
    }
    Serial.printf("Categories: %d loaded\n", num_cats);
}

// URL-encode a string (spaces, special chars) into dst. Returns dst.
static char* url_encode(const char* src, char* dst, int maxlen) {
    int j = 0;
    for (int i = 0; src[i] && j < maxlen - 3; i++) {
        char c = src[i];
        if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
            (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' || c == '~') {
            dst[j++] = c;
        } else {
            j += snprintf(dst + j, maxlen - j, "%%%02X", (unsigned char)c);
        }
    }
    dst[j] = 0;
    return dst;
}

// Fetch a question using the currently enabled categories as filter.
// Sends comma-separated list so the pool can match any of them.
static QuizQ fetch_question(Error* err = nullptr) {
    QuizQ q;
    String url = String(SERVICE_BASE) + "/api/quiz";

    int enabled = count_enabled_cats();

    if (enabled > 0 && enabled < num_cats) {
        // Subset — send comma-separated list
        url += "?category=";
        bool first = true;
        for (int i = 0; i < num_cats; i++) {
            if (cat_enabled[i]) {
                if (!first) url += ",";
                char enc[72];
                url_encode(cat_names[i], enc, sizeof(enc));
                url += enc;
                first = false;
            }
        }
    }
    // else: all enabled (or none) → no filter

    // Store info for error display
    if (enabled == 0 || enabled == num_cats) {
        strcpy(err_cat, "all");
    } else if (enabled == 1) {
        for (int i = 0; i < num_cats; i++) {
            if (cat_enabled[i]) { strncpy(err_cat, cat_names[i], 23); err_cat[23] = 0; break; }
        }
    } else {
        snprintf(err_cat, sizeof(err_cat), "%d of %d cats", enabled, num_cats);
    }

    HTTPClient http;
    http.begin(url);
    http.setTimeout(FETCH_TIMEOUT_MS);
    int code = http.GET();
    err_http = code;
    Serial.printf("[quiz] GET %s -> %d\n", url.c_str(), code);

    if (code == HTTP_CODE_OK) {
        JsonDocument doc;
        if (!deserializeJson(doc, http.getString())) {
            q.id      = doc["id"].as<String>();
            q.category= doc["category"].as<String>();
            q.q_text  = doc["question_text"].as<String>();
            q.a_text  = doc["answer_text"].as<String>();
            q.q_audio = doc["question_audio_url"].as<String>();
            q.a_audio = doc["answer_audio_url"].as<String>();
            q.valid   = true;
        } else if (err) *err = E_SERVICE;
    } else if (code == 503) {
        if (err) *err = E_EMPTY;
    } else {
        if (err) *err = E_SERVICE;
    }

    http.end();
    return q;
}

// ═══════════════════════════════════════════════════════════════════════════
//  TEXT RENDERING  — word-wrap for TFT_eSPI
// ═══════════════════════════════════════════════════════════════════════════

// Draw word-wrapped text. Returns Y after last line. Font must already be set.
static int draw_wrapped(const char* text, int x, int y, int maxw, int maxy,
                        uint16_t fg, uint16_t bg) {
    if (!text || !*text) return y;
    tft.setTextColor(fg, bg);
    tft.setTextDatum(TL_DATUM);
    int lh = tft.fontHeight();

    // Mutable copy for strtok
    size_t len = strlen(text);
    char* buf = (char*)malloc(len + 1);
    if (!buf) return y;
    strcpy(buf, text);

    char line[256] = "";
    char* word = strtok(buf, " \n");
    int cy = y;

    while (word) {
        char test[256];
        if (!line[0]) {
            strncpy(test, word, 255); test[255] = 0;
        } else {
            snprintf(test, 256, "%s %s", line, word);
        }

        if (tft.textWidth(test) <= maxw) {
            strcpy(line, test);
        } else {
            if (cy + lh > maxy) break;
            tft.drawString(line, x, cy);
            cy += lh + 2;
            strncpy(line, word, 255); line[255] = 0;
        }
        word = strtok(NULL, " \n");
    }
    if (line[0] && cy + lh <= maxy) { tft.drawString(line, x, cy); cy += lh; }
    free(buf);
    return cy;
}

// Count lines that word-wrapped text would occupy. Font must already be set.
static int count_lines(const char* text, int maxw) {
    if (!text || !*text) return 0;
    size_t len = strlen(text);
    char* buf = (char*)malloc(len + 1);
    if (!buf) return 1;
    strcpy(buf, text);

    int lines = 0;
    char line[256] = "";
    char* word = strtok(buf, " \n");
    while (word) {
        char test[256];
        if (!line[0]) { strncpy(test, word, 255); test[255] = 0; }
        else          { snprintf(test, 256, "%s %s", line, word); }

        if (tft.textWidth(test) <= maxw) { strcpy(line, test); }
        else { lines++; strncpy(line, word, 255); line[255] = 0; }
        word = strtok(NULL, " \n");
    }
    if (line[0]) lines++;
    free(buf);
    return lines;
}

// ═══════════════════════════════════════════════════════════════════════════
//  UI COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

static void btn_primary(const char* label, int x, int y, int w, int h) {
    tft.fillRoundRect(x, y, w, h, BTN_R, COL_GOLD);
    tft.setTextColor(COL_BG, COL_GOLD);
    tft.setTextDatum(MC_DATUM);
    tft.setFreeFont(&FreeSansBold12pt7b);
    tft.drawString(label, x + w / 2, y + h / 2);
}

static void btn_secondary(const char* label, int x, int y, int w, int h) {
    tft.fillRoundRect(x, y, w, h, 6, COL_BTN_BG);
    tft.drawRoundRect(x, y, w, h, 6, COL_GOLD_DIM);
    tft.drawRoundRect(x+1, y+1, w-2, h-2, 5, COL_GOLD_DIM);
    tft.setTextColor(COL_TEXT, COL_BTN_BG);
    tft.setTextDatum(MC_DATUM);
    tft.setFreeFont(&FreeSansBold12pt7b);
    tft.drawString(label, x + w / 2, y + h / 2);
}

static void btn_error(const char* label, int x, int y, int w, int h) {
    tft.fillRoundRect(x, y, w, h, 6, COL_BTN_BG);
    tft.drawRoundRect(x, y, w, h, 6, COL_RED);
    tft.drawRoundRect(x+1, y+1, w-2, h-2, 5, COL_RED);
    tft.setTextColor(COL_TEXT, COL_BTN_BG);
    tft.setTextDatum(MC_DATUM);
    tft.setFreeFont(&FreeSansBold12pt7b);
    tft.drawString(label, x + w / 2, y + h / 2);
}

// Replay button — small square with circular arrow icon
static void btn_replay(int x, int y, int w, int h) {
    tft.fillRoundRect(x, y, w, h, 6, COL_BTN_BG);
    tft.drawRoundRect(x, y, w, h, 6, COL_GOLD_DIM);
    tft.drawRoundRect(x+1, y+1, w-2, h-2, 5, COL_GOLD_DIM);

    int cx = x + w / 2, cy = y + h / 2;

    // Draw 270-degree arc (skip 30-degree gap at top-right)
    for (int a = 30; a <= 300; a++) {
        float rad = a * 0.01745329f;
        tft.drawPixel(cx + (int)(10.0f * cosf(rad)), cy - (int)(10.0f * sinf(rad)), COL_TEXT);
        tft.drawPixel(cx + (int)(9.0f * cosf(rad)),  cy - (int)(9.0f * sinf(rad)),  COL_TEXT);
    }

    // Arrowhead at 30-degree end (upper-right), pointing clockwise
    int ax = cx + 8, ay = cy - 4;
    tft.fillTriangle(ax - 3, ay - 4, ax + 3, ay + 1, ax - 4, ay + 3, COL_TEXT);
}

// Category badge — shows enabled count in header
// Draw category badge in header. If cat_name is non-null, show that
// category in bold (used on question/answer screens). Otherwise show
// the enabled count summary.
static void draw_badge(uint16_t bg, const char* cat_name = nullptr) {
    char label[24];

    if (cat_name) {
        // Show specific category name — uppercase, bold
        int i = 0;
        while (cat_name[i] && i < 22) { label[i] = toupper(cat_name[i]); i++; }
        label[i] = 0;
    } else {
        // Show enabled count summary
        int enabled = 0;
        for (int i = 0; i < num_cats; i++) if (cat_enabled[i]) enabled++;
        if (enabled == num_cats)    snprintf(label, sizeof(label), "ALL");
        else if (enabled == 0)      snprintf(label, sizeof(label), "NONE");
        else                        snprintf(label, sizeof(label), "%d/%d", enabled, num_cats);
    }

    // Use bold font for category name, regular for summary
    if (cat_name)
        tft.setFreeFont(&FreeSansBold9pt7b);
    else
        tft.setTextFont(2);
    tft.setTextDatum(TL_DATUM);

    // Truncate if too wide
    while (tft.textWidth(label) > 160 && strlen(label) > 4) {
        int l = strlen(label) - 1;
        label[l] = 0; label[l-1] = '.'; label[l-2] = '.';
    }

    int tw = tft.textWidth(label);
    int bw = tw + 12, bh = 24;
    tft.fillRect(PAD, 8, 180, 24, COL_PANEL);

    int enabled = 0;
    for (int i = 0; i < num_cats; i++) if (cat_enabled[i]) enabled++;
    uint16_t badge_bg = (enabled == 0 && !cat_name) ? COL_RED : bg;
    tft.fillRoundRect(PAD, 8, bw, bh, 4, badge_bg);
    tft.setTextColor(COL_BG, badge_bg);
    tft.drawString(label, PAD + 6, cat_name ? 10 : 12);
}

// WiFi icon — concentric arcs
static void draw_wifi() {
    int cx = 435, cy = 20;
    uint16_t c = wifi_up ? COL_GREEN : COL_RED;
    // Clear area
    tft.fillRect(cx - 10, cy - 10, 20, 20, COL_PANEL);
    tft.drawCircle(cx, cy, 8, c);
    tft.drawCircle(cx, cy, 5, c);
    tft.fillCircle(cx, cy, 2, c);
}

// Battery voltage — right side of header
static void draw_bat() {
    tft.fillRect(452, 8, 28, 24, COL_PANEL);
    tft.setTextFont(2);
    tft.setTextDatum(TR_DATUM);
    tft.setTextColor(COL_TEXT_DIM, COL_PANEL);
    if (bat_v < 0)
        tft.drawString("---", 478, 12);
    else {
        char b[8]; snprintf(b, sizeof(b), "%.1fV", bat_v);
        tft.drawString(b, 478, 12);
    }
}

// Audio indicator — three bars
static void draw_indicator(bool vis) {
    int x = 390, y = 12;
    tft.fillRect(x, y, 35, 16, COL_PANEL);
    if (vis && audio_playing) {
        tft.fillRect(x,      y + 10, 4, 6,  COL_AUDIO);
        tft.fillRect(x + 7,  y + 6,  4, 10, COL_AUDIO);
        tft.fillRect(x + 14, y + 2,  4, 14, COL_AUDIO);
    }
}

// Question count  "? N"
static void draw_qcount() {
    tft.fillRect(330, 8, 55, 24, COL_PANEL);
    tft.setTextFont(2);
    tft.setTextDatum(TR_DATUM);
    tft.setTextColor(COL_TEXT_DIM, COL_PANEL);
    char b[12]; snprintf(b, sizeof(b), "? %d", q_count);
    tft.drawString(b, 380, 12);
}

// Full header bar. If cat_name is set, badge shows that category in bold.
static void draw_header(const char* cat_name = nullptr) {
    tft.fillRect(0, 0, SCR_W, HDR_H, COL_PANEL);
    draw_badge(COL_CYAN, cat_name);
    draw_qcount();
    draw_wifi();
    draw_bat();
    if (audio_playing) draw_indicator(true);
}

static void clear_content() { tft.fillRect(0, CTN_Y, SCR_W, CTN_H, COL_BG); }
static void clear_action()  { tft.fillRect(0, ACT_Y, SCR_W, ACT_H, COL_BG); }

// Diamond glyph (filled rotated square)
static void draw_diamond(int cx, int cy, int s, uint16_t c) {
    tft.fillTriangle(cx, cy - s, cx + s, cy, cx, cy + s, c);
    tft.fillTriangle(cx, cy - s, cx - s, cy, cx, cy + s, c);
}

// ═══════════════════════════════════════════════════════════════════════════
//  CATEGORY GRID  — drawn on the main/category selection screen
// ═══════════════════════════════════════════════════════════════════════════

// Grid layout params (reused for drawing + hit testing)
static int cat_col_w, cat_row_h, cat_start_y;
static const int CAT_COLS = 2, CAT_COL_GAP = 10, CAT_ROW_GAP = 6;

static void calc_grid_layout() {
    int rows = (num_cats + CAT_COLS - 1) / CAT_COLS;
    cat_col_w = (USE_W - CAT_COL_GAP) / CAT_COLS;        // 223
    int avail_h = CTN_H - 12;                              // 188
    cat_row_h = (avail_h - (rows - 1) * CAT_ROW_GAP) / rows;
    if (cat_row_h > 42) cat_row_h = 42;                    // smaller max height
    int total_h = rows * cat_row_h + (rows - 1) * CAT_ROW_GAP;
    cat_start_y = CTN_Y + (CTN_H - total_h) / 2;
}

static void draw_cat_button(int idx) {
    int col = idx % CAT_COLS;
    int row = idx / CAT_COLS;
    int x = PAD + col * (cat_col_w + CAT_COL_GAP);
    int y = cat_start_y + row * (cat_row_h + CAT_ROW_GAP);
    bool enabled = cat_enabled[idx];

    uint16_t bg     = enabled ? COL_BTN_BG   : COL_BG;
    uint16_t border = enabled ? COL_GOLD     : COL_TEXT_DIM;
    uint16_t txt    = enabled ? COL_GOLD     : COL_TEXT_DIM;

    tft.fillRoundRect(x, y, cat_col_w, cat_row_h, 6, bg);
    tft.drawRoundRect(x, y, cat_col_w, cat_row_h, 6, border);
    if (enabled)
        tft.drawRoundRect(x + 1, y + 1, cat_col_w - 2, cat_row_h - 2, 5, border);

    // Capitalize first letter
    char label[24];
    int j = 0;
    const char* name = cat_names[idx];
    while (name[j] && j < 22) { label[j] = (j == 0) ? toupper(name[j]) : name[j]; j++; }
    label[j] = 0;

    tft.setTextFont(4);
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(txt, bg);
    tft.drawString(label, x + cat_col_w / 2, y + cat_row_h / 2);
}

static void draw_category_grid() {
    if (num_cats == 0) return;
    calc_grid_layout();
    for (int i = 0; i < num_cats; i++) draw_cat_button(i);
}

// Returns true if any category is enabled
static bool any_cats_enabled() {
    for (int i = 0; i < num_cats; i++) {
        if (cat_enabled[i]) return true;
    }
    return false;
}

static void draw_main_action() {
    clear_action();
    if (any_cats_enabled()) {
        btn_primary("NEW QUESTION", PAD, BTN_Y, USE_W, BTN_H);
    } else {
        tft.fillRoundRect(PAD, BTN_Y, USE_W, BTN_H, BTN_R, COL_BTN_BG);
        tft.setTextColor(COL_TEXT_DIM, COL_BTN_BG);
        tft.setTextDatum(MC_DATUM);
        tft.setFreeFont(&FreeSansBold12pt7b);
        tft.drawString("SELECT A CATEGORY", PAD + USE_W / 2, BTN_Y + BTN_H / 2);
    }
}

// Handle tap on the category grid — returns true if a category was toggled
static bool handle_category_tap(uint16_t tx, uint16_t ty) {
    if (num_cats == 0) return false;

    int col = (tx - PAD) / (cat_col_w + CAT_COL_GAP);
    int row = (ty - cat_start_y) / (cat_row_h + CAT_ROW_GAP);
    if (col < 0 || col >= CAT_COLS || row < 0) return false;

    int idx = row * CAT_COLS + col;
    if (idx >= num_cats) return false;

    // Verify tap is within the button bounds (not in gap)
    int bx = PAD + col * (cat_col_w + CAT_COL_GAP);
    int by = cat_start_y + row * (cat_row_h + CAT_ROW_GAP);
    if (tx < bx || tx >= bx + cat_col_w || ty < by || ty >= by + cat_row_h) return false;

    cat_enabled[idx] = !cat_enabled[idx];
    draw_cat_button(idx);
    draw_badge(COL_CYAN);
    draw_main_action();
    Serial.printf("Category '%s' %s\n", cat_names[idx], cat_enabled[idx] ? "ON" : "OFF");
    return true;
}

// ═══════════════════════════════════════════════════════════════════════════
//  SCREEN DRAWING
// ═══════════════════════════════════════════════════════════════════════════

static void scr_splash() {
    tft.invertDisplay(true);
    tft.fillScreen(TFT_BLACK);
    int ox = (SCR_W - LOGO_WIDTH) / 2;
    int oy = (SCR_H - LOGO_HEIGHT) / 2;
    int bw = (LOGO_WIDTH + 7) / 8;
    for (int j = 0; j < LOGO_HEIGHT; j++) {
        int run = -1;
        for (int i = 0; i <= LOGO_WIDTH; i++) {
            bool set = i < LOGO_WIDTH &&
                (pgm_read_byte(logo_bitmap + j * bw + i / 8) & (1 << (i & 7)));
            if (set && run < 0) run = i;
            else if (!set && run >= 0) {
                tft.drawFastHLine(ox + run, oy + j, i - run, COL_LOGO_RED);
                run = -1;
            }
        }
    }
}

static void scr_main() {
    draw_header();
    clear_content();

    draw_category_grid();
    draw_main_action();
}

static void scr_loading() {
    draw_header();
    clear_content();
    clear_action();

    tft.setTextFont(4);
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(COL_TEXT_DIM, COL_BG);
    tft.drawString("Loading...", SCR_W / 2, CTN_Y + CTN_H / 2 - 10);
    load_dot = 0; load_last = 0;
}

static void update_loading_dots() {
    if (millis() - load_last < 300) return;
    load_last = millis();
    int cx = SCR_W / 2, cy = CTN_Y + CTN_H / 2 + 20, sp = 20;
    for (int i = 0; i < 3; i++) tft.fillCircle(cx + (i - 1) * sp, cy, 4, COL_BG);
    tft.fillCircle(cx + (load_dot - 1) * sp, cy, 4, COL_GOLD);
    load_dot = (load_dot + 1) % 3;
}

static void scr_question() {
    draw_header(cur_q.category.c_str());
    clear_content();
    clear_action();

    int avail_h = (ACT_Y - 8) - (CTN_Y + 16);  // vertical space for text

    // Try 18pt first, fall back to 12pt if text won't fit
    tft.setFreeFont(&FreeSans18pt7b);
    int n = count_lines(cur_q.q_text.c_str(), USE_W);
    int max_lines = avail_h / (tft.fontHeight() + 2);
    if (n > max_lines) {
        tft.setFreeFont(&FreeSans12pt7b);
    }

    draw_wrapped(cur_q.q_text.c_str(), PAD, CTN_Y + 16, USE_W, ACT_Y - 8, COL_TEXT, COL_BG);

    // REVEAL ANSWER + replay button
    int reveal_w = USE_W - REPLAY_W - REPLAY_GAP;
    btn_primary("REVEAL ANSWER", PAD, BTN_Y, reveal_w, BTN_H);
    btn_replay(REPLAY_X, BTN_Y, REPLAY_W, BTN_H);
}

static void scr_answer() {
    // Gold flash reveal
    tft.fillRect(0, CTN_Y, SCR_W, CTN_H, COL_GOLD);
    delay(80);

    draw_header(cur_q.category.c_str());
    clear_content();
    clear_action();

    int ty = CTN_Y + 8;

    // Dimmed question (Font 2)
    tft.setTextFont(2);
    ty = draw_wrapped(cur_q.q_text.c_str(), PAD, ty, USE_W, CTN_Y + 80, COL_TEXT_DIM, COL_BG);

    // Gold divider
    ty += 6;
    tft.fillRect(PAD, ty, USE_W, 2, COL_GOLD);
    ty += 8;

    // Answer in green (24pt)
    tft.setFreeFont(&FreeSans24pt7b);
    draw_wrapped(cur_q.a_text.c_str(), PAD, ty, USE_W, ACT_Y - 4, COL_GREEN, COL_BG);

    // Split buttons: CATEGORY + NEXT QUESTION + REPLAY
    int next_w = USE_W - SPLIT_W - SPLIT_GAP - REPLAY_W - REPLAY_GAP;
    btn_secondary("CATEGORY", PAD, BTN_Y, SPLIT_W, BTN_H);
    btn_primary("NEXT QUESTION", SPLIT_R_X, BTN_Y, next_w, BTN_H);
    btn_replay(REPLAY_X, BTN_Y, REPLAY_W, BTN_H);
}

static void scr_error() {
    draw_header();
    clear_content();
    clear_action();

    const char *title, *d1, *d2;
    uint16_t tc;
    switch (cur_error) {
        case E_WIFI:  title="No WiFi"; d1="Could not connect to network.";
                      d2="Check that WiFi is available."; tc=COL_RED; break;
        case E_SERVICE: title="Service Unavailable"; d1="Quiz service is not responding.";
                        d2="It may be starting up."; tc=COL_RED; break;
        case E_EMPTY: title="No Questions Ready"; d1="The quiz service is generating";
                      d2="questions. Try again shortly."; tc=COL_GOLD; break;
        default:      title="Error"; d1="Something went wrong."; d2=""; tc=COL_RED; break;
    }

    tft.setTextFont(4);
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(tc, COL_BG);
    tft.drawString(title, SCR_W / 2, CTN_Y + 50);

    tft.setTextFont(2);
    tft.setTextColor(COL_TEXT_DIM, COL_BG);
    tft.drawString(d1, SCR_W / 2, CTN_Y + 95);
    tft.drawString(d2, SCR_W / 2, CTN_Y + 118);

    // Error detail line: HTTP code + category
    char detail[64];
    if (err_http != 0) {
        snprintf(detail, sizeof(detail), "HTTP %d  |  category: %s", err_http, err_cat);
    } else {
        snprintf(detail, sizeof(detail), "category: %s", err_cat);
    }
    tft.setTextColor(COL_TEXT_DIM, COL_BG);
    tft.drawString(detail, SCR_W / 2, CTN_Y + 150);

    // Split buttons: CATEGORY + RETRY
    btn_secondary("CATEGORY", PAD, BTN_Y, SPLIT_W, BTN_H);
    int retry_w = USE_W - SPLIT_W - SPLIT_GAP;
    btn_error("RETRY", SPLIT_R_X, BTN_Y, retry_w, BTN_H);
}

// ═══════════════════════════════════════════════════════════════════════════
//  TOUCH HANDLING
// ═══════════════════════════════════════════════════════════════════════════

// Attempt to fetch and show a question (handles loading + error transitions)
static void do_fetch_and_show() {
    if (!any_cats_enabled()) return;

    cur_screen = S_LOADING;
    scr_loading();

    if (!wifi_up && !connect_wifi(WIFI_TIMEOUT_MS)) {
        cur_error = E_WIFI; cur_screen = S_ERROR; scr_error(); return;
    }

    Error err = E_NONE;
    QuizQ q = fetch_question(&err);
    if (q.valid) {
        cur_q = q;
        q_count++;
        cur_screen = S_QUESTION;
        scr_question();
        play_audio(cur_q.q_audio);
    } else {
        cur_error = (err != E_NONE) ? err : E_SERVICE;
        cur_screen = S_ERROR;
        scr_error();
    }
}

static void handle_touch() {
    uint16_t tx, ty;
    if (!tft.getTouch(&tx, &ty)) return;
    ty = tft.height() - 1 - ty;   // Y-axis inversion fix

    // Debounce
    if (millis() - last_touch < TOUCH_DEBOUNCE_MS) return;
    last_touch = millis();

    // Touch zones
    bool in_cat     = (ty < HDR_H && tx < SCR_W / 3);
    bool in_action  = (ty >= ACT_Y);
    bool in_replay  = (in_action && tx >= REPLAY_X);
    bool in_act_l   = (in_action && tx < PAD + SPLIT_W + SPLIT_GAP);
    bool in_content = (ty >= CTN_Y && ty < ACT_Y);

    switch (cur_screen) {

    case S_MAIN:
        if (in_content) {
            handle_category_tap(tx, ty);
        } else if (in_action && any_cats_enabled()) {
            do_fetch_and_show();
        }
        break;

    case S_QUESTION:
        if (in_cat) {
            // Go back to category selection
            stop_audio();
            cur_screen = S_MAIN;
            scr_main();
        } else if (in_replay) {
            // Replay question audio
            stop_audio();
            play_audio(cur_q.q_audio);
        } else if (in_action) {
            // Reveal answer
            stop_audio();
            cur_screen = S_ANSWER;
            scr_answer();
            play_audio(cur_q.a_audio);
            pre_started = false;
            pre_done    = false;
        }
        break;

    case S_ANSWER:
        if (in_replay) {
            // Replay answer audio
            stop_audio();
            play_audio(cur_q.a_audio);
        } else if (in_action && tx >= SPLIT_R_X) {
            // NEXT QUESTION
            stop_audio();
            if (pre_done && pre_q.valid) {
                cur_q = pre_q;
                pre_done = false;
                q_count++;
                cur_screen = S_QUESTION;
                scr_question();
                play_audio(cur_q.q_audio);
                pre_started = false;
            } else {
                do_fetch_and_show();
                pre_started = false;
                pre_done    = false;
            }
        } else if (in_cat || in_act_l) {
            // Go back to category selection
            stop_audio();
            cur_screen = S_MAIN;
            scr_main();
        }
        break;

    case S_ERROR:
        if (in_cat || in_act_l) {
            // Go back to category selection
            cur_screen = S_MAIN;
            scr_main();
        } else if (in_action && tx >= SPLIT_R_X) {
            // Retry
            if (cur_error == E_WIFI) {
                cur_screen = S_LOADING; scr_loading();
                if (connect_wifi(WIFI_TIMEOUT_MS)) {
                    cur_screen = S_MAIN; scr_main();
                } else {
                    cur_error = E_WIFI; cur_screen = S_ERROR; scr_error();
                }
            } else {
                do_fetch_and_show();
            }
        }
        break;

    default: break;
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  DEEP SLEEP
// ═══════════════════════════════════════════════════════════════════════════

static void enter_sleep() {
    Serial.println("Entering deep sleep");
    stop_audio();
    tft.fillScreen(COL_BG);
    tft.setTextFont(2);
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(COL_TEXT_DIM, COL_BG);
    tft.drawString("Sleeping...", SCR_W / 2, SCR_H / 2);
    delay(500);

    digitalWrite(PIN_AMP_SD, LOW);
    tft.fillScreen(TFT_BLACK);

    esp_sleep_enable_ext0_wakeup((gpio_num_t)PIN_TOUCH_IRQ, 0);  // LOW = touched
    esp_deep_sleep_start();
}

// ═══════════════════════════════════════════════════════════════════════════
//  SETUP
// ═══════════════════════════════════════════════════════════════════════════

void setup() {
    // Pre-allocate 64KB audio pre-buffer before WiFi fragments the heap.
    // Only 64KB needed (not the full audio file) — rest is streamed.
    audio_pre = (uint8_t*)malloc(AUDIO_PRE_SIZE);

    Serial.begin(115200);
    delay(500);
    Serial.println("=== QuizMaster ===");
    Serial.printf("Audio pre-buf: %s (%u bytes, free=%u)\n",
                  audio_pre ? "OK" : "FAIL", AUDIO_PRE_SIZE, ESP.getFreeHeap());

    // Pins
    pinMode(PIN_AMP_SD, OUTPUT);
    digitalWrite(PIN_AMP_SD, LOW);
    pinMode(PIN_TOUCH_IRQ, INPUT);
    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);

    // Display
    tft.init();
    tft.setRotation(1);   // landscape 480x320
    tft.setTouch(calData);
    tft.fillScreen(COL_BG);

    // I2S (default — reconfigured per WAV)
    i2s_setup(22050, 1, 16);

    // Audio task on core 0
    audio_q = xQueueCreate(2, sizeof(AudioCmd));
    xTaskCreatePinnedToCore(audio_task, "audio", 8192, NULL, 1, &audio_th, 0);

    // ── Splash ──
    cur_screen = S_SPLASH;
    scr_splash();

    // Start WiFi during splash — play welcome audio as soon as connected
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    String welcome_wav = String(SERVICE_BASE) + "/audio/welcome.wav";
    bool welcome_started = false;
    uint32_t t0 = millis();
    while (millis() - t0 < SPLASH_HOLD_MS || audio_playing) {
        if (WiFi.status() == WL_CONNECTED && !wifi_up) {
            wifi_up = true;
            Serial.printf("WiFi OK: %s\n", WiFi.localIP().toString().c_str());
        }
        if (wifi_up && !welcome_started) {
            welcome_started = true;
            play_audio(welcome_wav);
        }
        if (millis() - t0 > 8000) break;   // hard cap
        delay(50);
    }
    wifi_up = (WiFi.status() == WL_CONNECTED);

    // Fetch categories from service
    if (wifi_up) fetch_categories();
    else {
        // Use fallback defaults
        const char* defaults[] = {"general", "science", "history", "geography", "entertainment", "sports"};
        for (int i = 0; i < 6; i++) {
            strncpy(cat_names[i], defaults[i], 23);
            cat_names[i][23] = 0;
            cat_enabled[i] = true;
        }
        num_cats = 6;
    }

    // Initial battery read
    last_bat = 0;  // force immediate read
    update_battery();

    // Transition: band wipe
    int bh = SCR_H / 8;
    for (int i = 0; i < 8; i++) { tft.fillRect(0, i * bh, SCR_W, bh, COL_BG); delay(30); }

    cur_screen = S_MAIN;
    scr_main();
    last_touch = millis();
}

// ═══════════════════════════════════════════════════════════════════════════
//  MAIN LOOP  (~50 Hz)
// ═══════════════════════════════════════════════════════════════════════════

void loop() {
    wifi_up = (WiFi.status() == WL_CONNECTED);

    // ── Touch ──
    handle_touch();

    // ── Audio indicator pulse ──
    if (audio_playing) {
        if (millis() - ind_last >= INDICATOR_TOGGLE_MS) {
            ind_last = millis();
            ind_vis = !ind_vis;
            draw_indicator(ind_vis);
        }
    } else if (ind_vis) {
        ind_vis = false;
        draw_indicator(false);
    }

    // ── Loading dots ──
    if (cur_screen == S_LOADING) update_loading_dots();

    // ── Battery ──
    update_battery();
    static uint32_t bat_draw = 0;
    if (millis() - bat_draw >= BATTERY_INTERVAL_MS && cur_screen != S_SPLASH) {
        bat_draw = millis();
        draw_bat();
    }

    // ── WiFi status change → refresh ──
    if (wifi_up != prev_wifi_up) {
        prev_wifi_up = wifi_up;
        if (cur_screen != S_SPLASH) draw_wifi();
    }

    // ── Prefetch during answer screen ──
    if (cur_screen == S_ANSWER && !pre_started && !pre_done) {
        pre_started = true;
        pre_q = fetch_question();   // err ignored for prefetch
        pre_done = pre_q.valid;
        Serial.printf("Prefetch: %s\n", pre_done ? "ok" : "failed");
    }

    // ── Idle timeout → deep sleep ──
    if (millis() - last_touch > IDLE_TIMEOUT_MS) enter_sleep();

    delay(20);
}
