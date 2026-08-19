# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for DSHLauncher.exe (windowed, no console, tray-capable).
# Usage:  pyinstaller build\DSHLauncher.spec  (from the launcher/ directory)

import os

root = os.path.abspath(os.path.join(SPECPATH, ".."))   # the launcher/ directory

a = Analysis(
    [os.path.join(root, "launcher.pyw")],
    pathex=[root],
    binaries=[],
    datas=[(os.path.join(root, "icon.ico"), ".")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DSHLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(root, "icon.ico")],
)
