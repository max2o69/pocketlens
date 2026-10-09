param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$taskAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $taskAdmin) {
    $taskArguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$PSCommandPath+'"'))
    if ($Remove) { $taskArguments += '-Remove' }
    $taskElevated = Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList $taskArguments -Wait -PassThru
    exit $taskElevated.ExitCode
}
$taskDestinations = @((Join-Path $env:ProgramFiles 'PocketLens'))
if ($Remove) { $taskDestinations += Join-Path $env:ProgramFiles 'InterviewCamera' }
if (-not $Remove) {
    foreach ($taskArch in @('x64', 'x86')) {
        foreach ($taskFile in @('pocketlens.dll', 'register-system.exe')) {
            if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot "native\bin\$taskArch\$taskFile"))) {
                throw 'Native binaries are missing. Use the Windows release ZIP or run Build PocketLens Native.ps1.'
            }
        }
    }
}
$taskLog = Join-Path $PSScriptRoot 'pocketlens-system-install.log'
try {
    $taskAction = if ($Remove) {'remove'} else {'install'}
    foreach ($taskDestination in $taskDestinations) {
        $taskDllName = if ((Split-Path $taskDestination -Leaf) -eq 'PocketLens') { 'pocketlens.dll' } else { 'interview-camera.dll' }
        foreach ($taskArch in @('x64','x86')) {
            $taskTarget = Join-Path $taskDestination $taskArch
            if ($Remove -and -not (Test-Path -LiteralPath (Join-Path $taskTarget 'register-system.exe'))) { continue }
            if (-not $Remove) {
                New-Item -ItemType Directory -Force -Path $taskTarget | Out-Null
                Copy-Item -LiteralPath (Join-Path $PSScriptRoot "native\bin\$taskArch\pocketlens.dll") -Destination $taskTarget -Force
                Copy-Item -LiteralPath (Join-Path $PSScriptRoot "native\bin\$taskArch\register-system.exe") -Destination $taskTarget -Force
            }
            $taskOutput = & (Join-Path $taskTarget 'register-system.exe') $taskAction (Join-Path $taskTarget $taskDllName)
            if ($LASTEXITCODE -ne 0) { throw "$taskArch registration failed: $taskOutput" }
            Add-Content -LiteralPath $taskLog -Value "$taskArch $taskOutput"
        }
    }
    Add-Content -LiteralPath $taskLog -Value "SUCCESS: $taskAction $(Get-Date -Format o)"
} catch {
    Add-Content -LiteralPath $taskLog -Value "FAILED: $_"
    throw
}
