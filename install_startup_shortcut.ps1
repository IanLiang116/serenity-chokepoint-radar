$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = Join-Path $Root "start_serenity_radar.cmd"
$Startup = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $Startup "Serenity Chokepoint Radar.lnk"

if (-not (Test-Path $Target)) {
    Write-Host "Launcher not found: $Target"
    exit 1
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Target
$Shortcut.WorkingDirectory = $Root
$Shortcut.WindowStyle = 7
$Shortcut.Description = "Start local Serenity Chokepoint Radar"
$Shortcut.Save()

Write-Host "Created startup shortcut:"
Write-Host $ShortcutPath
Write-Host "Remove that shortcut to disable auto-start."
