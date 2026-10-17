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

# Version resources: without them Properties shows no file version at
# all, which is what an unsigned dropper looks like.
python (Join-Path $root "scripts\make-version-info.py")
if ($LASTEXITCODE -ne 0) { throw "version info generation failed" }

# The portable Node the installer unpacks. Its npm is what installs the harness,
# so this version is load-bearing: v0.1.6 expects ^22.19.0 || >=24.0.0.
$NODE_VERSION = '24.18.0'
$NODE_ZIP = Join-Path $root "payload\node-v$NODE_VERSION-win-x64.zip"

# Expected SHA-256 of that zip. This is a PRE-FIXED constant, not something
# computed at build time: hashing the bytes we just downloaded and comparing
# them against a hash of those same bytes proves nothing. Anything that ends up
# embedded in DSHSetup.exe is verified against this value, both when reusing an
# already-present zip and after a fresh download.
#
# Source: the official checksum published at
#   https://nodejs.org/dist/v24.18.0/SHASUMS256.txt
#   -> "0ae68406b42d7725661da979b1403ec9926da205c6770827f33aac9d8f26e821  node-v24.18.0-win-x64.zip"
# Cross-checked on 2026-10-17 against the copy vendored under payload\ (same
# digest, 37,176,245 bytes) with Get-FileHash -Algorithm SHA256. Bump this
# constant whenever $NODE_VERSION changes, or the build will (correctly) refuse.
$NODE_ZIP_SHA256 = '0AE68406B42D7725661DA979B1403EC9926DA205C6770827F33AAC9D8F26E821'

function Test-FileSha256 {
    # Pure helper: $true only when $Path is a file whose SHA-256 equals
    # $Expected. Never throws for a missing file (returns $false instead).
    # Comparison is case-insensitive because hex casing differs between tools.
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Expected
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    return ($actual -ieq $Expected)
}

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
    # An already-present zip is only reusable if it still matches the pinned
    # digest; a stale or tampered file must not silently ride into the exe.
    if (Test-Path $NODE_ZIP) {
        if (Test-FileSha256 -Path $NODE_ZIP -Expected $NODE_ZIP_SHA256) {
            Write-Host "==> portable Node zip already present (sha256 verified)"
        } else {
            Write-Warning "existing portable Node zip failed its sha256 check; re-downloading"
            Remove-Item -LiteralPath $NODE_ZIP -Force
        }
    }

    if (-not (Test-Path $NODE_ZIP)) {
        Write-Host "==> Downloading portable Node.js v$NODE_VERSION"
        Invoke-WebRequest -Uri "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-win-x64.zip" `
            -OutFile $NODE_ZIP -UseBasicParsing
    }

    # Verify whatever we are about to embed against the pinned constant -- this
    # is the check that actually matters, since a fresh download is unverified.
    if (-not (Test-FileSha256 -Path $NODE_ZIP -Expected $NODE_ZIP_SHA256)) {
        throw "portable Node zip failed its sha256 check: expected $NODE_ZIP_SHA256 (see scripts\build.ps1 for the source of this value)"
    }
    Write-Host "==> portable Node zip sha256 verified against the pinned value"
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
