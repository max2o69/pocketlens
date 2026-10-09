param(
    [ValidateSet('chrome', 'msedge')][string]$BrowserChannel = 'chrome',
    [string]$BrowserExecutable
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command npx.cmd -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js/npm to run developer browser tests. Normal camera use does not require Node.js.'
}
$taskStartedServer = $false
$taskBrowserOpened = $false
$taskSession = 'pocketlens-check-' + [Guid]::NewGuid().ToString('N').Substring(0, 8)
$taskDirectory = Join-Path $PSScriptRoot 'work\browser-compatibility'
New-Item -ItemType Directory -Force -Path $taskDirectory | Out-Null
$taskBrowser = @{ browserName = 'chromium'; isolated = $true; launchOptions = @{ channel = $BrowserChannel; headless = $true }; contextOptions = @{ ignoreHTTPSErrors = $true; permissions = @('camera'); viewport = @{ width = 1280; height = 1000 } } }
if ($BrowserExecutable) {
    $taskExecutable = (Resolve-Path -LiteralPath $BrowserExecutable).Path
    $taskBrowser.launchOptions = @{ executablePath = $taskExecutable; headless = $true }
}
$taskConfig = Join-Path $taskDirectory ($taskSession + '.json')
@{ browser = $taskBrowser; outputDir = (Join-Path $PSScriptRoot 'output\playwright') } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $taskConfig -Encoding utf8
function Invoke-CameraBrowserCli {
    param([string[]]$CliArguments)
    $taskOutput = & npx.cmd --yes --package '@playwright/cli@0.1.22' playwright-cli ("-s=$taskSession") @CliArguments
    if ($LASTEXITCODE -ne 0 -or ($taskOutput -join "`n") -match '(?m)^### Error') { throw ($taskOutput -join "`n") }
    return ($taskOutput -join "`n")
}
try {
    try { $taskStatus = Invoke-RestMethod http://127.0.0.1:8766/status -TimeoutSec 2 } catch { $taskStatus = $null }
    if ($taskStatus -and $taskStatus.app -ne 'pocketlens') { throw 'Port 8766 is used by another application.' }
    if ($taskStatus -and ($taskStatus.live -or $taskStatus.cameraInUse)) {
        throw 'Stop phone capture and close virtual-camera clients before running browser tests.'
    }
    if (-not $taskStatus) {
        & (Join-Path $PSScriptRoot 'Start PocketLens.ps1') -NoBrowser -Ip 127.0.0.1
        if ($LASTEXITCODE -ne 0) { throw 'Receiver could not start.' }
        $taskStartedServer = $true
    }
    Invoke-CameraBrowserCli @('open', 'http://127.0.0.1:8766/camera-test', '--config', $taskConfig) | Write-Host
    $taskBrowserOpened = $true
    $taskReply = Invoke-CameraBrowserCli @('--raw', 'run-code', '--filename', (Join-Path $PSScriptRoot 'scripts\browser_compatibility.js'))
    $taskReport = $taskReply | ConvertFrom-Json
    if (-not ($taskReport.realVirtualCamera -and $taskReport.movingPixels -and $taskReport.flip -and $taskReport.stopStart -and $taskReport.webRTCSend) -or $taskReport.pageErrors -ne 0) {
        throw 'Browser compatibility checks did not all pass.'
    }
    $taskMirrorReply = Invoke-CameraBrowserCli @('--raw', 'run-code', '--filename', (Join-Path $PSScriptRoot 'scripts\phone_mirror_compatibility.js'))
    $taskMirrorReport = $taskMirrorReply | ConvertFrom-Json
    foreach ($taskMode in @('WebRTC', 'JPEG')) {
        $taskResult = $taskMirrorReport.$taskMode
        if (-not ($taskResult.preview -and $taskResult.outgoing -and $taskResult.dashboardSync -and $taskResult.stopStart) -or $taskMirrorReport.pageErrors -ne 0) {
            throw "Phone mirror checks failed for $taskMode."
        }
    }
    $taskReport | Add-Member -NotePropertyName phoneMirror -NotePropertyValue $taskMirrorReport
    $taskReport | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $taskDirectory "$BrowserChannel-result.json") -Encoding utf8
    Write-Host $taskReply
    Write-Host $taskMirrorReply
    Write-Host 'Browser capture and WebRTC sending passed. Results saved under work\browser-compatibility.'
} finally {
    if ($taskBrowserOpened) {
        try { Invoke-CameraBrowserCli @('close') | Write-Host } catch { Write-Warning "Browser cleanup failed: $_" }
    }
    if ($taskStartedServer) {
        Invoke-RestMethod http://127.0.0.1:8766/shutdown -Method Post -Headers @{ Origin = 'http://127.0.0.1:8766' } -TimeoutSec 3 | Out-Null
    }
}
