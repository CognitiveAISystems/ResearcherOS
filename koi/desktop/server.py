"""Run the ResearchOS API and web UI in one parent process.

The desktop shell owns this process. Both listeners bind to loopback on
ephemeral ports, so parallel installs and unrelated local services do not
depend on fixed ports. Only the web listener is exposed to the shell; it
proxies ``/api`` to the private API listener.
"""

from __future__ import annotations

import socket
import threading
import time
from http.server import ThreadingHTTPServer
from typing import Any

import uvicorn


class DesktopServer:
    """In-process API and UI servers with explicit, graceful lifecycle."""

    def __init__(self, *, host: str = "127.0.0.1", port: int = 0) -> None:
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("DesktopServer may only bind to loopback")
        if not 0 <= port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        self.host = "127.0.0.1" if host == "localhost" else host
        self.requested_port = port
        self.api_server: uvicorn.Server | None = None
        self.web_server: ThreadingHTTPServer | None = None
        self._api_thread: threading.Thread | None = None
        self._web_thread: threading.Thread | None = None
        self._api_socket: socket.socket | None = None
        self._started = False

    @property
    def url(self) -> str:
        if not self._started or self.web_server is None:
            raise RuntimeError("desktop server has not started")
        host, port = self.web_server.server_address[:2]
        return f"http://{host}:{port}/"

    def start(self, *, timeout: float = 20.0) -> str:
        """Start API and UI, returning the UI URL once the API is healthy."""
        if self._started:
            return self.url

        # Import only after the caller's environment is in place. Importing
        # api.main also initializes workspace adapters.
        try:
            from api.main import app
            from api.web_proxy import KoiWebHandler

            api_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            api_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            api_socket.bind((self.host, 0))
            api_socket.listen(128)
            api_socket.setblocking(False)
            self._api_socket = api_socket
            api_host, api_port = api_socket.getsockname()[:2]

            config = uvicorn.Config(
                app,
                host=api_host,
                port=api_port,
                log_config=None,
                access_log=False,
            )
            self.api_server = uvicorn.Server(config)
            self._api_thread = threading.Thread(
                target=self.api_server.run,
                kwargs={"sockets": [api_socket]},
                name="researchos-api",
                daemon=True,
            )
            self._api_thread.start()

            KoiWebHandler.api_host = api_host
            KoiWebHandler.api_port = api_port
            self.web_server = ThreadingHTTPServer(
                (self.host, self.requested_port), KoiWebHandler
            )
            self.web_server.daemon_threads = True
            self._web_thread = threading.Thread(
                target=self.web_server.serve_forever,
                name="researchos-web",
                daemon=True,
            )
            self._web_thread.start()

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self.api_server.started:
                    self._started = True
                    return self.url
                if self._api_thread is not None and not self._api_thread.is_alive():
                    break
                time.sleep(0.025)
            raise RuntimeError("ResearchOS API did not become ready before timeout")
        except BaseException:
            self.stop()
            raise

    def stop(self, *, timeout: float = 10.0) -> None:
        """Stop listeners and wait for their request threads to finish."""
        if self.web_server is not None:
            self.web_server.shutdown()
            self.web_server.server_close()
            self.web_server = None
        if self.api_server is not None:
            self.api_server.should_exit = True
        if self._web_thread is not None:
            self._web_thread.join(timeout=timeout)
            self._web_thread = None
        if self._api_thread is not None:
            self._api_thread.join(timeout=timeout)
            self._api_thread = None
        if self._api_socket is not None:
            try:
                self._api_socket.close()
            except OSError:
                pass
            self._api_socket = None
        self.api_server = None
        self._started = False

    def __enter__(self) -> "DesktopServer":
        self.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.stop()
