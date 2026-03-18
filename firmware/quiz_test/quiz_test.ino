// QuizMaster — single question fetch + play test (ESP32 DevKitV1)
// No display or buttons needed.
// Fetches one question from the quiz service, plays question audio then answer audio.

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "driver/i2s_std.h"

// ── Config ────────────────────────────────────────────────────────────────────
#define WIFI_SSID     "Solipsia"
#define WIFI_PASSWORD "313920Airport"
#define SERVICE_BASE  "http://synology.local:8080"

// ESP32 DevKitV1 — use GPIO numbers directly
#define PIN_AMP_SD  32
#define PIN_BCLK    ((gpio_num_t)25)
#define PIN_LRC     ((gpio_num_t)26)
#define PIN_DIN     ((gpio_num_t)33)

#define I2S_BUF_SIZE   4096  // bytes per I2S write chunk
#define PREBUFFER_SIZE 8192  // bytes to buffer before starting playback
// ─────────────────────────────────────────────────────────────────────────────

static i2s_chan_handle_t tx_handle = NULL;
static uint8_t stream_buf[I2S_BUF_SIZE];
static uint8_t prebuf[PREBUFFER_SIZE];

// --- I2S ---

static void i2s_setup(uint32_t sample_rate, uint8_t channels, uint8_t bits) {
    if (tx_handle) {
        i2s_channel_disable(tx_handle);
        i2s_del_channel(tx_handle);
        tx_handle = NULL;
    }

    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_AUTO, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num  = 8;
    chan_cfg.dma_frame_num = 512;
    chan_cfg.auto_clear    = true;
    i2s_new_channel(&chan_cfg, &tx_handle, NULL);

    i2s_data_bit_width_t bw = (bits == 16) ? I2S_DATA_BIT_WIDTH_16BIT : I2S_DATA_BIT_WIDTH_16BIT;
    i2s_slot_mode_t mode    = (channels == 1) ? I2S_SLOT_MODE_MONO : I2S_SLOT_MODE_STEREO;

    i2s_std_config_t std_cfg = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(sample_rate),
        .slot_cfg = I2S_STD_MSB_SLOT_DEFAULT_CONFIG(bw, mode),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = PIN_BCLK,
            .ws   = PIN_LRC,
            .dout = PIN_DIN,
            .din  = I2S_GPIO_UNUSED,
            .invert_flags = { false, false, false },
        },
    };
    i2s_channel_init_std_mode(tx_handle, &std_cfg);
    i2s_channel_enable(tx_handle);
    Serial.printf("I2S: %u Hz, %u ch, %u bit\n", sample_rate, channels, bits);
}

// --- Volume ---

// Halve every 16-bit sample in a buffer (6 dB attenuation)
static void attenuate_half(uint8_t* buf, size_t len) {
    int16_t* samples = (int16_t*)buf;
    size_t count = len / 2;
    for (size_t i = 0; i < count; i++)
        samples[i] >>= 1;
}

// --- WAV streaming ---

// Read exactly n bytes from stream into dst. Returns false on timeout/error.
static bool read_bytes(WiFiClient& stream, uint8_t* dst, size_t n) {
    size_t got = 0;
    uint32_t deadline = millis() + 5000;
    while (got < n && millis() < deadline) {
        if (stream.available()) {
            dst[got++] = stream.read();
        }
    }
    return got == n;
}

static uint16_t read_u16le(uint8_t* b) { return b[0] | (b[1] << 8); }
static uint32_t read_u32le(uint8_t* b) { return b[0]|(b[1]<<8)|(b[2]<<16)|(b[3]<<24); }

// Parse WAV header and configure I2S, leave stream positioned at PCM data.
// Returns number of PCM data bytes, or 0 on error.
static uint32_t parse_wav_and_init_i2s(WiFiClient& stream) {
    uint8_t hdr[12];
    if (!read_bytes(stream, hdr, 12)) { Serial.println("WAV: header read fail"); return 0; }
    if (memcmp(hdr, "RIFF", 4) || memcmp(hdr+8, "WAVE", 4)) {
        Serial.println("WAV: not a RIFF/WAVE file");
        return 0;
    }

    uint32_t sample_rate = 22050;
    uint16_t channels = 1, bits = 16;
    uint32_t data_bytes = 0;

    // Walk sub-chunks until we find fmt and data
    uint8_t chunk_hdr[8];
    while (read_bytes(stream, chunk_hdr, 8)) {
        uint32_t chunk_size = read_u32le(chunk_hdr + 4);
        if (!memcmp(chunk_hdr, "fmt ", 4)) {
            uint8_t fmt[16];
            uint32_t to_read = min((uint32_t)16, chunk_size);
            if (!read_bytes(stream, fmt, to_read)) return 0;
            // skip remainder if chunk > 16
            for (uint32_t i = to_read; i < chunk_size; i++) {
                uint8_t b; read_bytes(stream, &b, 1);
            }
            channels    = read_u16le(fmt + 2);
            sample_rate = read_u32le(fmt + 4);
            bits        = read_u16le(fmt + 14);
            Serial.printf("WAV fmt: %u Hz, %u ch, %u bit\n", sample_rate, channels, bits);
            i2s_setup(sample_rate, channels, bits);
        } else if (!memcmp(chunk_hdr, "data", 4)) {
            data_bytes = chunk_size;
            break;  // PCM data follows immediately
        } else {
            // skip unknown chunk
            for (uint32_t i = 0; i < chunk_size; i++) {
                uint8_t b; read_bytes(stream, &b, 1);
            }
        }
    }

    if (!data_bytes) Serial.println("WAV: no data chunk");
    return data_bytes;
}

// Stream PCM from http client to I2S
static void stream_audio(const String& url) {
    Serial.printf("Audio: %s\n", url.c_str());

    HTTPClient http;
    http.begin(url);
    http.setTimeout(10000);
    int code = http.GET();
    if (code != HTTP_CODE_OK) {
        Serial.printf("HTTP %d\n", code);
        http.end();
        return;
    }

    WiFiClient* stream = http.getStreamPtr();
    uint32_t data_bytes = parse_wav_and_init_i2s(*stream);
    if (!data_bytes) { http.end(); return; }

    Serial.printf("Streaming %u bytes of PCM...\n", data_bytes);

    // Pre-buffer before enabling amp to avoid startup glitch
    uint32_t remaining = data_bytes;
    size_t pre = 0;
    uint32_t deadline = millis() + 5000;
    while (pre < PREBUFFER_SIZE && pre < remaining && millis() < deadline) {
        if (stream->available()) prebuf[pre++] = stream->read();
    }
    Serial.printf("Pre-buffered %u bytes, starting playback\n", pre);

    digitalWrite(PIN_AMP_SD, HIGH);

    // Write pre-buffer
    size_t written;
    attenuate_half(prebuf, pre);
    i2s_channel_write(tx_handle, prebuf, pre, &written, portMAX_DELAY);
    remaining -= pre;

    // Stream remainder in chunks
    while (remaining > 0) {
        size_t n = stream->readBytes(stream_buf,
                                     min((uint32_t)I2S_BUF_SIZE, remaining));
        if (!n) {
            // Brief wait for more TCP data
            delay(5);
            n = stream->readBytes(stream_buf,
                                  min((uint32_t)I2S_BUF_SIZE, remaining));
            if (!n) break;
        }
        attenuate_half(stream_buf, n);
        i2s_channel_write(tx_handle, stream_buf, n, &written, portMAX_DELAY);
        remaining -= n;
    }

    delay(300);  // flush DMA tail
    digitalWrite(PIN_AMP_SD, LOW);
    http.end();
    Serial.println("Audio done.");
}

// --- Main ---

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("=== QuizMaster audio test (ESP32 DevKitV1) ===");

    pinMode(PIN_AMP_SD, OUTPUT);
    digitalWrite(PIN_AMP_SD, LOW);

    // Default I2S at 22050 Hz (will be reconfigured from WAV header)
    i2s_setup(22050, 1, 16);

    // Connect WiFi
    Serial.printf("WiFi: connecting to %s\n", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500); Serial.print(".");
    }
    Serial.printf("\nIP: %s\n", WiFi.localIP().toString().c_str());

    for (int q = 1; q <= 3; q++) {
        Serial.printf("\n=== Question %d/3 ===\n", q);
        HTTPClient http;
        http.begin(SERVICE_BASE "/api/quiz");
        http.setTimeout(15000);
        int code = http.GET();
        if (code != HTTP_CODE_OK) {
            Serial.printf("Quiz API HTTP %d\n", code);
            http.end();
            continue;
        }

        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, http.getString());
        http.end();
        if (err) { Serial.printf("JSON error: %s\n", err.c_str()); continue; }

        String question       = doc["question_text"].as<String>();
        String answer         = doc["answer_text"].as<String>();
        String question_audio = doc["question_audio_url"].as<String>();
        String answer_audio   = doc["answer_audio_url"].as<String>();

        Serial.printf("Q: %s\nA: %s\n", question.c_str(), answer.c_str());

        stream_audio(question_audio);
        delay(2000);
        stream_audio(answer_audio);
        delay(3000);  // pause before next question
    }

    Serial.println("\nAll done. Reset to replay.");
}

void loop() {
    delay(10000);
}
