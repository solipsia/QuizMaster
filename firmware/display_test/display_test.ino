// Display + touch test for ESP32 DevKitV1 + ILI9488 + XPT2046
// Shows colour bands on startup, then draws a dot wherever you touch.

#include <SPI.h>
#include <TFT_eSPI.h>

#define TOUCH_IRQ  4

TFT_eSPI tft = TFT_eSPI();

// Touch calibration — run TFT_eSPI Touch_calibrate example to get values
// for your specific display. These are reasonable defaults for a 4" ILI9488.
uint16_t calData[5] = { 300, 3600, 300, 3600, 3 };

static void draw_test_pattern() {
    int w = tft.width();
    int h = tft.height();
    int band = h / 6;

    tft.fillRect(0, 0,        w, band, TFT_RED);
    tft.fillRect(0, band,     w, band, TFT_GREEN);
    tft.fillRect(0, band * 2, w, band, TFT_BLUE);
    tft.fillRect(0, band * 3, w, band, TFT_YELLOW);
    tft.fillRect(0, band * 4, w, band, TFT_CYAN);
    tft.fillRect(0, band * 5, w, h - band * 5, TFT_MAGENTA);

    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.setTextDatum(MC_DATUM);
    tft.setTextSize(1);
    tft.setFreeFont(&FreeSansBold18pt7b);
    tft.drawString("QuizMaster", w / 2, h / 2 - 20);

    tft.setFreeFont(&FreeSans12pt7b);
    tft.drawString("Touch the screen!", w / 2, h / 2 + 20);

    tft.setTextDatum(TL_DATUM);
    tft.setFreeFont(&FreeSans9pt7b);
    tft.setTextColor(TFT_WHITE);
    tft.drawString(String(w) + " x " + String(h), 8, 8);
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("=== Display + touch test (ESP32 DevKitV1) ===");

    pinMode(TOUCH_IRQ, INPUT);

    tft.init();
    tft.setRotation(1);  // landscape, 480x320
    tft.setTouch(calData);

    Serial.printf("Display: %d x %d\n", tft.width(), tft.height());

    draw_test_pattern();
    Serial.println("Ready — touch the screen.");
}

void loop() {
    uint16_t tx, ty;
    if (tft.getTouch(&tx, &ty)) {
        ty = tft.height() - 1 - ty;  // flip Y — touch panel is vertically inverted
        Serial.printf("Touch: x=%d y=%d\n", tx, ty);
        tft.fillCircle(tx, ty, 6, TFT_WHITE);
    }
    delay(20);
}
