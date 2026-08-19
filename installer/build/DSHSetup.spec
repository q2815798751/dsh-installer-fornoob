# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the one-click installer DSHSetup.exe.
# The whole payload (repo source + portable Node + launcher exe + icon +
# shortcut script) is embedded; nothing is downloaded at install time except
# the npm dependencies themselves.
# Usage:  pyinstaller build\DSHSetup.spec   (from the installer/ directory)

import os

root = os.path.abspath(os.path.join(SPECPATH, "..", ".."))     # project root
payload = os.path.join(root, "payload")

datas = [
    (os.path.join(payload, "repo.tar.gz"), "."),
    (os.path.join(payload, "node-v24.18.0-win-x64.zip"), "."),
    (os.path.join(root, "launcher", "dist", "DSHLauncher.exe"), "."),
    (os.path.join(root, "launcher", "icon.ico"), "."),
    (os.path.join(root, "installer", "make-shortcut.ps1"), "."),
]

a = Analysis(
    [os.path.join(root, "installer", "installer.py")],
    pathex=[os.path.join(root, "installer")],
    binaries=[],
    datas=datas,
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
    name="DSHSetup",
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
    icon=[os.path.join(root, "launcher", "icon.ico")],
)
