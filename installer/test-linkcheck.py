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


def _cell(state: str) -> dict:
    return {"junction": state, "junction_errno": 0 if state == "ok" else -4048,
            "symlink_dir": "fail", "symlink_dir_errno": -4048}


def _report(junction: str, mklink: str = "ok", status: str = "ran",
            home: str = "ok", install: str = "ok", tmp: str = "ok",
            volumes: dict | None = None) -> dict:
    """Four-cell report. `junction` is the primary (home -> install volume)."""
    return {
        "status": status, "reason": "", "node": "24.18.0", "mklink_j": mklink,
        "home": r"C:\Users\x\.dsh",
        "volumes": volumes or {"install": "D:", "home": "C:", "tmp": "C:",
                               "same_as_home": False, "home_is_unc": False},
        "cells": {
            "home_to_install": _cell(junction),
            "home_to_home": _cell(home),
            "tmp_to_install": _cell(install),
            "tmp_to_tmp": _cell(tmp),
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
    t = _text(linkcheck.diagnose(EPERM_SMOKE, _report("fail", mklink="fail",
                                                      home="fail", tmp="fail"),
                                 error="RuntimeError('试运行时进程退出了 (exit 1)')",
                                 step="正在试运行…", target=r"D:\deepseek",
                                 harness_version="0.1.5-rc.2", smoke_exists=True))
    check("哪儿都建不了 -> 指认不是权限问题", "不是「权限不够」" in t, t)
    check("哪儿都建不了 -> 提到组策略", "组策略" in t, t)
    check("哪儿都建不了 -> 明确说管理员运行无用", "用管理员身份运行解决不了" in t, t)
    check("诊断块带三态矩阵", "home_to_install-junction=FAIL(-4048)" in t, t)
    check("诊断块给出链接形状", "链接形状:" in t, t)
    check("诊断块说明已装好可复用", "不会重下 600 MB" in t, t)
    check("诊断块提醒 smoke.log 含令牌", "只发 install.log" in t, t)

    # ---- attribution: which of the three causes ---------------------------
    def cause_of(**kw) -> tuple:
        return linkcheck.verdict(_report(**kw)) or ("", "")

    c, advice = cause_of(junction="fail", home="fail", tmp="fail")
    check("哪里都失败 -> machine", c == "machine", c)
    check("machine 结论指向策略/杀软", "创建符号链接" in advice and "安全软件" in advice, advice)
    check("machine 结论不劝人换安装目录", "换一个" not in advice, advice)

    c, advice = cause_of(junction="fail", home="fail", tmp="ok",
                         volumes={"install": "D:", "home": "C:", "tmp": "C:",
                                  "same_as_home": False, "home_is_unc": True})
    check(".dsh 位置不行 -> home", c == "home", c)
    check("home 结论点名 .dsh 位置与重定向", ".dsh" in advice and "重定向" in advice, advice)
    check("home 结论不甩锅给组策略", "组策略" not in advice, advice)
    check("home 结论不提 DSH_HOME（本期无此能力）", "DSH_HOME" not in advice, advice)

    c, advice = cause_of(junction="fail", home="ok", tmp="ok", install="fail")
    check("只有安装卷不行 -> install", c == "install", c)
    check("install 结论劝换安装目录并点名文件系统", "换一个" in advice and "exFAT" in advice, advice)
    check("install 结论不提提权", "管理员" not in advice, advice)
    check("install 结论带上安装盘", "D:" in advice, advice)

    c, advice = cause_of(junction="fail", home="ok", tmp="ok", install="ok")
    check("单独都能建、组合不行 -> combination", c == "combination", c)

    check("主格正常 -> 没有结论", linkcheck.verdict(_report("ok")) is None)
    check("探针没跑 -> 没有结论", linkcheck.verdict(_report("fail", status="unavailable")) is None)

    # A needed cell unknown must not be read as a cause.
    c, _ = cause_of(junction="fail", home="unknown", tmp="fail")
    check("点名格子未知 -> 不下结论", c == "inconclusive", c)
    c, _ = cause_of(junction="fail", home="ok", tmp="fail")
    check("TEMP 失败但 .dsh 正常 -> 不下结论", c == "inconclusive", c)

    # ---- the invariant that keeps this from blocking a working machine ----
    states = ("ok", "fail", "unknown")
    bad: list[str] = []
    blocked_wrong: list[str] = []
    for p in states:
        for h in states:
            for x in states:
                for tt in states:
                    rep = _report(p, home=h, install=x, tmp=tt)
                    try:
                        linkcheck.verdict(rep)
                        for text in linkcheck.diagnose(EPERM_SMOKE, rep):
                            linkcheck.redact(text)
                    except Exception as exc:  # noqa: BLE001
                        bad.append("%s/%s/%s/%s -> %r" % (p, h, x, tt, exc))
                    want = (p == "fail")
                    got = linkcheck.blocking_message(rep) is not None
                    if got != want:
                        blocked_wrong.append("%s/%s/%s/%s" % (p, h, x, tt))
    check("81 种组合都不抛异常", not bad, "; ".join(bad[:3]))
    check("只有主格失败才阻断安装（其余格子只影响措辞）", not blocked_wrong,
          ",".join(blocked_wrong[:5]))

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

    # ---- the administrator suggestion ------------------------------------
    def sug(text, rep, elevated=False):
        return linkcheck.admin_suggestion(text, rep, elevated=elevated)

    check("链接失败 -> 不提管理员（提了也没用，还会自相矛盾）",
          sug(EPERM_SMOKE, _report("fail", mklink="fail")) is None)
    check("已经提权 -> 不提管理员", sug(EPERM_SMOKE, _report("ok"), elevated=True) is None)
    check("权限类失败 -> 建议管理员", "以管理员身份运行" in (sug(
        "Error: EPERM: operation not permitted, open 'D:\\x\\y'", _report("ok")) or ""))
    check("网络失败 -> 不提管理员", sug(NET_SMOKE, _report("ok")) is None)
    check("磁盘满 -> 不提管理员", sug("Error: ENOSPC: no space left on device", _report("ok")) is None)
    check("node 起不来（疑似被杀软隔离）-> 建议管理员",
          "以管理员身份运行" in (sug("", _report("ok")) or ""))

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
