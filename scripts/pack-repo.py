#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pack a deepseek-harness checkout into payload/repo.tar.gz.

Used by scripts\\build.ps1 (which previously called GNU tar directly; on Git
Bash that binary mis-parses Windows drive paths like C:\\... as a remote host,
so we build the archive with Python's tarfile instead).

Excludes mirror the old `tar ... --exclude ...` list:
    *node_modules*, *.git*, launcher/build, launcher/data,
    *__pycache__*, *.pyc, *.pyo, .pnpm-store, testhome*

Usage (build.ps1 calls this with two absolute paths):
    python scripts\\pack-repo.py <output.tar.gz> <harness-src-dir>
"""
from __future__ import annotations

import os
import sys
import tarfile

SUFFIX = {".pyc", ".pyo"}
SUBSTR = ("node_modules", "__pycache__")
EXACT = {"launcher/build", "launcher/data", ".pnpm-store"}


def _skip(rel: str) -> bool:
    parts = rel.split("/")
    if any(p in EXACT for p in parts):
        return True
    if any(s in rel for s in SUBSTR):
        return True
    if "testhome" in rel:
        return True
    # `*.git*`: drop the git dir and .git* metadata (no submodules expected).
    if any(p == ".git" or p.startswith(".git") for p in parts):
        return True
    if rel.endswith(tuple(SUFFIX)):
        return True
    return False


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: pack-repo.py <output.tar.gz> <harness-src-dir>", file=sys.stderr)
        return 2
    out, src = sys.argv[1], sys.argv[2]
    if not os.path.isdir(src):
        print("error: not a directory: %s" % src, file=sys.stderr)
        return 2
    count = 0
    with tarfile.open(out, "w:gz") as tf:
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if not (d == ".git" or d.startswith(".git"))]
            for f in files:
                p = os.path.join(root, f)
                rel = os.path.relpath(p, src).replace(os.sep, "/")
                if _skip(rel):
                    continue
                try:
                    tf.add(p, arcname=rel)
                    count += 1
                except (OSError, PermissionError):
                    pass
    print("packed %d entries -> %s (%d bytes)" % (count, out, os.path.getsize(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
