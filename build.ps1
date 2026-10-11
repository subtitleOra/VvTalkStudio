$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & py -3.12 -m venv (Join-Path $taskRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required to create the build environment.' }
}
$taskRequirements = Join-Path $taskRoot 'requirements-lock.txt'
if (-not (Test-Path -LiteralPath $taskRequirements)) {
    $taskRequirements = Join-Path $taskRoot 'requirements.txt'
}
& $taskPython -m pip install -r $taskRequirements
if ($LASTEXITCODE -ne 0) { throw 'Dependency setup failed.' }
Push-Location $taskRoot
try {
    & $taskPython -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    & $taskPython app.py --self-test
    if ($LASTEXITCODE -ne 0) { throw 'Export self-test failed.' }
    & $taskPython -m PyInstaller --noconfirm VvTalkStudio.spec
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
} finally { Pop-Location }
