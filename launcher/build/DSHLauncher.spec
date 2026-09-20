# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for DSHLauncher.exe (windowed, no console, tray-capable).
# Usage:  pyinstaller build\DSHLauncher.spec  (from the launcher/ directory)

import os

root = os.path.abspath(os.path.join(SPECPATH, ".."))   # the launcher/ directory

a = Analysis(
    [os.path.join(root, "launcher.pyw")],
    pathex=[root],
    binaries=[],
    # icon.ico drives the exe/shortcut/tray; logo.png is the whale mark the
    # panel header draws (Tk reads PNG natively, so no image library is needed
    # at runtime).
    datas=[(os.path.join(root, "icon.ico"), "."),
           (os.path.join(root, "logo.png"), ".")],
    # updater.py / update_ui.py are local modules next to launcher.pyw; naming
    # them keeps them in the bundle even if an import is ever made lazily.
    hiddenimports=["updater", "update_ui"],
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
    version=os.path.join(root, "build", "version_info.txt"),
    icon=[os.path.join(root, "icon.ico")],
)
