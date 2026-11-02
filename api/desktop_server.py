"""Electron-facing entry point for the bundled ResearcherOS desktop server."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading

from koi.desktop.server import DesktopServer


def main() -> int:
    parser = argparse.ArgumentParser(description="ResearcherOS desktop server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--paper-edit-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--research-tools", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--research-runtime", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.research_tools:
        from koi.agent_chat.research_tools import main as tools_main
        tools_main()
        return 0
    if args.research_runtime:
        from koi.agent_chat.research_runtime import main as runtime_main
        runtime_main()
        return 0
    if args.paper_edit_worker:
        from koi.paper.edit_worker import main as edit_worker_main
        edit_worker_main()
        return 0

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
        print(f"ResearcherOS startup failed: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
