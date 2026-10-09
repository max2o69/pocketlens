function Get-PocketLensDataDirectory {
    if ($env:POCKETLENS_DATA_DIR) {
        return [IO.Path]::GetFullPath($env:POCKETLENS_DATA_DIR)
    }
    if ($env:LOCALAPPDATA) { return Join-Path $env:LOCALAPPDATA 'PocketLens' }
    if ($env:APPDATA) { return Join-Path $env:APPDATA 'PocketLens' }
    return Join-Path ([Environment]::GetFolderPath('UserProfile')) '.pocketlens'
}
