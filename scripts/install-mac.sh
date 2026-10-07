#!/bin/bash
# Build locally with private toolchains; never require sudo or change shell profiles.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ "$(uname -s)" == Darwin ]] || { echo "Этот установщик работает только на macOS."; exit 1; }
case "$(uname -m)" in
  arm64) UV_ARCH=aarch64; NODE_ARCH=arm64 ;;
  x86_64) UV_ARCH=x86_64; NODE_ARCH=x64 ;;
  *) echo "Архитектура этого Mac не поддерживается."; exit 1 ;;
esac
TOOLS="$ROOT/.tools/mac-installer"
mkdir -p "$TOOLS"
# mkdir is atomic: concurrent builds must not share node_modules or build output.
LOCK="$TOOLS/install.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  # An interrupted Terminal session can leave the directory behind.
  sleep 2
  lock_pid="$(cat "$LOCK/pid" 2>/dev/null || true)"
  if [[ "$lock_pid" =~ ^[0-9]+$ ]] && kill -0 "$lock_pid" 2>/dev/null; then
    echo "Установщик уже запущен (PID $lock_pid)."
    exit 1
  fi
  rm -f "$LOCK/pid"
  rmdir "$LOCK" 2>/dev/null || true
  if ! mkdir "$LOCK" 2>/dev/null; then
    echo "Не удалось снять блокировку установщика: $LOCK"
    exit 1
  fi
fi
echo "$$" > "$LOCK/pid"
TMP="$(mktemp -d "$TOOLS/download.XXXXXX")"
cleanup() { rm -rf "$TMP"; rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 130' INT HUP TERM
fetch() { curl --fail --location --retry 3 --connect-timeout 30 --output "$2" "$1"; }
verify() {
  local expected actual
  expected="$(awk -v name="$2" '$2 == name || $2 == "*" name {print $1}' "$3")"
  actual="$(shasum -a 256 "$1" | awk '{print $1}')"
  [[ -n "$expected" && "$actual" == "$expected" ]] || { echo "Не совпала контрольная сумма: $2"; exit 1; }
}

echo "[1/5] Подготовка Python и Node.js…"
UV_VERSION=0.8.22
UV_DIR="$TOOLS/uv-$UV_VERSION"
if [[ ! -x "$UV_DIR/uv" ]]; then
  archive="uv-$UV_ARCH-apple-darwin.tar.gz"
  base="https://github.com/astral-sh/uv/releases/download/$UV_VERSION"
  fetch "$base/$archive" "$TMP/$archive"
  fetch "$base/$archive.sha256" "$TMP/uv.sha256"
  verify "$TMP/$archive" "$archive" "$TMP/uv.sha256"
  mkdir "$TMP/uv"
  tar -xzf "$TMP/$archive" -C "$TMP/uv" --strip-components=1
  mv "$TMP/uv" "$UV_DIR"
fi
NODE_VERSION=22.14.0
NODE_DIR="$TOOLS/node-v$NODE_VERSION-darwin-$NODE_ARCH"
if [[ ! -x "$NODE_DIR/bin/node" ]]; then
  archive="node-v$NODE_VERSION-darwin-$NODE_ARCH.tar.gz"
  base="https://nodejs.org/dist/v$NODE_VERSION"
  fetch "$base/$archive" "$TMP/$archive"
  fetch "$base/SHASUMS256.txt" "$TMP/node.sha256"
  verify "$TMP/$archive" "$archive" "$TMP/node.sha256"
  tar -xzf "$TMP/$archive" -C "$TMP"
  mv "$TMP/node-v$NODE_VERSION-darwin-$NODE_ARCH" "$NODE_DIR"
fi
export PATH="$NODE_DIR/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export UV_PYTHON_INSTALL_DIR="$TOOLS/python"
export UV_PYTHON_PREFERENCE=only-managed
export RESEARCHOS_BUILD_VENV="$TOOLS/venv"
if [[ ! -x "$RESEARCHOS_BUILD_VENV/bin/python" ]]; then
  "$UV_DIR/uv" venv --python 3.12 "$RESEARCHOS_BUILD_VENV"
fi

echo "[2/5] Установка зависимостей…"
"$UV_DIR/uv" pip install --python "$RESEARCHOS_BUILD_VENV/bin/python" --only-binary :all: -r "$ROOT/requirements.txt" 'pyinstaller==6.16.0'
cd "$ROOT/desktop"
npm ci --no-audit --no-fund

echo "[3/5] Сборка приложения с иконкой…"
echo "Упаковка может несколько минут не показывать прогресс. Дождитесь шага [4/5] или сообщения об ошибке."
export CSC_IDENTITY_AUTO_DISCOVERY=false
npm run pack:mac -- --config.mac.identity=- --config.mac.hardenedRuntime=false
APP="$ROOT/desktop/dist/mac/ResearcherOS.app"
[[ "$NODE_ARCH" != arm64 ]] || APP="$ROOT/desktop/dist/mac-arm64/ResearcherOS.app"
[[ -d "$APP" ]] || { echo "Сборка не создала приложение: $APP"; exit 1; }

node "$ROOT/desktop/verify-server.cjs" "$APP/Contents/Resources/server/researchos-server"

echo "[4/5] Установка в ~/Applications…"
DEST="$HOME/Applications/ResearcherOS.app"
if pgrep -f "^$DEST/Contents/MacOS/ResearcherOS$" >/dev/null; then
  echo "Закройте ResearcherOS и повторите установку. Сборка сохранена: $APP"
  exit 1
fi
mkdir -p "$HOME/Applications"
STAGE="$(mktemp -d "$HOME/Applications/.researchos-install.XXXXXX")"
# Keep the previous app until the new bundle has been copied successfully.
if ! ditto "$APP" "$STAGE/ResearcherOS.app"; then
  rm -rf "$STAGE"
  exit 1
fi
if [[ -e "$DEST" ]]; then
  mv "$DEST" "$STAGE/previous.app"
fi
if ! mv "$STAGE/ResearcherOS.app" "$DEST"; then
  [[ ! -d "$STAGE/previous.app" ]] || mv "$STAGE/previous.app" "$DEST"
  exit 1
fi
rm -rf "$STAGE"

echo "[5/5] Создание ярлыка на рабочем столе…"
mkdir -p "$HOME/Desktop"
LINK="$HOME/Desktop/ResearcherOS.app"
if [[ -L "$LINK" ]]; then
  rm "$LINK"
fi
if [[ -e "$LINK" ]]; then
  echo "На рабочем столе уже есть ResearcherOS.app; этот файл сохранён. Приложение установлено: $DEST"
else
  ln -s "$DEST" "$LINK"
fi
touch "$DEST"
echo "ResearcherOS установлен: $DEST"
echo "Открываю мастер настройки ResearcherOS…"
open "$DEST" --args --reconfigure
