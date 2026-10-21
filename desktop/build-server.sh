#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

build_venv="${RESEARCHOS_BUILD_VENV:-$repo_root/.venv}"
if [[ ! -x "$build_venv/bin/pyinstaller" ]]; then
  echo "Create .venv and install requirements.txt plus pyinstaller before building." >&2
  exit 1
fi
whisper_assets="$("$build_venv/bin/python" -c 'import faster_whisper, pathlib; print(pathlib.Path(faster_whisper.__file__).parent / "assets")')"

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
  --collect-data latex2mathml \
  --collect-all faster_whisper \
  --collect-all ctranslate2 \
  --collect-all av \
  --collect-all onnxruntime \
  --add-data "$whisper_assets:faster_whisper/assets" \
  --add-data "$repo_root/web:web" \
  --add-data "$repo_root/koi/widgets:koi/widgets" \
  --add-data "$repo_root/agents:agents" \
  --add-data "$repo_root/docs:docs" \
  api/desktop_server.py
