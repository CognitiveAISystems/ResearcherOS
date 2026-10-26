"""Discover installed ACP agents without starting or downloading them."""
import json
import os
import shlex
import shutil
from koi.adapters.workspace import get_workspace


def agents():
    # Local executable discovery never downloads code or silently changes transport.
    defaults = {"codex-acp": ["codex-acp"], "claude-acp": ["claude-agent-acp"]}
    try:
        configured = json.loads(os.environ.get("KOI_ACP_AGENTS", "{}"))
    except ValueError:
        configured = {}
    if isinstance(configured, dict):
        defaults.update(configured)
    rows = []
    for name, command in defaults.items():
        args = shlex.split(command) if isinstance(command, str) else command
        if not isinstance(args, list) or not args or not all(isinstance(x, str) for x in args):
            continue
        local = get_workspace().tools_dir / "acp" / "node_modules" / ".bin" / args[0]
        if not shutil.which(args[0]) and local.is_file():
            args = [str(local), *args[1:]]
        rows.append({"id": "acp:" + name, "label": name + " (ACP)",
                     "available": bool(shutil.which(args[0])), "command": args})
    return rows
