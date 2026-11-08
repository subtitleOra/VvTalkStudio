#!/bin/bash
# Build the native macOS app (or the legacy WebView app with --web).
set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:---native}"
if [[ $# -gt 1 || ( "$MODE" != "--native" && "$MODE" != "--web" ) ]]; then
  echo "用法：./build.sh [--native|--web]" >&2
  exit 2
fi

find_python() {
  if [ -n "${PYTHON:-}" ]; then
    printf '%s\n' "$PYTHON"
    return 0
  fi
  local candidate
  for candidate in "$HOME/.local/bin/python3.12" python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

if ! PYTHON_BIN=$(find_python); then
  echo "需要 Python 3.12 或更高版本。请安装后重试，或用 PYTHON=/path/to/python3.12 ./build.sh 指定。" >&2
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  "$PYTHON_BIN" -m venv .venv
fi
if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
  .venv/bin/python -m ensurepip --upgrade
fi
.venv/bin/python -m pip install --upgrade pip

REQUIREMENTS=requirements-lock.txt
[ -f "$REQUIREMENTS" ] || REQUIREMENTS=requirements.txt
.venv/bin/python -m pip install -r "$REQUIREMENTS"

.venv/bin/python -m unittest discover -s tests -v
VVTALK_DATA_DIR="$PWD/.qa/macos-selfcheck" .venv/bin/python app.py --self-test

if [[ "$MODE" = "--web" ]]; then
  .venv/bin/python -m PyInstaller --noconfirm VvTalkStudio.spec
  echo "已生成 dist/VvTalkStudio.app（网页界面）"
else
  xcodebuild -project macOS/VvTalkStudio.xcodeproj -scheme VvTalkStudio \
    -configuration Release -destination 'platform=macOS,name=My Mac' \
    -derivedDataPath build/macos-native build
  SOURCE="build/macos-native/Build/Products/Release/VvTalkStudioNative.app"
  DESTINATION="dist/VvTalkStudioNative.app"
  mkdir -p "$DESTINATION"
  /usr/bin/rsync -a --delete "$SOURCE/" "$DESTINATION/"
  codesign --verify --deep --strict "$DESTINATION"
  echo "已生成 $DESTINATION（原生界面）"
fi
