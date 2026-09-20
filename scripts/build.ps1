# Build script: launcher exe -> payload -> one-click installer exe.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\build.ps1
#         [-SkipLauncher] [-SkipPayload]
#
# There is no harness source to bundle any more: the installer pulls
# `@deepseek-ai/dsh` from npm at install time, which is the only distribution
# channel upstream actually publishes to.
param(
    [switch]$SkipLauncher,
    [switch]$SkipPayload
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# The portable Node the installer unpacks. Its npm is what installs the harness,
# so this version is load-bearing: v0.1.6 expects ^22.19.0 || >=24.0.0.
$NODE_VERSION = '24.18.0'
$NODE_ZIP = Join-Path $root "payload\node-v$NODE_VERSION-win-x64.zip"

# 1) launcher --------------------------------------------------------------
if (-not $SkipLauncher) {
    Write-Host "==> Building DSHLauncher.exe"
    Push-Location "$root\launcher"
    python -m PyInstaller --noconfirm --clean build\DSHLauncher.spec
    if ($LASTEXITCODE -ne 0) { throw "launcher build failed" }
    Pop-Location
}

# 2) payload ---------------------------------------------------------------
if (-not $SkipPayload) {
    if (-not (Test-Path $NODE_ZIP)) {
        Write-Host "==> Downloading portable Node.js v$NODE_VERSION"
        Invoke-WebRequest -Uri "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-win-x64.zip" `
            -OutFile $NODE_ZIP -UseBasicParsing
    } else {
        Write-Host "==> portable Node zip already present"
    }
}

# 3) installer -------------------------------------------------------------
Write-Host "==> Building DSHSetup.exe (one-click installer)"
Push-Location "$root\installer"
python -m PyInstaller --noconfirm --clean build\DSHSetup.spec
if ($LASTEXITCODE -ne 0) { throw "installer build failed" }
Pop-Location

$final = Join-Path $root "installer\dist\DSHSetup.exe"
if (-not (Test-Path $final)) { throw "installer exe not produced" }
$mb = [math]::Round((Get-Item $final).Length / 1MB, 1)
Write-Host ""
Write-Host "==== BUILD OK ===="
Write-Host "Harness  : @deepseek-ai/dsh@latest, installed from npm on the target"
Write-Host "Launcher : $root\launcher\dist\DSHLauncher.exe"
Write-Host "Installer: $final ($mb MB)"
