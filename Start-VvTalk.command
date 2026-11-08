#!/bin/bash
# Double-click entry point for macOS. Mirrors Start-VvTalk.cmd.
set -euo pipefail
cd "$(dirname "$0")"

if [ -d "VvTalkStudio.app" ]; then
  open "VvTalkStudio.app"
elif [ -d "dist/VvTalkStudio.app" ]; then
  open "dist/VvTalkStudio.app"
elif [ -x ".venv/bin/python" ]; then
  DATA_DIR="${VVTALK_DATA_DIR:-$HOME/Library/Application Support/VvTalkStudio}"
  mkdir -p "$DATA_DIR"
  nohup .venv/bin/python app.py >>"$DATA_DIR/start.log" 2>&1 &
else
  /usr/bin/osascript -e 'display alert "VvTalk Studio" message "未找到 VvTalkStudio.app 或 .venv。请先运行 ./build.sh，或按 README 从源码准备 Python 3.12 环境。"'
  exit 1
fi
