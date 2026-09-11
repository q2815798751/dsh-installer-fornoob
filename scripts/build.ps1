# Build script: launcher exe -> payload -> one-click installer exe.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\build.ps1
#         [-SkipLauncher] [-SkipPayload] [-HarnessDir <dir>]
#         `-HarnessDir` points at a deepseek-harness checkout to pack. If it is
#         not supplied, the build uses the default local checkout or, failing
#         that, downloads and extracts the pinned harness release (see
#         $HARNESS_TAG below) so the bundle always ships the intended version.
param(
    [switch]$SkipLauncher,
    [switch]$SkipPayload,
    [string]$HarnessDir = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# The deepseek-harness release this installer ships. Keep these in sync:
#   $HARNESS_TAG     - the git tag to fetch when no local checkout exists
#   $HARNESS_VERSION - the exact "version" string expected in its package.json
#   HARNESS_COMMIT in installer\installer.py - that tag's commit, injected as
#     DSH_CLIENT_COMMIT_HASH at install time (the payload has no .git, and the
#     harness build script runs `git rev-parse HEAD` when the variable is unset)
$HARNESS_TAG = 'dsh-v0.1.5-rc.2'
$HARNESS_VERSION = '0.1.5-rc.2'
$DEFAULT_HARNESS_DIR = "C:\Users\$env:USERNAME\deepseek-harness"

$NODE_VERSION = '24.18.0'   # satisfies v0.1.5 engines (^22.19.0 || >=24.0.0)
$NODE_ZIP = Join-Path $root "payload\node-v$NODE_VERSION-win-x64.zip"

# 0) resolve the harness source tree -----------------------------------------
function Resolve-HarnessDir {
    if ($HarnessDir) {
        if (-not (Test-Path (Join-Path $HarnessDir 'package.json'))) {
            throw "-HarnessDir '$HarnessDir' has no package.json - not a harness checkout?"
        }
        Write-Host "==> Using harness from -HarnessDir: $HarnessDir"
        return $HarnessDir
    }
    if (Test-Path (Join-Path $DEFAULT_HARNESS_DIR 'package.json')) {
        Write-Host "==> Using harness from default dir: $DEFAULT_HARNESS_DIR"
        return $DEFAULT_HARNESS_DIR
    }
    # No local checkout: fetch the pinned release so the build is reproducible.
    Write-Host "==> No local harness checkout. Downloading deepseek-harness $HARNESS_TAG"
    $dest = Join-Path $root "payload\_harness-src"
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    $tar = Join-Path $dest 'harness.tar.gz'
    Invoke-WebRequest -Uri "https://codeload.github.com/deepseek-ai/deepseek-harness/tar.gz/refs/tags/$HARNESS_TAG" `
        -OutFile $tar -UseBasicParsing
    tar -xzf $tar -C $dest
    if ($LASTEXITCODE -ne 0) { throw "extracting harness failed" }
    $inner = Get-ChildItem -Directory $dest | Select-Object -First 1
    if (-not $inner) { throw "harness archive extracted to an empty directory" }
    return $inner.FullName
}

$HARNESS_SRC = Resolve-HarnessDir

# verify the tree we are about to pack is the version we intend to ship
$pkg = Join-Path $HARNESS_SRC 'package.json'
try {
    $actual = (Get-Content $pkg -Raw | ConvertFrom-Json).version
} catch { $actual = $null }
if ($actual -ne $HARNESS_VERSION) {
    Write-Warning "Harness at '$HARNESS_SRC' is version '$actual'; expected '$HARNESS_VERSION'."
    Write-Warning "Packing anyway. Double-check this is the release you want to bundle."
} else {
    Write-Host "==> Harness version OK: $actual"
}

# Up to 0.1.3 the harness depended on `fs-ext`, a node-gyp native addon that
# needs Visual Studio C++ plus a Windows SDK to install. No target machine has
# that, so such a payload installs for nobody. 0.1.5 replaced it with an
# in-repo addon, so this only trips if the tag is rolled back.
$fsExtHits = Select-String -Path (Join-Path $HARNESS_SRC 'packages\*\*\package.json') `
    -Pattern '"fs-ext"' -SimpleMatch -ErrorAction SilentlyContinue
if ($fsExtHits) {
    Write-Warning "Harness at '$HARNESS_SRC' still depends on fs-ext (native, needs MSVC)."
    Write-Warning "A payload packed from it will fail on machines without Visual Studio C++."
    Write-Warning "See the note in installer\installer.py about the pre-0.1.5 workaround."
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
    python (Join-Path $root "scripts\pack-repo.py") $out $HARNESS_SRC
    if ($LASTEXITCODE -ne 0) { throw "packing repo failed" }
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
Write-Host "Harness   : $HARNESS_VERSION ($HARNESS_TAG)"
Write-Host "Launcher : $root\launcher\dist\DSHLauncher.exe"
Write-Host "Installer: $final ($mb MB)"
