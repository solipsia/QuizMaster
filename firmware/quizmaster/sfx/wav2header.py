#!/usr/bin/env python3
"""Convert a WAV file to a PROGMEM C header for ESP32.

Usage: python wav2header.py input.wav [output.h]

The WAV must be 22050 Hz, 16-bit, mono (matching the I2S config).
If output path is omitted, writes sfx_<name>.h alongside the input.
"""
import wave, sys, os

def convert(wav_path, out_path=None):
    name = os.path.splitext(os.path.basename(wav_path))[0]
    sym = f"SFX_{name.upper()}"

    if out_path is None:
        out_path = os.path.join(os.path.dirname(wav_path), f"sfx_{name}.h")

    wav = wave.open(wav_path, "rb")
    assert wav.getnchannels() == 1, f"Must be mono, got {wav.getnchannels()} channels"
    assert wav.getsampwidth() == 2, f"Must be 16-bit, got {wav.getsampwidth()*8}-bit"
    assert wav.getframerate() == 22050, f"Must be 22050 Hz, got {wav.getframerate()} Hz"

    frames = wav.readframes(wav.getnframes())
    wav.close()
    n = len(frames)

    with open(out_path, "w") as f:
        f.write(f"// Auto-generated from {os.path.basename(wav_path)} — do not edit\n")
        f.write("// 22050 Hz, 16-bit, mono PCM\n")
        f.write("#pragma once\n")
        f.write("#include <pgmspace.h>\n\n")
        f.write(f"static const size_t {sym}_LEN = {n};\n")
        f.write(f"static const uint8_t {sym}[] PROGMEM = {{\n")
        for i in range(0, n, 16):
            chunk = frames[i:i+16]
            hex_vals = ", ".join(f"0x{b:02X}" for b in chunk)
            comma = "," if i + 16 < n else ""
            f.write(f"    {hex_vals}{comma}\n")
        f.write("};\n")

    print(f"{wav_path} -> {out_path} ({n} bytes, {n/44100:.2f}s)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
