"""Build the desktop server on the host OS (PyInstaller cannot cross-compile)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    # Git symlinks checked out on Windows can become placeholder files. Package
    # ordinary files so NSIS/7-Zip never receives directory-like .md entries.
    docs_copy = root / "build" / "desktop-docs"
    shutil.rmtree(docs_copy, ignore_errors=True)
    shutil.copytree(root / "docs", docs_copy, symlinks=False)
    for alias in ("GETTING_STARTED.md", "KNOWLEDGE_BASE.md", "PROGRAM_FORMAT.md", "PROJECT_FORMAT.md"):
        source = root / "docs" / alias
        if source.is_symlink():
            target = source.resolve()
        else:
            target = source.parent / source.read_text(encoding="utf-8").strip()
        (docs_copy / alias).write_bytes(target.read_bytes())
    env_python = os.environ.get("RESEARCHOS_BUILD_PYTHON")
    python = Path(env_python) if env_python else Path(sys.executable)
    command = [
        str(python), "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", "researchos-server", "--distpath", str(root / "dist"),
        "--workpath", str(root / "build" / "pyinstaller"),
        "--specpath", str(root / "build"), "--paths", str(root),
        "--hidden-import", "api.main", "--hidden-import", "api.web_proxy",
        "--collect-submodules", "api", "--collect-submodules", "koi",
        "--collect-data", "latex2mathml",
    ]
    for name in ("web", "koi/widgets", "agents", "docs"):
        source = docs_copy if name == "docs" else root / name
        command.extend(("--add-data", f"{source}{os.pathsep}{name}"))
    command.append(str(root / "api" / "desktop_server.py"))
    subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()
