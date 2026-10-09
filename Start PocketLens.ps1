param([switch]$NoBrowser, [string]$Ip)
$ErrorActionPreference = 'Stop'
$taskApp = $PSScriptRoot
# Runtime state lives outside the app folder so ZIP updates keep the pairing CA.
. (Join-Path $PSScriptRoot 'PocketLens Runtime.ps1')
$taskData = Get-PocketLensDataDirectory
# Keep a relative override consistent with the server's working directory.
$env:POCKETLENS_DATA_DIR = $taskData
$taskRuntime = Join-Path $taskData 'venv\Scripts\python.exe'
try {
    $taskStatus = Invoke-RestMethod 'http://127.0.0.1:8766/status' -TimeoutSec 2
    if ($taskStatus.app -eq 'pocketlens') {
        if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8766' }
        exit 0
    }
    throw 'Port 8766 is in use by another application.'
} catch {
    if ($_.Exception.Message -eq 'Port 8766 is in use by another application.') { throw }
}
foreach ($taskArch in @('x64', 'x86')) {
    if (-not (Test-Path -LiteralPath (Join-Path $taskApp "native\bin\$taskArch\pocketlens.dll"))) {
        throw 'Camera binaries are missing. Use the Windows release ZIP, or run Build PocketLens Native.ps1 after installing Visual Studio C++ Build Tools. See README.md.'
    }
}
if (-not (Test-Path -LiteralPath $taskRuntime)) {
    if (-not (Get-Command py.exe -ErrorAction SilentlyContinue)) {
        throw 'Install 64-bit Python 3.12 with the Python launcher, then run Start PocketLens.cmd again.'
    }
    & py.exe -3.12 -c "import struct; assert struct.calcsize('P') == 8, '64-bit Python is required'"
    if ($LASTEXITCODE -ne 0) { throw '64-bit Python 3.12 is required. See README.md.' }
    $taskVenv = Join-Path $taskData 'venv'
    py -3.12 -m venv $taskVenv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is needed to create the local runtime.' }
}
$taskRequirements = Join-Path $taskApp 'requirements.txt'
$taskStamp = Join-Path $taskData 'requirements.sha256'
$taskHash = (Get-FileHash -LiteralPath $taskRequirements -Algorithm SHA256).Hash
$taskInstalled = if (Test-Path -LiteralPath $taskStamp) { (Get-Content -LiteralPath $taskStamp -Raw).Trim() } else { '' }
$taskDepsMissing = $true
try {
    & $taskRuntime -c "import struct; assert struct.calcsize('P') == 8; import aiohttp, aiortc, cv2, cryptography, numpy, PIL, qrcode" 2>$null
    $taskDepsMissing = $LASTEXITCODE -ne 0
} catch {}
if ($taskDepsMissing -or $taskInstalled -ne $taskHash) {
    Write-Host 'Installing camera dependencies. Internet access is required for this step.'
    & $taskRuntime -m pip install -r (Join-Path $taskApp 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Could not update the camera runtime.' }
    Set-Content -LiteralPath $taskStamp -Value $taskHash
}
$taskLog = Join-Path $taskData 'pocketlens.log'
$taskErr = Join-Path $taskData 'pocketlens-errors.log'
$taskServer = Join-Path $taskApp 'server.py'
$taskArguments = @('-u', ('"' + $taskServer + '"'), '--no-browser')
if ($Ip) { $taskArguments += @('--ip', $Ip) }
$taskProcess = Start-Process -FilePath $taskRuntime -ArgumentList $taskArguments -WorkingDirectory $taskApp -WindowStyle Hidden -RedirectStandardOutput $taskLog -RedirectStandardError $taskErr -PassThru
for ($taskAttempt = 0; $taskAttempt -lt 40; $taskAttempt++) {
    if ($taskProcess.HasExited) {
        if (Test-Path -LiteralPath $taskErr) { Get-Content -LiteralPath $taskErr -Tail 12 | Write-Host }
        throw "Receiver failed to start. Run Diagnose PocketLens.cmd or check $taskErr."
    }
    try {
        $taskStatus = Invoke-RestMethod 'http://127.0.0.1:8766/status' -TimeoutSec 1
        if ($taskStatus.app -eq 'pocketlens') {
            Write-Host 'Camera receiver ready: http://127.0.0.1:8766'
            if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8766' }
            exit 0
        }
    } catch {}
    Start-Sleep -Milliseconds 250
}
throw 'Receiver is taking longer than expected. Run Diagnose PocketLens.cmd and check the error log.'
