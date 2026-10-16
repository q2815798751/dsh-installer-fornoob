#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聚合自检入口 —— 一次跑完仓库里的自检脚本，给出汇总表。

    python scripts\\selfcheck.py
    python scripts\\selfcheck.py --list
    python scripts\\selfcheck.py --only updater
    python scripts\\selfcheck.py --only updater,linkcheck --quiet
    python scripts\\selfcheck.py --verbose --timeout 900

零依赖（只用标准库），不引入任何测试框架：每个自检脚本都是自研的
`check()` + 退出码风格，这里只负责「挨个跑、收退出码、收输出、汇总」。
退出码非 0 表示有 FAIL（SKIP 不算失败）。

跳过规则
--------
缺条件的用例标 SKIP 而不是 FAIL，并打印原因：

  * 需要 node 的（`installer\\test-linkcheck.py` 的实跑探针那一段）——本机
    没有 node 就整条跳过。可以用环境变量 `DSH_TEST_NODE` 指定 node 路径。
  * 需要桌面会话的（`launcher\\test-layout.py` 要起 tkinter）——无头环境下跳过，
    这是硬性规则 9 要求的：无桌面环境不算失败。
  * 需要联网的——目前这五个用例**都不需要**（`test-github-probe.py` 是刻意的
    离线自检，把 `_opener` 换成了假的）。这个能力仍然保留：本脚本是 AW-14 里
    CI 的入口，将来加的联网检查必须能跳过，而不是把 CI 判红。

⚠️ `launcher\\test-security.py` 以前**默认跳过**：它的第 5 项检查会真的运行一次
卸载脚本，而它依赖的 `restore_registry()` 在 `reg export` 失败时会静默不还原，
跑一次有概率删掉本机真实的卸载注册项
（`HKCU\\...\\Uninstall\\DeepSeekHarness`，本机**真实存在**）。
**AW-1 已修**：`reg export` 失败现在抛 `RegistryBackupError` 并中止（绝不再跑
卸载脚本），`reg import` 失败也会报错；第 0 段还用打桩自测了这两条。
所以这里**不再默认跳过**，`--allow-security` 开关也已删除。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# AW-1 已修完（test-security.py 的注册表护栏在备份失败时会中止、不再静默），
# 所以不再默认跳过。留这个常量只为「将来某个用例需要无条件跳过」时有个位置。
SECURITY_SKIP_REASON = None


class Case:
    """一个自检脚本。`requires` 里列出缺了就得跳过的条件。"""

    def __init__(self, name: str, relpath: str, desc: str,
                 requires: tuple[str, ...] = (), skip: str | None = None,
                 timeout: float = 900.0):
        self.name = name
        self.relpath = relpath
        self.desc = desc
        self.requires = requires
        self.skip = skip                  # 无条件跳过的原因（AW-1 之前给 security 用）
        self.timeout = timeout

    @property
    def path(self) -> str:
        return os.path.join(ROOT, self.relpath)


CASES: list[Case] = [
    Case("linkcheck", r"installer\test-linkcheck.py",
         "链接探测与失败归因（规则表 + 实跑探针）", requires=("node",)),
    Case("updater", r"launcher\test-updater.py",
         "更新回滚（六条路径 + 启动器自更新换文件）"),
    Case("security", r"launcher\test-security.py",
         "安全回归（下载校验 / 不用 PATH node / 绝对路径 / 只杀 node.exe / 卸载守卫）",
         skip=SECURITY_SKIP_REASON),
    Case("github-probe", r"launcher\test-github-probe.py",
         "GitHub 延迟/测速探针的离线自检（不联网）"),
    Case("layout", r"launcher\test-layout.py",
         "环境检查页布局（离屏渲染，找共享像素的兄弟控件）", requires=("desktop",)),
]

BY_NAME = {c.name: c for c in CASES}


# --------------------------------------------------------------------------
# 条件探测：返回 "" 表示可用，否则返回一句人话原因
# --------------------------------------------------------------------------
def _why_no_node() -> str:
    node = os.environ.get("DSH_TEST_NODE") or shutil.which("node")
    if not node:
        return "PATH 里没有 node，也没有设 DSH_TEST_NODE"
    if not os.path.exists(node):
        return "DSH_TEST_NODE 指向的 %s 不存在" % node
    return ""


def _why_no_desktop() -> str:
    try:
        import tkinter as tk
    except Exception as exc:                      # noqa: BLE001
        return "没有 tkinter（%s）" % exc.__class__.__name__
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
    except Exception as exc:                      # noqa: BLE001
        return "起不了 Tk（%s: %s）" % (exc.__class__.__name__, exc)
    return ""


def _why_no_network() -> str:
    import socket
    try:
        socket.create_connection(("registry.npmjs.org", 443), timeout=5).close()
    except OSError as exc:
        return "连不上 registry.npmjs.org:443（%s）" % exc
    return ""


REQUIREMENTS = {"node": _why_no_node, "desktop": _why_no_desktop,
                "network": _why_no_network}


def skip_reason(case: Case) -> str:
    """"" = 可以跑；否则是跳过原因。"""
    if case.skip:
        return case.skip
    for need in case.requires:
        why = REQUIREMENTS[need]()
        if why:
            return "需要 %s：%s" % (need, why)
    return ""


# --------------------------------------------------------------------------
# 跑
# --------------------------------------------------------------------------
def run_case(case: Case) -> dict:
    started = time.time()
    result = {"name": case.name, "status": "FAIL", "seconds": 0.0,
              "reason": "", "exit": None, "output": ""}

    if not os.path.isfile(case.path):
        result["reason"] = "脚本不存在：%s" % case.relpath
        return result

    env = dict(os.environ)
    # 子进程统一吐 UTF-8，免得在 cp936 控制台上把中文输出变成乱码。
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, case.path], cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            timeout=case.timeout)
    except subprocess.TimeoutExpired as exc:
        result["seconds"] = time.time() - started
        result["reason"] = "超时（>%gs）" % case.timeout
        result["output"] = (exc.output or "") if isinstance(exc.output, str) else ""
        return result

    result["seconds"] = time.time() - started
    result["exit"] = proc.returncode
    result["output"] = proc.stdout or ""
    if proc.returncode == 0:
        result["status"] = "PASS"
    else:
        result["reason"] = "退出码 %d" % proc.returncode
    return result


def run_selected(cases: list[Case], quiet: bool, verbose: bool) -> list[dict]:
    rows: list[dict] = []
    for case in cases:
        why = skip_reason(case)
        print("\n" + "=" * 72)
        print(">> %s  (%s)" % (case.name, case.relpath))
        print("   %s" % case.desc)
        print("=" * 72)
        if why:
            print("SKIP  %s" % why)
            rows.append({"name": case.name, "status": "SKIP", "seconds": 0.0,
                         "reason": why, "exit": None, "output": ""})
            continue
        row = run_case(case)
        rows.append(row)
        if row["output"] and (verbose or not quiet or row["status"] == "FAIL"):
            sys.stdout.write(row["output"])
            if not row["output"].endswith("\n"):
                sys.stdout.write("\n")
        if row["status"] == "FAIL" and quiet and not row["output"]:
            print("FAIL  %s" % row["reason"])
        print("--> %s  %.1fs%s" % (row["status"], row["seconds"],
                                   ("  (%s)" % row["reason"]) if row["reason"] else ""))
    return rows


def summarize(rows: list[dict]) -> int:
    print("\n" + "=" * 72)
    print("汇总")
    print("=" * 72)
    print("%-14s %-6s %8s  %s" % ("用例", "状态", "用时", "说明"))
    for row in rows:
        print("%-14s %-6s %7.1fs  %s" % (row["name"], row["status"], row["seconds"],
                                         row["reason"]))
    passed = sum(1 for r in rows if r["status"] == "PASS")
    failed = [r["name"] for r in rows if r["status"] == "FAIL"]
    skipped = sum(1 for r in rows if r["status"] == "SKIP")
    print("-" * 72)
    print("%d 项：%d 通过，%d 失败，%d 跳过" % (len(rows), passed, len(failed), skipped))
    if failed:
        print("失败：%s" % ", ".join(failed))
        return 1
    return 0


# --------------------------------------------------------------------------
def write_json(path: str, rows: list[dict]) -> None:
    payload = {
        "when": _dt.datetime.now().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "cases": [{k: r[k] for k in ("name", "status", "seconds", "reason", "exit")}
                  for r in rows],
        "summary": {
            "total": len(rows),
            "passed": sum(1 for r in rows if r["status"] == "PASS"),
            "failed": sum(1 for r in rows if r["status"] == "FAIL"),
            "skipped": sum(1 for r in rows if r["status"] == "SKIP"),
        },
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def select(only: str | None) -> list[Case]:
    if not only:
        return list(CASES)
    wanted = [n.strip() for n in only.split(",") if n.strip()]
    unknown = [n for n in wanted if n not in BY_NAME]
    if unknown:
        raise SystemExit("--only 不认识：%s\n可用：%s"
                         % (", ".join(unknown), ", ".join(BY_NAME)))
    return [BY_NAME[n] for n in wanted]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="聚合自检入口：挨个跑自检脚本，最后给汇总表。")
    ap.add_argument("--only", metavar="NAME[,NAME...]",
                    help="只跑指定的用例（%s）" % ", ".join(BY_NAME))
    ap.add_argument("--list", action="store_true", help="只列出用例，不跑")
    ap.add_argument("--quiet", action="store_true",
                    help="只在失败时打印子进程输出")
    ap.add_argument("--verbose", action="store_true", help="总是打印完整输出")
    ap.add_argument("--timeout", type=float, default=900.0,
                    help="单个用例的超时秒数（默认 900）")
    ap.add_argument("--json", metavar="PATH", default=os.path.join(ROOT, "selfcheck.json"),
                    help="把机器可读的汇总写到 PATH（默认 selfcheck.json）")
    ap.add_argument("--no-json", action="store_true", help="不写 JSON 汇总")
    args = ap.parse_args(argv)

    if args.list:
        for case in CASES:
            why = skip_reason(case)
            print("%-14s %-34s %s" % (case.name, case.relpath,
                                      ("SKIP: " + why) if why else ""))
        return 0

    cases = select(args.only)
    for case in cases:
        if args.timeout != 900.0:
            case.timeout = args.timeout

    print("聚合自检：%d 个用例，仓库根 %s" % (len(cases), ROOT))
    rows = run_selected(cases, args.quiet, args.verbose)
    code = summarize(rows)
    if not args.no_json:
        try:
            write_json(args.json, rows)
            print("机器可读汇总：%s" % args.json)
        except OSError as exc:
            print("写 JSON 汇总失败（不影响退出码）：%s" % exc)
    return code


if __name__ == "__main__":
    sys.exit(main())
