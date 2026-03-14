from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()


@router.get("/audio/{filename}")
async def get_audio(request: Request, filename: str):
    # Sanitize filename to prevent path traversal
    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        return JSONResponse(status_code=400, content={"error": "Invalid filename"})

    audio_dir: Path = request.app.state.audio_dir
    file_path = audio_dir / safe_name

    if not file_path.exists():
        return JSONResponse(status_code=404, content={"error": "Audio file not found"})

    return FileResponse(
        path=str(file_path),
        media_type="audio/wav",
        filename=safe_name,
    )
