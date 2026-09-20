#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Write the Windows VERSIONINFO resource files PyInstaller embeds.

Without these the exes have no CompanyName / ProductName / FileVersion at
all: Properties shows "文件版本: 无", which is what an unsigned dropper looks
like, and both SmartScreen and Defender's heuristics weigh it.

Version comes from launcher/launcher.pyw so there is one source of truth.
    python scripts/make-version-info.py
"""
from __future__ import annotations

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TARGETS = {
    "launcher/build/version_info.txt": (
        "DSHLauncher.exe", "DSH 面板"),
    "installer/build/version_info.txt": (
        "DSHSetup.exe", "DSH 一键安装程序"),
}

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v0}, {v1}, {v2}, 0),
    prodvers=({v0}, {v1}, {v2}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'DSH'),
         StringStruct('FileDescription', '{desc}'),
         StringStruct('FileVersion', '{version}'),
         StringStruct('InternalName', '{name}'),
         StringStruct('LegalCopyright', 'MIT License'),
         StringStruct('OriginalFilename', '{name}'),
         StringStruct('ProductName', 'DSH'),
         StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> int:
    src = open(os.path.join(ROOT, "launcher", "launcher.pyw"), encoding="utf-8").read()
    version = re.search(r'^VERSION = "([^"]+)"', src, re.M).group(1)
    parts = [int(p) for p in re.match(r"(\d+)\.(\d+)\.(\d+)", version).groups()]
    print("version: %s" % version)
    for rel, (name, desc) in TARGETS.items():
        path = os.path.join(ROOT, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(TEMPLATE.format(v0=parts[0], v1=parts[1], v2=parts[2],
                                    version=version, name=name, desc=desc))
        print("  -> %s" % rel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
