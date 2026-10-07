"""Electron-facing entry point for the bundled ResearchOS desktop server."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading

from koi.desktop.server import DesktopServer


def main() -> int:
    parser = argparse.ArgumentParser(description="ResearchOS desktop server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    stopped = threading.Event()
    server = DesktopServer(host=args.host, port=args.port)

    def request_stop(_signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        url = server.start()
        print(json.dumps({"url": url}), flush=True)
        stopped.wait()
        return 0
    except Exception as exc:
        print(f"ResearchOS startup failed: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
