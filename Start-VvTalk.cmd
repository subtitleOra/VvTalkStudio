@echo off
cd /d "%~dp0"
if exist "VvTalkStudio.exe" (
  start "" "VvTalkStudio.exe"
) else if exist "dist\VvTalkStudio.exe" (
  start "" "dist\VvTalkStudio.exe"
) else (
  start "" ".venv\Scripts\pythonw.exe" "app.py"
)
