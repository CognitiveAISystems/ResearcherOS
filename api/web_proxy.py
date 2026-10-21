#!/usr/bin/env python3
"""Serve ``web/`` and proxy ``/api/*`` to the KOI FastAPI server.

Also serves ResearchOS widgets:
  /widgets/_base/...                      → koi/widgets/base/web/...
  /widgets/<project_id>/<id>/...          → tree/.../koi-structure/widgets/<id>/...
"""

from __future__ import annotations

import argparse
import http.client
import mimetypes
import select
import socket
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ENGINE_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ENGINE_ROOT / "web"
WIDGETS_ROOT = ENGINE_ROOT / "koi" / "widgets"
API_PREFIX = "/api"
WIDGETS_PREFIX = "/widgets/"


class KoiWebHandler(SimpleHTTPRequestHandler):
    api_host = "127.0.0.1"
    api_port = 8010

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT.resolve()), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _upstream_path(self) -> str:
        path = self.path
        if path.startswith(API_PREFIX):
            path = path[len(API_PREFIX) :] or "/"
        url = urlparse(path)
        upstream_path = url.path
        if url.query:
            upstream_path = f"{upstream_path}?{url.query}"
        return upstream_path

    def _is_websocket(self) -> bool:
        upgrade = (self.headers.get("Upgrade") or "").lower()
        connection = (self.headers.get("Connection") or "").lower()
        return upgrade == "websocket" and "upgrade" in connection

    def _proxy_websocket(self) -> None:
        upstream_path = self._upstream_path()
        try:
            remote = socket.create_connection((self.api_host, self.api_port), timeout=15)
        except OSError as exc:
            msg = f'{{"detail":"API unavailable on {self.api_host}:{self.api_port}: {exc}"}}'
            body_bytes = msg.encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
            return

        request = [f"{self.command} {upstream_path} HTTP/1.1", f"Host: {self.api_host}:{self.api_port}"]
        for key, value in self.headers.items():
            if key.lower() == "host":
                continue
            request.append(f"{key}: {value}")
        request.append("")
        request.append("")
        remote.sendall("\r\n".join(request).encode("latin-1"))

        client = self.connection
        sockets = [client, remote]
        try:
            while True:
                readable, _, errored = select.select(sockets, [], sockets, 60)
                if errored:
                    break
                if not readable:
                    continue
                for sock in readable:
                    other = remote if sock is client else client
                    data = sock.recv(65536)
                    if not data:
                        return
                    other.sendall(data)
        except OSError:
            return
        finally:
            try:
                remote.close()
            except OSError:
                pass

    def _proxy_api(self) -> None:
        if self._is_websocket():
            self._proxy_websocket()
            return
        upstream_path = self._upstream_path()

        content_length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(content_length) if content_length else None

        headers = {}
        for key, value in self.headers.items():
            lower = key.lower()
            if lower in {"host", "connection", "content-length"}:
                continue
            headers[key] = value

        conn = http.client.HTTPConnection(self.api_host, self.api_port, timeout=120)
        try:
            conn.request(self.command, upstream_path, body=body, headers=headers)
            resp = conn.getresponse()
            payload = resp.read()
            self.send_response(resp.status)
            for key, value in resp.getheaders():
                lower = key.lower()
                if lower in {"transfer-encoding", "connection"}:
                    continue
                self.send_header(key, value)
            self.end_headers()
            if payload:
                self.wfile.write(payload)
        except OSError as exc:
            msg = f'{{"detail":"API unavailable on {self.api_host}:{self.api_port}: {exc}"}}'
            body_bytes = msg.encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
        finally:
            conn.close()

    def _widget_file(self) -> Path | None:
        url = urlparse(self.path)
        raw = unquote(url.path or "")
        if not raw.startswith(WIDGETS_PREFIX):
            return None
        rel = raw[len(WIDGETS_PREFIX) :]
        if not rel or ".." in rel.split("/"):
            return None

        # Shared base assets: /widgets/_base/floating.js → koi/widgets/base/web/floating.js
        if rel.startswith("_base/"):
            candidate = (WIDGETS_ROOT / "base" / "web" / rel[len("_base/") :]).resolve()
            base_web = (WIDGETS_ROOT / "base" / "web").resolve()
            try:
                candidate.relative_to(base_web)
            except ValueError:
                return None
            return candidate if candidate.is_file() else None

        parts = [p for p in rel.split("/") if p]
        if len(parts) < 2:
            return None
        project_or_installed, widget_id, *rest = parts
        if not widget_id or widget_id.startswith("."):
            return None

        # Lazy import so static server starts even if mounts are cold
        from koi.widgets.base.registry import resolve_widget_asset

        return resolve_widget_asset(project_or_installed, widget_id, "/".join(rest))

    def _serve_widget(self) -> bool:
        path = self._widget_file()
        if path is None:
            if urlparse(self.path).path.startswith(WIDGETS_PREFIX):
                self.send_error(404, "Widget asset not found")
                return True
            return False
        try:
            data = path.read_bytes()
        except OSError:
            self.send_error(404, "Widget asset not found")
            return True
        ctype, _ = mimetypes.guess_type(str(path))
        if path.suffix == ".js":
            ctype = "text/javascript; charset=utf-8"
        elif path.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif not ctype:
            ctype = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
        return True

    def do_GET(self) -> None:
        if self.path == API_PREFIX or self.path.startswith(f"{API_PREFIX}/"):
            self._proxy_api()
            return
        if self._serve_widget():
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if self.path == API_PREFIX or self.path.startswith(f"{API_PREFIX}/"):
            self._proxy_api()
            return
        if self._serve_widget():
            return
        super().do_HEAD()

    def do_OPTIONS(self) -> None:
        if self.path == API_PREFIX or self.path.startswith(f"{API_PREFIX}/"):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, Authorization",
            )
            self.end_headers()
            return
        super().do_OPTIONS()

    def do_POST(self) -> None:
        if self.path == API_PREFIX or self.path.startswith(f"{API_PREFIX}/"):
            self._proxy_api()
            return
        self.send_error(405)

    def do_PUT(self) -> None:
        if self.path == API_PREFIX or self.path.startswith(f"{API_PREFIX}/"):
            self._proxy_api()
            return
        self.send_error(405)

    def do_PATCH(self) -> None:
        if self.path == API_PREFIX or self.path.startswith(f"{API_PREFIX}/"):
            self._proxy_api()
            return
        self.send_error(405)

    def do_DELETE(self) -> None:
        if self.path == API_PREFIX or self.path.startswith(f"{API_PREFIX}/"):
            self._proxy_api()
            return
        self.send_error(405)


def main() -> None:
    parser = argparse.ArgumentParser(description="KOI web static server + /api proxy")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--api-host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8010)
    args = parser.parse_args()

    KoiWebHandler.api_host = args.api_host
    KoiWebHandler.api_port = args.api_port

    server = ThreadingHTTPServer((args.host, args.port), KoiWebHandler)
    sys.stderr.write(
        f"KOI web on http://{args.host}:{args.port}/ (API proxy → {args.api_host}:{args.api_port})\n"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
