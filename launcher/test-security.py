#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安全回归自检 — 不需要联网也能跑。

    python launcher/test-security.py

锁住这几条，它们都是「改回去很容易、但改回去代价很大」的东西：

  1  自更新下载的文件必须对得上发布声明的 sha256，对不上就丢弃、不动原文件
  2  装好的面板绝不用 PATH 里的 node（开发目录里允许）
  3  所有系统命令走绝对路径，不经过 PATH 解析
  4  后端只杀 node.exe，不会因为端口被占就杀掉别人的进程
  5  卸载脚本在「不像安装目录」的地方拒绝执行

注意第 5 条：它会真的运行一次卸载脚本，而脚本会删 `HKCU\\...\\Uninstall\\DeepSeekHarness`。
所以这里先 `reg export` 备份、跑完 `reg import` 还原 —— 少了这一步，跑一次测试就会把
本机真装的那份的卸载入口删掉。
"""
from __future__ import annotations

import importlib.util
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALLER_DIR = os.path.join(os.path.dirname(HERE), "installer")
sys.path.insert(0, HERE)
sys.path.insert(0, INSTALLER_DIR)

REG_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSeekHarness"

spec = importlib.util.spec_from_file_location("launcher", os.path.join(HERE, "launcher.pyw"))
mod = importlib.util.module_from_spec(spec)
sys.modules["launcher"] = mod
spec.loader.exec_module(mod)

import updater  # noqa: E402

OK = True


def check(label: str, cond: bool, extra="") -> None:
    global OK
    print("%-6s %s%s" % ("PASS" if cond else "FAIL", label,
                         ("  <- " + str(extra)) if extra and not cond else ""))
    OK = OK and bool(cond)


def _sys(name: str) -> str:
    return os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", name)


# --------------------------------------------------------------------------
# registry guard for the uninstaller check
# --------------------------------------------------------------------------
def snapshot_registry() -> str | None:
    backup = os.path.join(tempfile.gettempdir(), "dsh-uninstall-backup.reg")
    existed = subprocess.run([_sys("reg.exe"), "query", REG_KEY],
                             capture_output=True).returncode == 0
    if not existed:
        return None
    subprocess.run([_sys("reg.exe"), "export", REG_KEY, backup, "/y"],
                   capture_output=True, creationflags=0x08000000)
    return backup if os.path.exists(backup) else ""


def restore_registry(backup: str | None) -> None:
    if backup is None:                       # the key did not exist before
        subprocess.run([_sys("reg.exe"), "delete", REG_KEY, "/f"],
                       capture_output=True, creationflags=0x08000000)
    elif backup:
        subprocess.run([_sys("reg.exe"), "import", backup],
                       capture_output=True, creationflags=0x08000000)
        os.remove(backup)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="dsh-sec")
    backup = snapshot_registry()
    try:
        # 1 ---- digest enforcement ---------------------------------------
        fake = os.path.join(tmp, "tampered.exe")
        with open(fake, "wb") as f:
            f.write(b"MZ" + os.urandom(2_000_000))
        release = updater.LauncherRelease(
            tag="v9.9.9", version="9.9.9",
            url="file:///" + fake.replace("\\", "/"),
            size=os.path.getsize(fake), digest="00" * 32)
        events: "queue.Queue[dict]" = queue.Queue()
        worker = updater.LauncherUpdateWorker(
            exe_path=os.path.join(tmp, "DSHLauncher.exe"), release=release,
            events=events, cancel=threading.Event(),
            log_path=os.path.join(tmp, "u.log"))
        with open(worker.exe_path, "wb") as f:
            f.write(b"ORIGINAL")
        worker.start()
        deadline = time.time() + 60
        while worker.is_alive() and time.time() < deadline:
            time.sleep(0.1)
        msgs = []
        while True:
            try:
                msgs.append(events.get_nowait())
            except queue.Empty:
                break
        done = next((e["msg"] for e in msgs if e["kind"] == "done"), "")
        check("被篡改的下载被拒绝", "校验不通过" in done, done)
        check("原文件没被动过", open(worker.exe_path, "rb").read() == b"ORIGINAL")
        check("坏文件已丢弃", not os.path.exists(worker.staged))

        # 2 ---- no PATH node for an installed copy ------------------------
        saved = (mod.sys.__dict__.get("frozen"), mod.LAUNCHER_DIR,
                 mod.INSTALL_DIR, mod.HARNESS_DIR)
        try:
            mod.sys.frozen = True
            mod.LAUNCHER_DIR = mod.INSTALL_DIR = mod.HARNESS_DIR = os.path.join(tmp, "empty")
            check("装好的面板不用 PATH node", mod._resolve_node() == "",
                  repr(mod._resolve_node()))
            mod.sys.frozen = False
            check("开发目录仍可用 PATH node", mod._resolve_node() == "node")
        finally:
            if saved[0] is None:
                mod.sys.__dict__.pop("frozen", None)
            else:
                mod.sys.frozen = saved[0]
            mod.LAUNCHER_DIR, mod.INSTALL_DIR, mod.HARNESS_DIR = saved[1], saved[2], saved[3]

        # 3 ---- absolute system tools -------------------------------------
        check("系统命令全部绝对路径",
              all(os.path.isabs(mod._SYS32(t)) and os.path.exists(mod._SYS32(t))
                  for t in ("taskkill.exe", "tasklist.exe", "netstat.exe",
                            "reg.exe", "cmd.exe")))
        check("updater 也用绝对路径", os.path.isabs(updater._SYS32("reg.exe")))

        # 4 ---- only node.exe is ever killed ------------------------------
        # `stop_server` finds the backend by "who listens on the port", so the
        # image-name check is what stops it killing an unrelated process that
        # happens to have taken 3080.
        candidates = [
            os.path.join(mod.INSTALL_DIR, "runtime", "node.exe"),
            os.path.join(mod.LAUNCHER_DIR, "runtime", "node.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "DeepSeekHarness",
                         "runtime", "node.exe"),
        ]
        node = next((c for c in candidates if c and os.path.exists(c)), None)
        if node is None:
            node = shutil.which("node")
        if node is None:
            # A dev checkout has no bundled runtime and node may simply not be
            # installed. Say so rather than quietly passing.
            print("SKIP   _is_node_process（本机没有 node.exe 可测）")
        else:
            proc = subprocess.Popen([node, "-e", "setTimeout(function(){}, 20000)"],
                                    creationflags=0x08000000)
            time.sleep(1.5)
            try:
                check("_is_node_process 认出真 node.exe",
                      mod._is_node_process(proc.pid) is True)
                check("_is_node_process 对非 node 返回 False",
                      mod._is_node_process(os.getpid()) is False)
            finally:
                subprocess.run([_sys("taskkill.exe"), "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, creationflags=0x08000000)

        # 5 ---- uninstaller refuses a directory that is not an install -----
        import installer
        victim = os.path.join(tmp, "notaninstall")
        os.makedirs(os.path.join(victim, "sub"))
        canary = os.path.join(victim, "precious.txt")
        open(canary, "w").write("keep me")
        w = installer.InstallWorker(victim, installer.resources(),
                                    queue.Queue(), threading.Event(), test_mode=True)
        w.target = victim
        w._write_uninstaller()
        bat = os.path.join(victim, "uninstall.bat")
        check("卸载脚本带守卫", "does not look like a DSH install" in
              open(bat, encoding="ascii").read())
        # stdin=DEVNULL so the script's `pause` sees EOF instead of waiting for
        # a keypress that will never come.
        try:
            subprocess.run([_sys("cmd.exe"), "/c", bat], stdin=subprocess.DEVNULL,
                           timeout=60, capture_output=True, creationflags=0x08000000)
        except subprocess.TimeoutExpired:
            check("卸载脚本自己会结束（没卡在 pause）", False)
        check("守卫拦住了，文件还在", os.path.exists(canary))
        check("守卫拦住了，子目录还在", os.path.isdir(os.path.join(victim, "sub")))
    finally:
        restore_registry(backup)
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("ALL PASS" if OK else "SOME CHECKS FAILED")
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
