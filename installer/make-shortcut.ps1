# Creates a Windows shortcut (.lnk) with the given parameters.
# ASCII-only source (the default Chinese display name is built from code
# points to dodge PowerShell 5.1 UTF-8-without-BOM misreading).
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File make-shortcut.ps1
#         -LnkPath <path> -TargetPath <exe> [-Arguments ...] [-IconPath ...]
#         [-WorkingDirectory ...] [-Description ...]
param(
    [string]$LnkPath = '',
    [string]$TargetPath = '',
    [string]$Arguments = '',
    [string]$IconPath = '',
    [string]$WorkingDirectory = '',
    [string]$Description = ''
)
$ErrorActionPreference = 'Stop'

if (-not $LnkPath) {
    # "DSH 启动器" — 启(0x542F) 动(0x52A8) 器(0x5668)
    $name = 'DSH ' + [char]0x542F + [char]0x52A8 + [char]0x5668
    $LnkPath = Join-Path ([Environment]::GetFolderPath('Desktop')) ($name + '.lnk')
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($LnkPath)
if ($TargetPath) { $shortcut.TargetPath = $TargetPath }
if ($Arguments) { $shortcut.Arguments = $Arguments }
if ($IconPath) { $shortcut.IconLocation = "$IconPath,0" }
if ($WorkingDirectory) { $shortcut.WorkingDirectory = $WorkingDirectory }
if ($Description) { $shortcut.Description = $Description }
$shortcut.Save()

Write-Host "OK: $LnkPath"
