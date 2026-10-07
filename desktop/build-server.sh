#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

build_venv="${RESEARCHOS_BUILD_VENV:-$repo_root/.venv}"
if [[ ! -x "$build_venv/bin/pyinstaller" ]]; then
  echo "Create .venv and install requirements.txt plus pyinstaller before building." >&2
  exit 1
fi

"$build_venv/bin/pyinstaller" \
  --noconfirm --clean --onedir \
  --name researchos-server \
  --distpath dist \
  --workpath build/pyinstaller \
  --specpath build \
  --paths . \
  --hidden-import api.main \
  --hidden-import api.web_proxy \
  --collect-submodules api \
  --collect-submodules koi \
  --collect-submodules widgets \
  --collect-data latex2mathml \
  --add-data "$repo_root/web:web" \
  --add-data "$repo_root/widgets:widgets" \
  --add-data "$repo_root/agents:agents" \
  --add-data "$repo_root/docs:docs" \
  api/desktop_server.py
