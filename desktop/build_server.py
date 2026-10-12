"""Build the desktop server on the host OS (PyInstaller cannot cross-compile)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    env_python = os.environ.get("RESEARCHOS_BUILD_PYTHON")
    python = Path(env_python) if env_python else Path(sys.executable)
    command = [
        str(python), "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", "researchos-server", "--distpath", str(root / "dist"),
        "--workpath", str(root / "build" / "pyinstaller"),
        "--specpath", str(root / "build"), "--paths", str(root),
        "--hidden-import", "api.main", "--hidden-import", "api.web_proxy",
        "--collect-submodules", "api", "--collect-submodules", "koi",
        "--collect-submodules", "widgets", "--collect-data", "latex2mathml",
    ]
    for name in ("web", "widgets", "agents", "docs"):
        command.extend(("--add-data", f"{root / name}{os.pathsep}{name}"))
    command.append(str(root / "api" / "desktop_server.py"))
    subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()
