#!/bin/bash
# Finder opens executable .command files in Terminal.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$ROOT/.run/logs"
LOG="$ROOT/.run/logs/mac-install-$(date +%Y%m%d-%H%M%S).log"
echo "Установка ResearcherOS. Журнал: $LOG"
/bin/bash "$ROOT/scripts/install-mac.sh" 2>&1 | tee "$LOG"
result=${PIPESTATUS[0]}
if [[ "$result" -eq 0 ]]; then
  echo "Готово. Откройте ResearcherOS через ярлык на рабочем столе."
else
  echo "Установка не завершена. Подробности: $LOG"
fi
if [[ -t 0 ]]; then
  read -r -p "Нажмите Enter, чтобы закрыть окно…" _ || true
fi
exit "$result"
