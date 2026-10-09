param([switch]$Remove, [string]$DataDirectory)
# Run with PowerShell. Windows requests administrator consent only for the firewall rule.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PocketLens Runtime.ps1')
$taskData = if ($DataDirectory) { [IO.Path]::GetFullPath($DataDirectory) } else { Get-PocketLensDataDirectory }
$taskIsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $taskIsAdmin) {
    $taskArguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $PSCommandPath + '"'))
    if ($Remove) { $taskArguments += '-Remove' }
    $taskArguments += @('-DataDirectory', ('"' + $taskData + '"'))
    $taskElevated = Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList $taskArguments -Wait -PassThru
    exit $taskElevated.ExitCode
}
# Remove obsolete rules during setup as well as uninstall.
foreach ($taskRule in @('InterviewCamera-LocalNetwork', 'InterviewCamera-WebRTC', 'InterviewCamera-WebRTC-Base')) {
    Get-NetFirewallRule -Name $taskRule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
}
if ($Remove) {
    foreach ($taskRule in @('PocketLens-LocalNetwork', 'PocketLens-WebRTC', 'PocketLens-WebRTC-Base')) {
        Get-NetFirewallRule -Name $taskRule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    }
    Write-Host 'Camera firewall rules removed.'
    exit 0
}
$taskPython = Join-Path $taskData 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run Start PocketLens.cmd once to set up Python before allowing network access.' }
$taskBasePython = (& $taskPython -c 'import sys; print(sys._base_executable)').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not locate the Python runtime.' }
$taskName = 'PocketLens-LocalNetwork'
if (-not (Get-NetFirewallRule -Name $taskName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name $taskName -DisplayName 'PocketLens - local network only' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8764,8765 -RemoteAddress LocalSubnet -Profile Any | Out-Null
}
foreach ($taskEntry in @(@{Name='PocketLens-WebRTC';Program=$taskPython},@{Name='PocketLens-WebRTC-Base';Program=$taskBasePython})) {
    if (-not (Get-NetFirewallRule -Name $taskEntry.Name -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name $taskEntry.Name -DisplayName $taskEntry.Name -Direction Inbound -Action Allow -Protocol UDP -Program $taskEntry.Program -RemoteAddress LocalSubnet -Profile Any | Out-Null
    } else {
        Get-NetFirewallRule -Name $taskEntry.Name | Get-NetFirewallApplicationFilter | Set-NetFirewallApplicationFilter -Program $taskEntry.Program | Out-Null
    }
}
