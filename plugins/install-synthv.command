#!/bin/bash
# Choose the existing Synthesizer V Studio 2 scripts folder and install the
# clipboard import plugin, backing up an older copy first.
set -euo pipefail
cd "$(dirname "$0")"

FOLDER=$(/usr/bin/osascript <<'APPLESCRIPT'
try
    set chosenFolder to choose folder with prompt "Select the existing Synthesizer V Studio 2 scripts folder (Scripts > Open Scripts Folder)."
    return POSIX path of chosenFolder
on error number -128
    return ""
end try
APPLESCRIPT
) || FOLDER=""

[ -n "$FOLDER" ] || exit 0
FOLDER="${FOLDER%/}"
DESTINATION="$FOLDER/VvTalkStudio_Import.js"

if [ -f "$DESTINATION" ]; then
  BACKUP="$DESTINATION.backup-$(date +%Y%m%d-%H%M%S)"
  cp -p "$DESTINATION" "$BACKUP"
  echo "Previous plugin backed up: $BACKUP"
fi

cp -p "VvTalkStudio_Import.js" "$DESTINATION"
echo "Installed: $DESTINATION"
echo "Rescan scripts in Synthesizer V Studio 2. Copy exported .sv2.json, then run the VvTalk Studio import script."
