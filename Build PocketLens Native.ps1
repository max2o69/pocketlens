param(
    [ValidateSet('x64', 'x86', 'all')][string]$Architecture = 'all',
    [string]$ToolchainRoot,
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'native\bin')
)
$ErrorActionPreference = 'Stop'
$taskVsDev = $null
if (-not $ToolchainRoot) {
    $taskVsWhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $taskVsWhere)) {
        throw 'Install Visual Studio 2022 Build Tools with Desktop development with C++ and the Windows SDK. See README.md.'
    }
    $taskVsPath = & $taskVsWhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $taskVsPath) { throw 'Visual Studio C++ tools were not found.' }
    $taskVsDev = Join-Path $taskVsPath 'Common7\Tools\VsDevCmd.bat'
}
$taskOutput = [IO.Path]::GetFullPath($OutputDirectory)
$taskSources = @()
foreach ($taskDirectory in @('baseclasses', 'softcamcore', 'softcam')) {
    $taskSources += Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot "native\src\$taskDirectory") -Filter '*.cpp' |
        Select-Object -ExpandProperty FullName
}
$taskArchitectures = if ($Architecture -eq 'all') { @('x64', 'x86') } else { @($Architecture) }
foreach ($taskArch in $taskArchitectures) {
    $taskBuild = Join-Path $PSScriptRoot "work\native-build\$taskArch"
    $taskBin = Join-Path $taskOutput $taskArch
    New-Item -ItemType Directory -Force -Path $taskBuild, $taskBin | Out-Null
    $taskSetup = if ($ToolchainRoot) { Join-Path $ToolchainRoot "setup_$taskArch.bat" } else { $taskVsDev }
    if (-not (Test-Path -LiteralPath $taskSetup)) { throw "Toolchain setup script missing: $taskSetup" }
    $taskSetupArgs = if ($ToolchainRoot) { '' } else { " -no_logo -host_arch=x64 -arch=$taskArch" }
    $taskFlags = @('/nologo', '/LD', '/O2', '/MT', '/EHsc', '/std:c++17', '/DWIN32', '/DUNICODE', '/D_UNICODE', '/DNDEBUG', '/D_CRT_SECURE_NO_WARNINGS',
        ('/I"' + (Join-Path $PSScriptRoot 'native\src') + '"'), ('/I"' + (Join-Path $PSScriptRoot 'native\src\baseclasses') + '"'))
    $taskFlags += $taskSources | ForEach-Object { '"' + $_ + '"' }
    $taskFlags += @('/link', ('/DEF:"' + (Join-Path $PSScriptRoot 'native\src\softcam\softcam.def') + '"'), ('/OUT:"' + (Join-Path $taskBin 'pocketlens.dll') + '"'), 'strmiids.lib', 'winmm.lib', 'kernel32.lib', 'user32.lib', 'gdi32.lib', 'advapi32.lib', 'ole32.lib', 'oleaut32.lib', 'uuid.lib')
    $taskResponse = Join-Path $taskBuild 'camera.rsp'
    # MSVC's /link applies to the rest of its line, including in a response file.
    Set-Content -LiteralPath $taskResponse -Value ($taskFlags -join ' ') -Encoding ASCII
    $taskRegisterResponse = Join-Path $taskBuild 'register.rsp'
    Set-Content -LiteralPath $taskRegisterResponse -Encoding ASCII -Value ('/nologo /MT /O2 /EHsc "' + (Join-Path $PSScriptRoot 'native\register-system.cpp') + '" /Fe"' + (Join-Path $taskBin 'register-system.exe') + '" /link advapi32.lib')
    $taskCommand = Join-Path $taskBuild 'build.cmd'
    Set-Content -LiteralPath $taskCommand -Encoding ASCII -Value @('@echo off', ('call "' + $taskSetup + '"' + $taskSetupArgs), 'if errorlevel 1 exit /b %errorlevel%', ('cl.exe @"' + $taskResponse + '"'), 'if errorlevel 1 exit /b %errorlevel%', ('cl.exe @"' + $taskRegisterResponse + '"'), 'exit /b %errorlevel%')
    Push-Location -LiteralPath $taskBuild
    try {
        & $env:ComSpec /d /c ('"' + $taskCommand + '"')
        if ($LASTEXITCODE -ne 0) { throw "Native $taskArch build failed." }
    } finally { Pop-Location }
    foreach ($taskArtifact in @('pocketlens.dll', 'register-system.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $taskBin $taskArtifact))) {
            throw "Build succeeded without producing $taskArtifact in $taskBin."
        }
    }
    Write-Host "Built $taskArch camera and registration helper: $taskBin"
}
