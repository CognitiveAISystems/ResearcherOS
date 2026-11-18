"""Saved legacy interface settings cannot replace Quick Navigation assets."""
import hashlib
import json

import pytest

from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer


from api.web_proxy import KoiWebHandler
from koi.adapters import settings_store

ROOT = Path(__file__).resolve().parents[1]
LIGHT = ROOT / "web/variants/light"
SOURCE = json.loads((LIGHT / "source.json").read_text())


@pytest.mark.parametrize("name,expected", SOURCE["current_files"].items())
def test_maintained_light_assets_match_manifest(name, expected):
    assert hashlib.sha256((LIGHT / name).read_bytes()).hexdigest() == expected


def test_legacy_selection_serves_quick_navigation_without_stale_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_store, "ENV_PATH", tmp_path / "settings.env")
    monkeypatch.setenv("KOI_UI_VARIANT", "light")
    server = ThreadingHTTPServer(("127.0.0.1", 0), KoiWebHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        for path, source in (("/", "index.html"), ("/app.js", "app.js"), ("/styles.css", "styles.css"), ("/node-tree-help.js", "node-tree-help.js")):
            with urlopen(base + path) as response:
                assert response.read() == (ROOT / "web" / source).read_bytes()
                assert response.headers["Cache-Control"] == "no-store"
        # Onboarding uses one shared implementation in both modes.
        with urlopen(base + "/desktop-onboarding.js") as response:
            assert response.read() == (ROOT / "web/desktop-onboarding.js").read_bytes()
        monkeypatch.setenv("KOI_UI_VARIANT", "chats")
        request = Request(base + "/app.js", headers={"If-Modified-Since": "Fri, 01 Jan 2100 00:00:00 GMT"})
        with urlopen(request) as response:
            assert response.status == 200
            assert response.read() == (ROOT / "web/app.js").read_bytes()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
