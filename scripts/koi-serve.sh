#!/usr/bin/env bash
# Start/stop KOI API (8010) + web UI (8080). Idempotent.
set -euo pipefail

KOI_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export KOI_ROOT
VENV="$KOI_ROOT/.venv"
API_PORT=8010
WEB_PORT=8080
RUN_DIR="$KOI_ROOT/.run"
LOG_DIR="$RUN_DIR/logs"
API_PID="$RUN_DIR/koi-api.pid"
WEB_PID="$RUN_DIR/koi-web.pid"
WORKER_PID="$RUN_DIR/koi-agent-chat-worker.pid"
CURSOR_WIDGET_PID="$RUN_DIR/koi-cursor-usage-widget.pid"
ENV_FILE="$KOI_ROOT/.env"

mkdir -p "$RUN_DIR" "$LOG_DIR"

# Load private keys/env (gitignored). Every variable in .env is exported
# and inherited by the API, web server and agent worker.
if [[ -f "$ENV_FILE" ]]; then
  chmod 600 "$ENV_FILE" 2>/dev/null || true
  # shellcheck disable=SC1090
  set -a && source "$ENV_FILE" && set +a
fi

port_busy() {
  lsof -ti:"$1" >/dev/null 2>&1
}

health_ok() {
  curl -sf "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1 \
    && curl -sf "http://127.0.0.1:${WEB_PORT}/api/health" >/dev/null 2>&1
}

diagnose_health() {
  if curl -sf "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
    echo "  API :${API_PORT} — OK" >&2
  else
    echo "  API :${API_PORT} — не отвечает" >&2
    if port_busy "$API_PORT"; then
      echo "    порт занят PID: $(lsof -ti:"$API_PORT" 2>/dev/null | tr '\n' ' ')" >&2
    fi
  fi
  if curl -sf "http://127.0.0.1:${WEB_PORT}/api/health" >/dev/null 2>&1; then
    echo "  Web :${WEB_PORT}/api — OK" >&2
  elif curl -sf -o /dev/null "http://127.0.0.1:${WEB_PORT}/" 2>/dev/null; then
    echo "  Web :${WEB_PORT} — отвечает на /, но НЕТ /api (старый http.server?)" >&2
    echo "    запустите: $0 restart" >&2
  else
    echo "  Web :${WEB_PORT} — не отвечает" >&2
    if port_busy "$WEB_PORT"; then
      echo "    порт занят PID: $(lsof -ti:"$WEB_PORT" 2>/dev/null | tr '\n' ' ')" >&2
    fi
  fi
}

free_port() {
  local port="$1"
  if ! port_busy "$port"; then
    return 0
  fi
  local pids
  pids="$(lsof -ti:"$port" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
    sleep 0.5
  fi
}

_python_for_venv() {
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      echo "$candidate"
      return 0
    fi
  done
  echo python3
}

ensure_venv() {
  local py
  py="$(_python_for_venv)"
  if [[ ! -d "$VENV" ]]; then
    echo "Creating venv in $VENV ($py)"
    "$py" -m venv "$VENV"
  fi
  if ! "$VENV/bin/python" -c "import uvicorn" 2>/dev/null; then
    echo "Installing Python dependencies in $VENV"
    "$VENV/bin/pip" install -q --upgrade pip
    "$VENV/bin/pip" install -q -r "$KOI_ROOT/requirements.txt"
  fi
}

start_api() {
  if curl -sf "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
    return 0
  fi
  stop_pid_file "$API_PID" "$API_PORT"
  ensure_venv
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  cd "$KOI_ROOT"
  if [[ "${KOI_RELOAD:-}" == "1" ]]; then
    nohup env WATCHFILES_FORCE_POLLING=true uvicorn api.main:app --host 127.0.0.1 --port "$API_PORT" \
      --reload --reload-dir "$KOI_ROOT/api" --reload-dir "$KOI_ROOT/koi" \
      >>"$LOG_DIR/api.log" 2>&1 &
  else
    nohup env WATCHFILES_FORCE_POLLING=true uvicorn api.main:app --host 127.0.0.1 --port "$API_PORT" \
      >>"$LOG_DIR/api.log" 2>&1 &
  fi
  echo $! >"$API_PID"
}

start_web() {
  if curl -sf "http://127.0.0.1:${WEB_PORT}/api/health" >/dev/null 2>&1; then
    return 0
  fi
  stop_pid_file "$WEB_PID" "$WEB_PORT"
  # Старый python -m http.server отвечает на /, но не проксирует /api.
  if port_busy "$WEB_PORT"; then
    free_port "$WEB_PORT"
  fi
  ensure_venv
  cd "$KOI_ROOT"
  nohup "$VENV/bin/python" -m api.web_proxy \
    --host 127.0.0.1 --port "$WEB_PORT" --api-host 127.0.0.1 --api-port "$API_PORT" \
    >>"$LOG_DIR/web.log" 2>&1 &
  echo $! >"$WEB_PID"
}

start_cursor_usage_widget() {
  if [[ "${KOI_CURSOR_USAGE_WIDGET:-0}" != "1" ]]; then
    return 0
  fi
  if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "cursor usage widget: skipped (macOS overlay only for now)" >&2
    return 0
  fi
  if [[ -f "$CURSOR_WIDGET_PID" ]]; then
    local pid
    pid="$(cat "$CURSOR_WIDGET_PID")"
    if kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    rm -f "$CURSOR_WIDGET_PID"
  fi
  ensure_venv
  nohup "$VENV/bin/python" -m koi.cursor.widget \
    >>"$LOG_DIR/cursor-usage-widget.log" 2>&1 &
  echo $! >"$CURSOR_WIDGET_PID"
}

start_agent_worker() {
  if [[ -f "$WORKER_PID" ]] && kill -0 "$(cat "$WORKER_PID")" 2>/dev/null; then
    return 0
  fi
  local mode="${KOI_AGENT_CHAT_MODE:-}"
  if [[ -z "$mode" && -n "${CURSOR_API_KEY:-}" ]]; then
    mode="api"
  fi
  if [[ -z "$mode" ]]; then
    mode="local"
  fi
  if [[ "$mode" != "api" ]]; then
    echo "agent worker: skipped (KOI_AGENT_CHAT_MODE=$mode; local mode runs per question)" >&2
    return 0
  fi
  if [[ -z "${CURSOR_API_KEY:-}" ]]; then
    echo "agent worker: skipped (CURSOR_API_KEY not set in $ENV_FILE)" >&2
    return 0
  fi
  ensure_venv
  if ! "$VENV/bin/python" -c "import cursor_sdk" 2>/dev/null; then
    echo "agent worker: installing cursor-sdk…" >&2
    if ! "$VENV/bin/pip" install -q cursor-sdk; then
      echo "agent worker: skipped (cursor-sdk install failed)" >&2
      return 0
    fi
  fi
  nohup "$VENV/bin/python" -m koi.agent_chat.worker \
    >>"$LOG_DIR/agent-chat-worker.log" 2>&1 &
  echo $! >"$WORKER_PID"
}

agent_chat_mode() {
  local mode="${KOI_AGENT_CHAT_MODE:-}"
  if [[ -z "$mode" && -n "${CURSOR_API_KEY:-}" ]]; then
    mode="api"
  fi
  if [[ -z "$mode" ]]; then
    mode="local"
  fi
  echo "$mode"
}

stop_inbox_watcher() {
  stop_pid_file_simple "$RUN_DIR/koi-agent-chat-inbox-watch.pid"
  stop_pid_file_simple "$RUN_DIR/koi-related-work-inbox-watch.pid"
  stop_pid_file_simple "$RUN_DIR/koi-paper-inbox-watch.pid"
}

stop_pid_file_simple() {
  local pid_file="$1"
  if [[ ! -f "$pid_file" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 0.3
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

_start_one_inbox_watcher() {
  local module="$1"
  local pid_file="$2"
  local log_file="$3"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    rm -f "$pid_file"
  fi
  ensure_venv
  nohup "$VENV/bin/python" -m "$module" watch >>"$log_file" 2>&1 &
  local i pid
  for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 0.2
    if [[ -f "$pid_file" ]]; then
      pid="$(cat "$pid_file")"
      if kill -0 "$pid" 2>/dev/null; then
        return 0
      fi
    fi
  done
  echo "warning: inbox watcher failed to start: $module (see $log_file)" >&2
}

start_inbox_watcher() {
  if [[ "$(agent_chat_mode)" != "cursor_inbox" ]]; then
    return 0
  fi
  _start_one_inbox_watcher \
    "koi.agent_chat.inbox_cli" \
    "$RUN_DIR/koi-agent-chat-inbox-watch.pid" \
    "$LOG_DIR/agent-chat-watch.log"
  _start_one_inbox_watcher \
    "koi.related_work.inbox_cli" \
    "$RUN_DIR/koi-related-work-inbox-watch.pid" \
    "$LOG_DIR/related-work-watch.log"
  _start_one_inbox_watcher \
    "koi.paper.inbox_cli" \
    "$RUN_DIR/koi-paper-inbox-watch.pid" \
    "$LOG_DIR/paper-watch.log"
}

stop_pid_file() {
  local pid_file="$1"
  local port="$2"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 0.5
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
  fi
  if port_busy "$port"; then
    local pids
    pids="$(lsof -ti:"$port" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      # shellcheck disable=SC2086
      kill -9 $pids 2>/dev/null || true
    fi
  fi
}

cmd_start() {
  if [[ -x "$KOI_ROOT/scripts/koi-install-tectonic.sh" ]]; then
    "$KOI_ROOT/scripts/koi-install-tectonic.sh" || true
  fi
  start_api
  start_web
  start_agent_worker
  start_cursor_usage_widget
  start_inbox_watcher
  for _ in $(seq 1 30); do
    if health_ok; then
      echo "KOI running"
      echo "  UI:  http://127.0.0.1:${WEB_PORT}/"
      echo "  API: http://127.0.0.1:${API_PORT}/ (docs: /docs)"
      if [[ "$(agent_chat_mode)" == "cursor_inbox" ]]; then
        echo "  Chat inbox:     .run/logs/agent-chat-watch.log (AGENT_CHAT_WAKE)"
        echo "  Literature inbox: .run/logs/related-work-watch.log (RELATED_WORK_WAKE)"
        echo "  Paper inbox:    .run/logs/paper-watch.log (PAPER_WAKE)"
      fi
      if [[ "${KOI_CURSOR_USAGE_WIDGET:-0}" == "1" && "$(uname -s)" == "Darwin" ]]; then
        echo "  Cursor desktop overlay: enabled (legacy; web widget is default in ResearchOS UI)"
      fi
      return 0
    fi
    sleep 0.4
  done
  echo "KOI failed to become healthy. Logs: $LOG_DIR" >&2
  diagnose_health >&2
  return 1
}

cmd_stop() {
  stop_pid_file "$API_PID" "$API_PORT"
  stop_pid_file "$WEB_PID" "$WEB_PORT"
  free_port "$API_PORT"
  free_port "$WEB_PORT"
  stop_inbox_watcher
  stop_pid_file_simple "$CURSOR_WIDGET_PID"
  if [[ -f "$WORKER_PID" ]]; then
    pid="$(cat "$WORKER_PID")"
    kill "$pid" 2>/dev/null || true
    rm -f "$WORKER_PID"
  fi
  echo "KOI stopped"
}

cmd_status() {
  if health_ok; then
    echo "KOI: up (API ${API_PORT}, web ${WEB_PORT})"
    return 0
  fi
  echo "KOI: down"
  return 1
}

cmd_restart() {
  cmd_stop
  sleep 2
  cmd_start
}

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  restart) cmd_restart ;;
  *)
    echo "Usage: $0 {start|stop|status|restart}"
    exit 1
    ;;
esac
