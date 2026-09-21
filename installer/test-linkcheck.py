#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Self-check for linkcheck: the diagnosis rules, plus one real probe run.

    python installer\\test-linkcheck.py

The EPERM sample below is a verbatim copy of a real failure (2026-09-21, a
Windows 10 machine where dsh's own profile link could not be created), which is
what the rules exist to explain. The probe half needs a node binary: it takes
DSH_TEST_NODE, else whatever `node` is on PATH (test-only — the installer itself
never does that), and skips that half if neither exists.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import linkcheck

# Verbatim from the failing machine's smoke.log.
EPERM_SMOKE = """
node:fs:1877
  binding.symlink(
          ^

Error: EPERM: operation not permitted, symlink 'D:\\deepseek\\harness\\node_modules\\@deepseek-ai\\dsh' -> 'C:\\Users\\Administrator\\.dsh\\profiles\\node_modules\\@deepseek-ai\\dsh'
    at symlinkSync (node:fs:1877:11)
    at ensureSymlink (file:///D:/deepseek/harness/node_modules/@deepseek-ai/dsh-app-boot/lib/index.js:426:3)
    at healProfilesModuleFallbackLocked (file:///D:/deepseek/harness/node_modules/@deepseek-ai/dsh-app-boot/lib/index.js:674:8)
    at withFileLock (file:///D:/deepseek/harness/node_modules/@deepseek-ai/dsh-atomic-write/lib/index.js:141:16)
    at async composeProfile (file:///D:/deepseek/harness/node_modules/@deepseek-ai/dsh/lib/profile-boot-Dk-7KqJc.js:234:2) {
  errno: -4048,
  code: 'EPERM',
  syscall: 'symlink',
  path: 'D:\\deepseek\\harness\\node_modules\\@deepseek-ai\\dsh',
  dest: 'C:\\Users\\Administrator\\.dsh\\profiles\\node_modules\\@deepseek-ai\\dsh'
}

Node.js v24.18.0
"""

NET_SMOKE = """
npm error code ETIMEDOUT
npm error errno ETIMEDOUT
npm error network request to https://registry.npmjs.org/@deepseek-ai%2fdsh failed
dsh web: http://127.0.0.1:3198/?token=AbC-123_xyz
"""


def _report(junction: str, mklink: str = "ok", status: str = "ran") -> dict:
    return {
        "status": status, "reason": "", "node": "24.18.0", "mklink_j": mklink,
        "home": r"C:\Users\x\.dsh",
        "cells": {
            "home_to_install": {"junction": junction, "junction_errno": 0 if junction == "ok" else -4048,
                                "symlink_dir": "fail", "symlink_dir_errno": -4048},
            "tmp_to_tmp": {"junction": "ok", "symlink_dir": "fail", "symlink_dir_errno": -4048},
        },
    }


def _text(lines: list[str]) -> str:
    return "\n".join(lines)


def main() -> int:
    failures: list[str] = []

    def check(label: str, condition: bool, extra: str = "") -> None:
        print("%-4s %s%s" % ("ok" if condition else "FAIL", label, ("  <- " + extra) if extra and not condition else ""))
        if not condition:
            failures.append(label)

    # ---- rules -----------------------------------------------------------
    t = _text(linkcheck.diagnose(EPERM_SMOKE, _report("fail", mklink="fail"),
                                 error="RuntimeError('试运行时进程退出了 (exit 1)')",
                                 step="正在试运行…", target=r"D:\deepseek",
                                 harness_version="0.1.5-rc.2", smoke_exists=True))
    check("EPERM + junction 也失败 -> 指认不是权限问题", "不是「权限不够」" in t, t)
    check("EPERM + junction 也失败 -> 提到组策略", "组策略" in t, t)
    check("EPERM + junction 也失败 -> 明确说管理员运行无用", "管理员身份运行不会有帮助" in t, t)
    check("诊断块带三态矩阵", "home_to_install-junction=FAIL(-4048)" in t, t)
    check("诊断块说明已装好可复用", "不会重下 600 MB" in t, t)
    check("诊断块提醒 smoke.log 含令牌", "只发 install.log" in t, t)

    t = _text(linkcheck.diagnose(EPERM_SMOKE, _report("ok")))
    check("EPERM 但 junction 正常 -> 不甩锅给机器权限", "不是「权限不够」" not in t and "通用链接能力没问题" in t, t)

    t = _text(linkcheck.diagnose(EPERM_SMOKE, _report("fail", mklink="ok")))
    check("mklink 能建而 node 不能 -> 指向专门 hook node", "专门拦 node.exe" in t, t)

    t = _text(linkcheck.diagnose("", _report("fail")))
    check("smoke.log 为空 -> 走「进程没输出」而不是链接结论", "没有任何输出" in t and "组策略" not in t, t)

    t = _text(linkcheck.diagnose(NET_SMOKE, _report("ok")))
    check("网络错误 -> 不提链接问题", "失败在网络上" in t, t)

    check("脱敏 token", "token=<redacted>" in linkcheck.redact(NET_SMOKE)
          and "AbC-123_xyz" not in linkcheck.redact(NET_SMOKE))

    # ---- unknown must never block ---------------------------------------
    dead = {"status": "unavailable", "reason": "timed out after 15s", "cells": {}, "mklink_j": "unknown"}
    check("探针没跑起来 -> 渲染成 UNKNOWN", "UNKNOWN" in linkcheck.render(dead)
          and "timed out" in linkcheck.render(dead))
    check("探针没跑起来 -> 不阻断安装", linkcheck.blocking_message(dead) is None)
    check("junction 正常 -> 不阻断安装", linkcheck.blocking_message(_report("ok")) is None)
    check("junction 失败 -> 阻断并给出解释", bool(linkcheck.blocking_message(_report("fail"))))

    # ---- a real probe run ------------------------------------------------
    node = os.environ.get("DSH_TEST_NODE") or shutil.which("node")
    if not node:
        print("---- 没有 node 可测，跳过实跑探针（设 DSH_TEST_NODE 指定）")
    else:
        with tempfile.TemporaryDirectory(prefix="dsh-linkprobe-test-") as tmp:
            rep = linkcheck.probe(node, tmp)
            line = linkcheck.render(rep)
            print("probe: %s" % line)
            check("实跑探针拿到结果", rep["status"] == "ran", rep.get("reason", ""))
            check("实跑：node 能建 junction", linkcheck.cell_state(rep, "home_to_install") == "ok", line)
            cell = (rep.get("cells") or {}).get("home_to_install") or {}
            check("实跑：symlink-dir 失败且是 -4048（这台机器的正常状态）",
                  cell.get("symlink_dir") == "fail" and cell.get("symlink_dir_errno") == -4048, line)
            check("实跑后不留垃圾", not any(
                os.path.exists(os.path.join(tmp, n)) for n in (".dsh-linkprobe-src",)))

    print("\n%s" % ("ALL OK" if not failures else "%d FAILED: %s" % (len(failures), failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
