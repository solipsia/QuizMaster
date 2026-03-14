from __future__ import annotations

import asyncio
import io
import json
import wave
from pathlib import Path

from .models import TTSConfig


class PiperTTSClient:
    """
    Talks to rhasspy/wyoming-piper via the Wyoming TCP protocol.

    Config piper_url format:  host:port  (e.g. "piper:10300")
    Wyoming protocol: newline-delimited JSON headers, optional raw byte payload.
    """

    def __init__(self, config: TTSConfig):
        self._config = config

    def _parse_endpoint(self) -> tuple[str, int]:
        url = self._config.piper_url
        # Support "host:port" or "tcp://host:port"
        url = url.removeprefix("tcp://")
        if ":" in url:
            host, port_str = url.rsplit(":", 1)
            return host, int(port_str)
        return url, 10300

    async def synthesize(self, text: str, output_path: Path) -> int:
        """Synthesize text via Wyoming protocol. Returns audio duration in ms."""
        host, port = self._parse_endpoint()

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=10.0
        )
        try:
            return await self._do_synthesize(reader, writer, text, output_path)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _do_synthesize(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        text: str,
        output_path: Path,
    ) -> int:
        # Send synthesize request
        request = {
            "type": "synthesize",
            "data": {
                "text": text,
                "voice": {
                    "name": self._config.voice_model or "en_US-lessac-medium",
                    "language": "en_US",
                    "speaker": None,
                },
            },
            "data_length": 0,
        }
        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()

        # Collect PCM chunks
        pcm_chunks: list[bytes] = []
        audio_params: dict = {}

        while True:
            header_line = await asyncio.wait_for(reader.readline(), timeout=60.0)
            if not header_line:
                break
            try:
                header = json.loads(header_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise RuntimeError(
                    f"Piper returned unexpected data (not Wyoming JSON): "
                    f"{header_line[:40]!r} — {e}. "
                    f"Check Piper container logs; it may still be downloading the voice model."
                ) from e
            data_length = header.get("data_length", 0)
            data = b""
            if data_length > 0:
                data = await asyncio.wait_for(
                    reader.readexactly(data_length), timeout=60.0
                )

            msg_type = header.get("type", "")
            if msg_type == "audio-start":
                audio_params = header.get("data", {})
            elif msg_type == "audio-chunk":
                pcm_chunks.append(data)
            elif msg_type == "audio-stop":
                break
            elif msg_type == "error":
                err = header.get("data", {}).get("text", "unknown error")
                raise RuntimeError(f"Piper error: {err}")

        # Assemble WAV
        pcm_data = b"".join(pcm_chunks)
        rate = audio_params.get("rate", self._config.sample_rate)
        width = audio_params.get("width", 2)
        channels = audio_params.get("channels", 1)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(width)
            wf.setframerate(rate)
            wf.writeframes(pcm_data)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(buf.getvalue())

        # Duration from frame count
        if rate > 0 and width > 0 and channels > 0:
            num_frames = len(pcm_data) // (width * channels)
            return int(num_frames / rate * 1000)
        return 0

    async def health_check(self) -> bool:
        try:
            host, port = self._parse_endpoint()
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=5.0
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False
