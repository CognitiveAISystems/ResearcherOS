import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import projects


def test_canvas_round_trip_and_stale_save(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "require_project", lambda _: None)
    monkeypatch.setattr(projects, "koi_root", lambda project_id: tmp_path / project_id)
    app = FastAPI()
    app.include_router(projects.router)
    client = TestClient(app)
    url = "/projects/demo/canvas"

    empty = client.get(url).json()
    assert empty["scene"] is None
    scene = json.dumps({
        "type": "excalidraw",
        "version": 2,
        "elements": [{"id": "shape", "type": "rectangle"}],
        "appState": {"viewBackgroundColor": "#ffffff"},
        "files": {"image": {"dataURL": "data:image/png;base64,AA=="}},
    })
    saved = client.put(url, json={"revision": empty["revision"], "scene": scene})
    assert saved.status_code == 200
    assert (tmp_path / "demo" / "sketch.excalidraw").read_text() == scene
    assert client.get(url).json() == {"scene": scene, **saved.json()}
    assert client.get("/projects/other/canvas").json() == empty

    stale = client.put(url, json={
        "revision": empty["revision"], "scene": scene.replace("rectangle", "ellipse"),
    })
    assert stale.status_code == 409
    malformed = client.put(url, json={"revision": saved.json()["revision"], "scene": "{}"})
    assert malformed.status_code == 422
    assert client.get(url).json()["scene"] == scene
