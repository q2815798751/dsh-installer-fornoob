# Build script: launcher exe -> payload -> one-click installer exe.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\build.ps1
#         [-SkipLauncher] [-SkipPayload]   (skip already-done steps)
param(
    [switch]$SkipLauncher,
    [switch]$SkipPayload
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

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
    Write-Host "==> Packing repo source -> payload\repo.tar.gz"
    $out = Join-Path $root "payload\repo.tar.gz"
    if (Test-Path $out) { Remove-Item $out -Force }
    tar -czf $out -C "C:\Users\sechen\deepseek-harness" `
        --exclude "*node_modules*" --exclude "*.git*" --exclude "launcher/build" `
        --exclude "launcher/data" --exclude "*__pycache__*" --exclude "*.pyc" `
        --exclude ".pnpm-store" --exclude "testhome*" .
    if ($LASTEXITCODE -ne 0) { throw "tar failed" }
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
Write-Host "Launcher : $root\launcher\dist\DSHLauncher.exe"
Write-Host "Installer: $final ($mb MB)"
