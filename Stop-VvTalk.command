#!/bin/bash
# Stop the browser-mode or source-mode service started by Start-VvTalk.command.
set -euo pipefail
DATA_DIR="${VVTALK_DATA_DIR:-$HOME/Library/Application Support/VvTalkStudio}"
STATUS="$DATA_DIR/runtime.json"
[ -f "$STATUS" ] || exit 0

PID=$(sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$STATUS" | head -1)
[ -n "${PID:-}" ] || exit 0
kill -0 "$PID" 2>/dev/null || exit 0

COMMAND=$(ps -p "$PID" -o command= 2>/dev/null || true)
case "$COMMAND" in
  *VvTalkStudio*|*app.py*) ;;
  *) exit 0 ;;
esac

kill "$PID" 2>/dev/null || true
i=0
while [ "$i" -lt 20 ]; do
  kill -0 "$PID" 2>/dev/null || exit 0
  sleep 0.1
  i=$((i + 1))
done
kill -9 "$PID" 2>/dev/null || true
