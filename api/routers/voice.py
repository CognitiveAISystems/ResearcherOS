"""Local speech-to-text for chat composers."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

router = APIRouter(prefix="/voice", tags=["voice"])
_model_lock = Lock()
_model = None
MAX_AUDIO_BYTES = 20 * 1024 * 1024


def _transcribe(path: Path) -> str:
    global _model
    # Hold the lock during inference too: the model is shared across requests.
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel

            cache = Path(os.environ.get("KOI_DATA_DIR", Path.home() / ".researchos")) / "models" / "whisper"
            cache.mkdir(parents=True, exist_ok=True)
            _model = WhisperModel("base", device="cpu", compute_type="int8", download_root=str(cache))
        segments, _ = _model.transcribe(str(path), language="ru", beam_size=3, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()


@router.post("/transcribe")
async def transcribe_voice(audio: UploadFile = File(...)) -> dict[str, str]:
    if audio.content_type not in {"audio/webm", "audio/ogg", "audio/mp4", "audio/wav", "audio/x-wav"}:
        raise HTTPException(415, "Неподдерживаемый формат записи")
    suffix = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".mp4", "audio/wav": ".wav", "audio/x-wav": ".wav"}[audio.content_type]
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="researchos-voice-", suffix=suffix, delete=False) as target:
            path = Path(target.name)
            size = 0
            while chunk := await audio.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_AUDIO_BYTES:
                    raise HTTPException(413, "Запись слишком длинная")
                target.write(chunk)
        if size == 0:
            raise HTTPException(400, "Запись пуста")
        try:
            text = await run_in_threadpool(_transcribe, path)
        except Exception as exc:
            raise HTTPException(503, f"Не удалось распознать речь локально: {exc}") from exc
        return {"text": text}
    finally:
        await audio.close()
        if path is not None:
            path.unlink(missing_ok=True)
