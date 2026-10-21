from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app
from api.routers import voice


def test_voice_transcription_inserts_text_without_persisting_audio(monkeypatch, tmp_path):
    seen = []

    def fake_transcribe(path):
        seen.append(path)
        assert path.read_bytes() == b"audio-data"
        return "Проверяем гипотезу"

    monkeypatch.setattr(voice, "_transcribe", fake_transcribe)
    with TestClient(app) as client:
        result = client.post("/voice/transcribe", files={"audio": ("voice.webm", b"audio-data", "audio/webm")})
    assert result.status_code == 200
    assert result.json() == {"text": "Проверяем гипотезу"}
    assert seen and not seen[0].exists()


def test_voice_rejects_unsupported_format():
    with TestClient(app) as client:
        result = client.post("/voice/transcribe", files={"audio": ("voice.txt", b"text", "text/plain")})
    assert result.status_code == 415
