Add-Type -AssemblyName System.Windows.Forms
$selector = New-Object System.Windows.Forms.FolderBrowserDialog
$selector.Description = 'Select the existing Synthesizer V Studio 2 scripts folder (Scripts > Open Scripts Folder).'
if ($selector.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
$selectedDirectory = (Resolve-Path -LiteralPath $selector.SelectedPath).Path
$sourceScript = Join-Path $PSScriptRoot 'VvTalkStudio_Import.js'
$destinationScript = Join-Path $selectedDirectory 'VvTalkStudio_Import.js'
if (Test-Path -LiteralPath $destinationScript) {
    $backupScript = $destinationScript + '.backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fffffff')
    Copy-Item -LiteralPath $destinationScript -Destination $backupScript
    Write-Host ('Previous plugin backed up: ' + $backupScript)
}
Copy-Item -LiteralPath $sourceScript -Destination $destinationScript
Write-Host ('Installed: ' + $destinationScript)
Write-Host 'Rescan scripts in Synthesizer V Studio 2. Copy exported .sv2.json, then run the VvTalk Studio import script.'
