"""Tests for ResearchOS widgets registry (koi-structure discovery)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from koi.adapters.project_mount import ProjectMount
from koi.widgets.base.manifest import parse_widget_dir
from koi.widgets.base.registry import (
    enabled_widget_keys,
    list_widgets,
    resolve_widget_asset,
    set_widget_enabled,
)


def _write_widget(root: Path, widget_id: str = "demo-ring") -> Path:
    wdir = root / "widgets" / widget_id
    wdir.mkdir(parents=True)
    (wdir / "manifest.yaml").write_text(
        "\n".join(
            [
                f"id: {widget_id}",
                "title: Demo",
                "summary: test widget",
                "visibility: private",
                "surfaces: [web]",
                "default_enabled: true",
                "entry:",
                "  web: web/widget.js",
                "",
            ]
        ),
        encoding="utf-8",
    )
    web = wdir / "web"
    web.mkdir()
    (web / "widget.js").write_text("export async function mount() {}\n", encoding="utf-8")
    (web / "widget.css").write_text(".x{}\n", encoding="utf-8")
    return wdir


class WidgetKoiStructureTest(unittest.TestCase):
    def test_parse_ok(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            wdir = _write_widget(Path(td))
            m = parse_widget_dir(wdir, source="koi-structure", project_id="demo")
            self.assertTrue(m.ok, m.errors)
            self.assertEqual(m.key, "demo/demo-ring")

    def test_list_from_mount(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            koi = Path(td) / "koi-structure"
            _write_widget(koi)
            mount = ProjectMount(
                project_id="demo",
                repo_root=Path(td),
                koi_root=koi,
                code_root=Path(td),
                programs=(),
            )
            with patch("koi.widgets.base.registry.list_mounts", return_value=[mount]):
                with patch("koi.widgets.base.registry.STATE_PATH", Path(td) / "widgets.json"):
                    rows = list_widgets(ok_only=True)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].key, "demo/demo-ring")
            self.assertTrue(rows[0].enabled)

    def test_enable_disable_by_key(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            koi = Path(td) / "koi-structure"
            _write_widget(koi)
            mount = ProjectMount(
                project_id="demo",
                repo_root=Path(td),
                koi_root=koi,
                code_root=Path(td),
                programs=(),
            )
            state = Path(td) / "widgets.json"
            with patch("koi.widgets.base.registry.list_mounts", return_value=[mount]):
                with patch("koi.widgets.base.registry.STATE_PATH", state):
                    set_widget_enabled("demo/demo-ring", False)
                    self.assertNotIn("demo/demo-ring", enabled_widget_keys())
                    data = json.loads(state.read_text(encoding="utf-8"))
                    self.assertFalse(data["enabled"]["demo/demo-ring"])
                    set_widget_enabled("demo-ring", True)
                    self.assertIn("demo/demo-ring", enabled_widget_keys())

    def test_resolve_asset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            koi = Path(td) / "koi-structure"
            _write_widget(koi)
            mount = ProjectMount(
                project_id="demo",
                repo_root=Path(td),
                koi_root=koi,
                code_root=Path(td),
                programs=(),
            )
            with patch("koi.widgets.base.registry.list_mounts", return_value=[mount]):
                path = resolve_widget_asset("demo", "demo-ring", "web/widget.js")
            self.assertIsNotNone(path)
            assert path is not None
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()


def test_shared_widget_asset_is_served_after_package_move():
    """The public widget URL must survive moving its backing package."""
    from http.server import ThreadingHTTPServer
    from threading import Thread
    from urllib.request import urlopen

    from api.web_proxy import KoiWebHandler

    server = ThreadingHTTPServer(("127.0.0.1", 0), KoiWebHandler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/widgets/_base/floating.js") as response:
            assert response.status == 200
            assert response.read() == (
                Path(__file__).resolve().parents[1] / "koi/widgets/base/web/floating.js"
            ).read_bytes()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
