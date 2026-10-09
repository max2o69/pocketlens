$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PocketLens Runtime.ps1')
$taskData = Get-PocketLensDataDirectory
$taskRuntime = Join-Path $taskData 'venv\Scripts\python.exe'
try { Invoke-RestMethod -Uri 'http://127.0.0.1:8766/shutdown' -Method Post -Headers @{Origin='http://127.0.0.1:8766'} -TimeoutSec 3 | Out-Null } catch {}
Start-Sleep -Seconds 2
if (Test-Path -LiteralPath $taskRuntime) {
    & $taskRuntime (Join-Path $PSScriptRoot 'scripts\unregister.py')
    if ($LASTEXITCODE -ne 0) { throw 'Could not unregister the current-user camera.' }
} elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
    # Registry removal does not need installed camera dependencies.
    & py.exe -3.12 (Join-Path $PSScriptRoot 'scripts\unregister.py')
    if ($LASTEXITCODE -ne 0) { throw 'Could not unregister the current-user camera.' }
} else { throw 'Python is required to remove current-user registration. See README.md.' }
if ((Test-Path -LiteralPath (Join-Path $env:ProgramFiles 'PocketLens\x64\register-system.exe')) -or
    (Test-Path -LiteralPath (Join-Path $env:ProgramFiles 'InterviewCamera\x64\register-system.exe'))) {
    & (Join-Path $PSScriptRoot 'Install PocketLens System Camera.ps1') -Remove
}
Write-Host 'Remove the PocketLens profile on the iPhone in Settings > General > VPN & Device Management.'
Write-Host 'If you added network access, run Remove PocketLens Network Rules.cmd to remove all three app firewall rules.'
