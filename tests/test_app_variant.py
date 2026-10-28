"""UI variants share runtime settings and never change the agent backend."""
from fastapi.testclient import TestClient
import pytest

from api.main import app
from koi.adapters import settings_store
from koi.agent_chat.settings import settings_snapshot


@pytest.mark.parametrize("variant", ["chats", "light"])
def test_variant_persists_across_settings_reload(monkeypatch, tmp_path, variant):
    monkeypatch.setattr(settings_store, "ENV_PATH", tmp_path / "settings.env")
    monkeypatch.setenv("KOI_UI_VARIANT", "chats")
    monkeypatch.setenv("KOI_AGENT_CHAT_MODE", "local")
    client = TestClient(app)

    response = client.put("/settings/agent-chat", json={"ui_variant": variant})
    assert response.status_code == 200
    assert response.json()["ui_variant"] == variant
    assert response.json()["agent_chat_mode"] == "local"
    monkeypatch.delenv("KOI_UI_VARIANT", raising=False)
    assert client.get("/settings").json()["ui_variant"] == variant


def test_invalid_variant_cannot_change_existing_settings(monkeypatch, tmp_path):
    destination = tmp_path / "settings.env"
    monkeypatch.setattr(settings_store, "ENV_PATH", destination)
    monkeypatch.setenv("KOI_UI_VARIANT", "light")
    response = TestClient(app).put("/settings/agent-chat", json={"ui_variant": "other"})
    assert response.status_code == 422
    assert settings_snapshot()["ui_variant"] == "light"
    assert not destination.exists()


def test_unknown_saved_variant_uses_existing_chat_interface(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_store, "ENV_PATH", tmp_path / "settings.env")
    monkeypatch.setenv("KOI_UI_VARIANT", "old-experiment")
    assert settings_snapshot()["ui_variant"] == "chats"
