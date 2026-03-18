// Speaker test for ESP32 DevKitV1 + MAX98357A
// Generates a 440 Hz sine-wave test tone to verify I2S audio output and amplifier.

#include <math.h>
#include "driver/i2s_std.h"

// ESP32 DevKitV1 — use GPIO numbers directly (no D-pin mapping needed)
#define PIN_BCLK    ((gpio_num_t)25)
#define PIN_LRC     ((gpio_num_t)26)
#define PIN_DIN     ((gpio_num_t)33)
#define PIN_AMP_SD  32

#define SAMPLE_RATE 44100
#define TONE_HZ     440
#define AMPLITUDE   8000

// One full period of the sine wave, duplicated to stereo (L+R)
#define PERIOD_FRAMES (SAMPLE_RATE / TONE_HZ)
static int16_t tone_buf[PERIOD_FRAMES * 2];

static i2s_chan_handle_t tx_handle = NULL;

static void i2s_init() {
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_AUTO, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num  = 8;
    chan_cfg.dma_frame_num = 512;
    chan_cfg.auto_clear    = true;
    i2s_new_channel(&chan_cfg, &tx_handle, NULL);

    i2s_std_config_t std_cfg = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_MSB_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
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
}

static void amp_on()  { digitalWrite(PIN_AMP_SD, HIGH); delayMicroseconds(100); }
static void amp_off() { digitalWrite(PIN_AMP_SD, LOW); }

static void precompute_sine_wave() {
    for (int i = 0; i < PERIOD_FRAMES; i++) {
        int16_t sample = (int16_t)(AMPLITUDE * sinf(2.0f * M_PI * i / PERIOD_FRAMES));
        tone_buf[i * 2]     = sample;  // L
        tone_buf[i * 2 + 1] = sample;  // R
    }
}

static void play_tone(int duration_ms) {
    int total_frames = (int64_t)SAMPLE_RATE * duration_ms / 1000;
    int written = 0;
    size_t bytes_written;
    while (written < total_frames) {
        int chunk = (total_frames - written < PERIOD_FRAMES)
                  ? total_frames - written : PERIOD_FRAMES;
        i2s_channel_write(tx_handle, tone_buf, chunk * 2 * sizeof(int16_t),
                          &bytes_written, portMAX_DELAY);
        written += chunk;
    }
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("=== Speaker test (ESP32 DevKitV1) ===");
    Serial.printf("Pin mapping: BCLK=GPIO%d  LRC=GPIO%d  DIN=GPIO%d  SD=GPIO%d\n",
                  (int)PIN_BCLK, (int)PIN_LRC, (int)PIN_DIN, PIN_AMP_SD);

    pinMode(PIN_AMP_SD, OUTPUT);
    amp_off();

    precompute_sine_wave();
    i2s_init();
    Serial.println("Ready — playing 440 Hz sine wave (1s on, 0.5s off).");
}

void loop() {
    Serial.println("TONE ON");
    amp_on();
    play_tone(1000);

    Serial.println("TONE OFF");
    amp_off();
    delay(500);
}
