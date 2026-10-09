$ErrorActionPreference = 'Stop'
Write-Host 'Camera diagnostics (no pairing secrets or private keys are shown)'
Write-Host ('Windows: ' + [Environment]::OSVersion.Version)
. (Join-Path $PSScriptRoot 'PocketLens Runtime.ps1')
$taskData = Get-PocketLensDataDirectory
$taskRuntime = Join-Path $taskData 'venv\Scripts\python.exe'
if (Test-Path -LiteralPath $taskRuntime) {
    & $taskRuntime -c "import sys, struct; print('Python:', sys.version.split()[0], str(struct.calcsize('P') * 8) + '-bit')"
    & $taskRuntime -m pip check
} else {
    Write-Host 'Runtime: missing. Run Start PocketLens.cmd after installing 64-bit Python 3.12.'
}
foreach ($taskArch in @('x64', 'x86')) {
    $taskDll = Join-Path $PSScriptRoot "native\bin\$taskArch\pocketlens.dll"
    Write-Host ("Native $taskArch camera: " + $(if (Test-Path -LiteralPath $taskDll) { 'present' } else { 'missing; run Build PocketLens Native.ps1' }))
}
try {
    $taskStatus = Invoke-RestMethod 'http://127.0.0.1:8766/status' -TimeoutSec 2
    if ($taskStatus.app -eq 'pocketlens') {
        Write-Host ("Receiver: running; video live: $($taskStatus.live); camera in use: $($taskStatus.cameraInUse)")
    } else { Write-Host 'Port 8766: occupied by another application.' }
} catch { Write-Host "Receiver: not reachable. Check $taskData\pocketlens-errors.log." }
if (Get-Command Get-NetFirewallRule -ErrorAction SilentlyContinue) {
    Get-NetFirewallRule -Name 'PocketLens-*' -ErrorAction SilentlyContinue | Select-Object Name, Enabled, Profile | Format-Table
}
Write-Host 'For phone connection issues: use the same trusted Wi-Fi, run Allow PocketLens Network.ps1, and keep Safari open.'
