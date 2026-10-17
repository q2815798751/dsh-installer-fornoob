#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""备份 / 还原 DSH 的卸载注册项与快捷方式清单 —— 动卸载逻辑之前的护栏。

    python scripts\\backup-dsh-registry.py                 # 备份一份
    python scripts\\backup-dsh-registry.py --list          # 看已有的备份
    python scripts\\backup-dsh-registry.py --restore       # 从最新一份还原
    python scripts\\backup-dsh-registry.py --restore scripts\\backups\\20261016-231500

备份两样东西（本机 DSH 真的装在 `C:\\Users\\sechen\\deepseek`）：

  * `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DeepSeekHarness`
    —— 用 `reg export` 导出成 `.reg`；
  * `<安装目录>\\shortcuts.txt` —— 快捷方式清单（卸载脚本照它删快捷方式）。

每份备份落在 `<脚本目录>\\backups\\<时间戳>\\`，里面除上面两样还有一份
`manifest.json`（记录源路径、字节数、sha256）。**还原时真的会照着它核对**：
`reg import` / 文件复制**之前**先按 manifest 校验每个备份文件的字节数与 sha256，
对不上就中止、rc 非 0、不做任何改动（AW-15a —— 以前这句是空话，篡改后的
`.reg` 照样会被导进去）。还原前给当前状态拍的 `*-prerestore` 快照若导出失败，
也**立即中止**，绝不在没有安全网的情况下还原（AW-15b）。

为什么需要它
------------
`launcher\\test-security.py` 的第 5 项检查会真的运行一次卸载脚本，而卸载脚本会删
掉上面那个注册项；它的还原步骤在 `reg export` 失败时会**静默不还原**（AW-1 要修的
就是这处）。本机那个键是真实存在的，所以任何动卸载逻辑的验证之前都先跑一次本脚本。
本脚本是**只读 + 导入**的：只做 `reg export` / `reg query` / `reg import` 和文件复制，
**不会运行 `uninstall.bat`，不会 `reg delete` 任何东西，不碰 `%USERPROFILE%\\.dsh`**。

注：这里全程用 `subprocess` 传参数列表（不经 shell），所以 Git Bash 里那个
`MSYS_NO_PATHCONV=1` 的坑（`/y` `/v` 被当成路径转掉）在这条路径上不存在。

`--reg-key` 一般不用改：它存在只是为了能把「备份→改坏→还原」这条链路拿一个一次性
的临时键完整验证一遍，而**不必**去写本机那个真实的卸载键。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")

REG_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSeekHarness"
DEFAULT_INSTALL_DIR = r"C:\Users\sechen\deepseek"
REG_FILE = "uninstall-DeepSeekHarness.reg"
SHORTCUTS_FILE = "shortcuts.txt"
MANIFEST = "manifest.json"

# reg.exe 走绝对路径：项目里所有系统命令都不经过 PATH 解析（README「安全」一节）。
_NO_WINDOW = 0x08000000


def _sys(name: str) -> str:
    return os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", name)


def _reg(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([_sys("reg.exe"), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          creationflags=_NO_WINDOW)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _verify_backup_file(path: str, entry: dict) -> tuple[bool, str]:
    """按 manifest 里记的字节数与 sha256 校验一个备份文件。返回 (ok, 原因)。

    这是 AW-15(a)：以前 `do_restore` **从不**核对 manifest，把 `.reg` 篡改掉
    （语法仍合法）也能照样 `reg import` 进去。这里把校验抽成纯函数，
    还原前对每个存在的备份文件都过一遍，对不上就中止、不做任何改动。
    """
    if not os.path.isfile(path):
        return False, "备份文件缺失：%s" % path
    size = os.path.getsize(path)
    if size == 0:
        return False, "备份文件为空：%s" % path
    want_bytes = entry.get("bytes")
    if isinstance(want_bytes, int) and size != want_bytes:
        return False, ("字节数不符：manifest 记 %d，实际 %d" % (want_bytes, size))
    want_sha = (entry.get("sha256") or "").strip().lower()
    if want_sha:
        got = _sha256(path).lower()
        if got != want_sha:
            return False, ("sha256 不符：manifest 记 %s…，实际 %s…"
                           % (want_sha[:12], got[:12]))
    return True, ""


def _fresh_dir(parent: str, name: str) -> str:
    """`parent/name`，重名就补 -2 / -3，避免同一秒里的两次备份互相覆盖。"""
    dest, n = os.path.join(parent, name), 2
    while os.path.exists(dest):
        dest = os.path.join(parent, "%s-%d" % (name, n))
        n += 1
    os.makedirs(dest)
    return dest


# --------------------------------------------------------------------------
# 备份
# --------------------------------------------------------------------------
def do_backup(dest: str, install_dir: str, reg_key: str = REG_KEY) -> dict:
    """把注册项与 shortcuts.txt 备份到 `dest`，返回 manifest（也写进 dest）。

    `reg_key` 只是为了能拿一个一次性的临时键来验证这条链路（见文件头）；默认就是
    真实的那个卸载键。
    """
    os.makedirs(dest, exist_ok=True)
    manifest = {"when": _dt.datetime.now().isoformat(timespec="seconds"),
                "install_dir": install_dir, "registry_key": reg_key,
                "registry": {}, "shortcuts": {}}

    # --- 注册项 ---
    query = _reg("query", reg_key)
    if query.returncode != 0:
        manifest["registry"] = {"present": False,
                                "note": "注册项不存在（没有可丢的东西）"}
        print("注册项：不存在（%s）" % reg_key)
    else:
        reg_path = os.path.join(dest, REG_FILE)
        exported = _reg("export", reg_key, reg_path, "/y")
        ok = (exported.returncode == 0 and os.path.isfile(reg_path)
              and os.path.getsize(reg_path) > 0)
        if not ok:
            manifest["registry"] = {
                "present": True, "exported": False,
                "error": (exported.stderr or exported.stdout or "").strip()
                         or "reg export 返回 %d" % exported.returncode}
            print("注册项：导出失败！ %s" % manifest["registry"]["error"])
        else:
            text = open(reg_path, encoding="utf-16-le", errors="replace").read()
            manifest["registry"] = {
                "present": True, "exported": True, "file": REG_FILE,
                "bytes": os.path.getsize(reg_path), "sha256": _sha256(reg_path),
                "mentions_key": reg_key.rsplit("\\", 1)[-1] in text}
            print("注册项：已导出 %s（%d 字节，含键名=%s）"
                  % (REG_FILE, manifest["registry"]["bytes"],
                     manifest["registry"]["mentions_key"]))

    # --- shortcuts.txt ---
    src = os.path.join(install_dir, SHORTCUTS_FILE)
    if not os.path.isfile(src):
        manifest["shortcuts"] = {"present": False, "path": src}
        print("快捷方式清单：%s 不存在" % src)
    else:
        shutil.copy2(src, os.path.join(dest, SHORTCUTS_FILE))
        copied = os.path.join(dest, SHORTCUTS_FILE)
        manifest["shortcuts"] = {"present": True, "path": src, "file": SHORTCUTS_FILE,
                                 "bytes": os.path.getsize(copied),
                                 "sha256": _sha256(copied)}
        print("快捷方式清单：已复制 %s（%d 字节）" % (src, manifest["shortcuts"]["bytes"]))

    with open(os.path.join(dest, MANIFEST), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return manifest


def backup_exit_code(manifest: dict) -> int:
    reg = manifest.get("registry") or {}
    return 2 if (reg.get("present") and not reg.get("exported")) else 0


# --------------------------------------------------------------------------
# 还原
# --------------------------------------------------------------------------
def newest_backup(out_dir: str) -> str | None:
    if not os.path.isdir(out_dir):
        return None
    candidates = [os.path.join(out_dir, n) for n in os.listdir(out_dir)
                  if os.path.isfile(os.path.join(out_dir, n, MANIFEST))]
    return max(candidates, key=os.path.getmtime) if candidates else None


def do_restore(dest: str, install_dir: str, assume_yes: bool, out_dir: str,
               reg_key: str | None = None) -> int:
    manifest_path = os.path.join(dest, MANIFEST)
    if not os.path.isfile(manifest_path):
        print("这里没有 %s，不像一份备份：%s" % (MANIFEST, dest))
        return 2
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    reg = manifest.get("registry") or {}
    sh = manifest.get("shortcuts") or {}
    install_dir = manifest.get("install_dir") or install_dir
    # 没显式指定就照备份时的那个键还，免得还错地方。
    reg_key = reg_key or manifest.get("registry_key") or REG_KEY

    print("备份目录：%s（%s）" % (dest, manifest.get("when", "?")))

    # --- 完整性校验（AW-15a）---------------------------------------------
    # `reg import` **之前**先按 manifest 核对每个备份文件的字节数与 sha256。
    # 以前从不核对，把 .reg 篡改掉（语法仍合法）也能照样导进去。
    if reg.get("present") and reg.get("exported"):
        ok, why = _verify_backup_file(os.path.join(dest, REG_FILE), reg)
        if not ok:
            print("  注册项：备份完整性校验失败 —— %s" % why)
            print("  中止，不做任何改动（reg import 之前先核对 manifest）")
            return 2
    if sh.get("present"):
        ok, why = _verify_backup_file(os.path.join(dest, SHORTCUTS_FILE), sh)
        if not ok:
            print("  快捷方式清单：备份完整性校验失败 —— %s" % why)
            print("  中止，不做任何改动（文件复制之前先核对 manifest）")
            return 2

    print("将要还原到：")
    if reg.get("present") and reg.get("exported"):
        print("  注册项 %s <- %s（完整性 OK）" % (reg_key, REG_FILE))
    else:
        print("  注册项：这份备份里没有（跳过）")
    if sh.get("present"):
        print("  快捷方式清单 %s <- %s（完整性 OK）"
              % (os.path.join(install_dir, SHORTCUTS_FILE), SHORTCUTS_FILE))
    else:
        print("  快捷方式清单：这份备份里没有（跳过）")

    # 覆盖之前先把「现在的」状态也存一份，万一这份备份是旧的还能退回来。
    snapshot = _fresh_dir(out_dir, _stamp() + "-prerestore")
    print("\n还原前先给当前状态拍一张快照：%s" % snapshot)
    # AW-15(b)：接住快照的返回值。以前这里没接返回值，快照导出失败时只打印
    # 一句「导出失败！」然后**照样继续 import** —— 那是「备份失败却静默继续」
    # 的同族（AW-1 修的正是这个族），只是发生在还原前快照而非主备份。
    snapshot_manifest = do_backup(snapshot, install_dir, reg_key)
    if backup_exit_code(snapshot_manifest) != 0:
        print("快照不完整（注册项没导出成功）—— 中止，"
              "不在没有安全网的情况下还原")
        return 2

    if not assume_yes:
        if not sys.stdin.isatty():
            print("\n要真的还原就加 --yes（非交互环境下不猜你的意思）")
            return 2
        # Windows 上 NUL 设备也算「字符设备」，isatty() 会给 True，所以重定向
        # 到空设备时照样会走到 input()——它读到 EOF 抛 EOFError，得自己接住。
        try:
            answer = input("\n继续还原？[y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n没读到确认（EOF），按「不还原」处理。要真还原请加 --yes。")
            return 1
        if answer not in ("y", "yes"):
            print("已取消（快照仍然留在 %s）" % snapshot)
            return 1

    code = 0
    if reg.get("present") and reg.get("exported"):
        imported = _reg("import", os.path.join(dest, REG_FILE))
        if imported.returncode != 0:
            print("注册项：reg import 失败（返回 %d）！ %s"
                  % (imported.returncode, (imported.stderr or "").strip()))
            code = 2
        else:
            print("注册项：已还原")

    if sh.get("present"):
        src = os.path.join(dest, SHORTCUTS_FILE)
        dst = os.path.join(install_dir, SHORTCUTS_FILE)
        if not os.path.isfile(src):
            print("快捷方式清单：备份文件缺失，跳过")
            code = code or 2
        elif not os.path.isdir(install_dir):
            print("快捷方式清单：安装目录 %s 不存在，跳过" % install_dir)
        else:
            shutil.copy2(src, dst)
            print("快捷方式清单：已还原到 %s" % dst)
    return code


# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="备份 / 还原 DSH 的卸载注册项与 shortcuts.txt（不动安装目录）。")
    ap.add_argument("--install-dir", default=DEFAULT_INSTALL_DIR,
                    help="DSH 安装目录（默认 %s）" % DEFAULT_INSTALL_DIR)
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="备份根目录（默认 scripts\\backups）")
    ap.add_argument("--reg-key", default=None,
                    help="要备份的注册表键（默认就是 DSH 的卸载键；一般不用改，"
                         "给验证链路用）")
    ap.add_argument("--list", action="store_true", help="列出已有的备份")
    ap.add_argument("--restore", nargs="?", const="", metavar="DIR",
                    help="从 DIR 还原；不带 DIR 表示从最新一份还原")
    ap.add_argument("--yes", action="store_true", help="还原时不问确认")
    args = ap.parse_args(argv)

    if args.list:
        if not os.path.isdir(args.out):
            print("还没有备份（%s）" % args.out)
            return 0
        names = sorted(n for n in os.listdir(args.out)
                       if os.path.isfile(os.path.join(args.out, n, MANIFEST)))
        if not names:
            print("还没有备份（%s）" % args.out)
            return 0
        for name in names:
            m = json.load(open(os.path.join(args.out, name, MANIFEST), encoding="utf-8"))
            reg = m.get("registry") or {}
            sh = m.get("shortcuts") or {}
            print("%-24s %s  注册项=%s 快捷方式=%s"
                  % (name, m.get("when", "?"),
                     "有" if reg.get("exported") else ("无" if not reg.get("present") else "导出失败"),
                     "有" if sh.get("present") else "无"))
        return 0

    if args.restore is not None:
        dest = args.restore or newest_backup(args.out)
        if not dest:
            print("找不到可还原的备份（%s）" % args.out)
            return 2
        return do_restore(dest, args.install_dir, args.yes, args.out, args.reg_key)

    dest = _fresh_dir(args.out, _stamp())
    print("备份到：%s" % dest)
    manifest = do_backup(dest, args.install_dir, args.reg_key or REG_KEY)
    code = backup_exit_code(manifest)
    print("\n%s" % ("备份完成" if code == 0 else "备份不完整（注册项没导出成功）"))
    return code


if __name__ == "__main__":
    sys.exit(main())
