#!/bin/bash
# Sign (and optionally notarize) the macOS application bundle.
# Usage: ./sign-release-macos.sh [VvTalkStudio.app] ["Developer ID Application: ..."]
#        NOTARY_PROFILE=profile ./sign-release-macos.sh ...
set -euo pipefail

APP="${1:-dist/VvTalkStudio.app}"
IDENTITY="${2:--}"

if [ ! -d "$APP" ]; then
  echo "找不到应用包：$APP" >&2
  exit 1
fi

if [ "$IDENTITY" = "-" ]; then
  echo "使用 ad-hoc 签名（仅本机测试；公开发行请提供 Developer ID 证书）。"
  codesign --force --deep --sign - "$APP"
else
  codesign --force --deep --options runtime --timestamp --sign "$IDENTITY" "$APP"
fi
codesign --verify --deep --strict --verbose=2 "$APP"

if [ -n "${NOTARY_PROFILE:-}" ]; then
  TMP=$(mktemp -d)
  ZIP="$TMP/VvTalkStudio.zip"
  ditto -c -k --norsrc --noextattr --keepParent "$APP" "$ZIP"
  xcrun notarytool submit "$ZIP" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP"
  rm -rf "$TMP"
  echo "已公证并装订票据。"
fi
