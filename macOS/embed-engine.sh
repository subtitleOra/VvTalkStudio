#!/bin/bash
set -euo pipefail
ROOT="$(cd "${SRCROOT}/.." && pwd)"
PYTHON="${VVTALK_ENGINE_PYTHON:-$ROOT/.venv/bin/python}"
CACHE="$ROOT/build/native-engine/${ARCHS}"
HELPERS="$TARGET_BUILD_DIR/$CONTENTS_FOLDER_PATH/Helpers"
SOURCE="$CACHE/dist/VvTalkEngine.app"
DESTINATION="$HELPERS/VvTalkEngine.app"
STAMP="$DERIVED_FILE_DIR/vvtalk-engine-fingerprint"
if [[ ! -x "$PYTHON" ]] || ! "$PYTHON" -c 'import PyInstaller, parselmouth, pypinyin, fugashi, unidic_lite, cmudict, praatio'; then
    echo "error: 缺少引擎构建依赖。请先按 docs/macos-native.md 配置 Python 3.12 与 .venv。"
    exit 1
fi
if [[ "$("$PYTHON" -c 'import platform; print(platform.machine())')" != "$ARCHS" ]]; then
    echo "error: Python 的运行架构必须与 Xcode 目标架构 ($ARCHS) 一致。"
    exit 1
fi

# Cache the packaged engine across Swift-only builds and keep the source out of the app.
cd "$ROOT"
FINGERPRINT="$({
    "$PYTHON" -c 'import PyInstaller, sys; print(sys.executable, sys.version, PyInstaller.__version__)'
    "$PYTHON" -m pip freeze
    /usr/bin/shasum -a 256 native_engine.py server.py adapters.py alignment.py platform_support.py VvTalkStudio.spec requirements-lock.txt
    /usr/bin/find core templates plugins -type f ! -name '*.pyc' ! -name '.DS_Store' -print0 |
        /usr/bin/xargs -0 /usr/bin/shasum -a 256 | LC_ALL=C /usr/bin/sort
} | /usr/bin/shasum -a 256 | /usr/bin/cut -d ' ' -f 1)"

if [[ ! -x "$SOURCE/Contents/MacOS/VvTalkEngine" || "$(cat "$CACHE/fingerprint" 2>/dev/null || true)" != "$FINGERPRINT" ]]; then
    mkdir -p "$CACHE"
    VVTALK_NATIVE_ENGINE=1 "$PYTHON" -m PyInstaller --noconfirm --log-level WARN \
        --workpath "$CACHE/work" --distpath "$CACHE/dist" VvTalkStudio.spec
    printf '%s\n' "$FINGERPRINT" > "$CACHE/fingerprint"
fi
if [[ ! -x "$DESTINATION/Contents/MacOS/VvTalkEngine" || "$(cat "$STAMP" 2>/dev/null || true)" != "$FINGERPRINT" ]]; then
    mkdir -p "$DESTINATION"
    /usr/bin/rsync -a --delete "$SOURCE/" "$DESTINATION/"
    mkdir -p "$DERIVED_FILE_DIR"
    printf '%s\n' "$FINGERPRINT" > "$STAMP"
fi
