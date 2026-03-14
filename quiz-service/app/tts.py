from __future__ import annotations

import asyncio
import logging
import os
import wave
from pathlib import Path

import httpx

from .models import TTSConfig

logger = logging.getLogger(__name__)

# Piper voices are hosted on Hugging Face
_VOICES_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"


def _voice_url_prefix(voice_name: str) -> str:
    """Convert 'en_US-lessac-medium' to the HuggingFace path prefix."""
    # en_US-lessac-medium -> en/en_US/lessac/medium
    parts = voice_name.split("-")
    lang_region = parts[0]            # e.g. en_US
    speaker = parts[1] if len(parts) > 1 else "default"
    quality = parts[2] if len(parts) > 2 else "medium"
    lang = lang_region.split("_")[0]  # e.g. en
    return f"{lang}/{lang_region}/{speaker}/{quality}"


async def _download_voice(voice_name: str, models_dir: Path) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    prefix = _voice_url_prefix(voice_name)
    async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
        for suffix in (".onnx", ".onnx.json"):
            dest = models_dir / f"{voice_name}{suffix}"
            if dest.exists():
                continue
            url = f"{_VOICES_BASE}/{prefix}/{voice_name}{suffix}"
            logger.info("Downloading Piper voice: %s", url)
            resp = await client.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            logger.info("Saved %s (%d bytes)", dest.name, len(resp.content))


class PiperTTSClient:
    """
    Runs piper-tts as a local Python library — no separate container needed.
    Voice models are downloaded automatically to /data/models on first use.
    """

    def __init__(self, config: TTSConfig):
        self._config = config
        self._voice = None
        self._loaded_model: str | None = None
        self._models_dir = Path(os.environ.get("PIPER_MODELS_DIR", "/data/models"))

    async def _ensure_voice(self) -> None:
        voice_name = self._config.voice_model
        if self._loaded_model == voice_name and self._voice is not None:
            return

        model_path = self._models_dir / f"{voice_name}.onnx"
        if not model_path.exists():
            await _download_voice(voice_name, self._models_dir)

        from piper import PiperVoice
        loop = asyncio.get_event_loop()
        logger.info("Loading Piper voice: %s", model_path)
        self._voice = await loop.run_in_executor(
            None, PiperVoice.load, str(model_path)
        )
        self._loaded_model = voice_name

    async def synthesize(self, text: str, output_path: Path) -> int:
        """Synthesize text to WAV. Returns audio duration in ms."""
        await self._ensure_voice()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        voice = self._voice

        def _run() -> int:
            with wave.open(str(output_path), "wb") as wav_file:
                voice.synthesize(text, wav_file)
            with wave.open(str(output_path), "rb") as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                return int(frames / rate * 1000) if rate > 0 else 0

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _run)

    async def health_check(self) -> bool:
        try:
            await self._ensure_voice()
            return True
        except Exception:
            return False
