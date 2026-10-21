"""Child process for paper edits. The parent applies OS filesystem restrictions."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main():
    from koi.agent_chat.runner import _run_local_agent

    payload = json.load(sys.stdin)
    text, backend = _run_local_agent(
        payload["prompt"], payload["id"], mode=None, force=True,
        cwd=Path.cwd(), timeout=payload["timeout"], cli_agent=payload.get("backend"),
        log_activity=False, externally_sandboxed=True,
    )
    if text is None:
        raise RuntimeError("Локальный агент не завершил задачу")
    print(json.dumps({"answer": text, "backend": backend}, ensure_ascii=False))


if __name__ == "__main__":
    main()
