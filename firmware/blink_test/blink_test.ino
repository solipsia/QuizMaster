// Blink test for ESP32 DevKitV1 — verifies compile/upload pipeline
// Blinks the onboard LED (GPIO 2) at 1Hz.

#define LED_PIN 2

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("=== Blink test (ESP32 DevKitV1) ===");
    pinMode(LED_PIN, OUTPUT);
}

void loop() {
    digitalWrite(LED_PIN, HIGH);
    Serial.println("LED ON");
    delay(500);

    digitalWrite(LED_PIN, LOW);
    Serial.println("LED OFF");
    delay(500);
}
