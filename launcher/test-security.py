#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安全回归自检 — 不需要联网也能跑。

    python launcher/test-security.py

锁住这几条，它们都是「改回去很容易、但改回去代价很大」的东西：

  1  自更新下载的文件必须对得上发布声明的 sha256，对不上就丢弃、不动原文件
  2  装好的面板绝不用 PATH 里的 node（开发目录里允许）
  3  所有系统命令走绝对路径，不经过 PATH 解析
  4  后端只杀 node.exe，不会因为端口被占就杀掉别人的进程
  5  卸载脚本只在真正的安装目录里动手：守卫要求安装标记
     （`harness\\.dsh-installed.json`），删除只动白名单（`launcher` `harness`
     `runtime` `uninstall.bat` `shortcuts.txt` `install.log` `smoke.log`），
     白名单外的条目列出来并保留。老版本（无标记）兜底路径要求三个目录
     `launcher` `harness` `runtime` 全在**且** `launcher\\DSHLauncher.exe` 存在 ——
     纯函数 `uninstall_verdict` 与生成的 bat 必须给出同一个结论

注意第 5 条：它会真的运行一次卸载脚本，而脚本会删 `HKCU\\...\\Uninstall\\DeepSeekHarness`。
所以这里先 `reg export` 备份、跑完 `reg import` 还原。**备份拿不到就中止**（AW-1）：
以前 `reg export` 失败时 `snapshot_registry()` 返回空串，`restore_registry()` 的
`elif backup:` 对空串不成立 → 静默什么都不做，有概率删掉本机真实的卸载入口。
现在 `reg export` 失败抛 `RegistryBackupError`，**绝不在备份不可靠时继续跑卸载脚本**；
`reg import` 的返回码也检查，失败要报错而不是静默。下面第 0 段用打桩自测这两条
（**不碰真实注册项**）。

第 5 条的行为用例**一律在 `tempfile` 临时目录里造结构、生成脚本再跑**，绝不指向真实
安装目录；并且用 `_isolated_env()` 把 `PATH` / `SystemRoot` / `USERPROFILE` /
`APPDATA` 全部改道到临时目录，让脚本里的 `taskkill` `netstat` `reg` 和快捷方式清理
都变成空操作——这样即使脚本真的跑到底，也碰不到真实桌面、真实进程和真实注册项。
`cmd.exe` 是**故意**放进 stub `PATH` 的（AW-16）：脚本删完白名单、无保留项时，
`start /b cmd /c rmdir /s /q "\\\\?\\%DIR%"` 删安装根目录那条路径要真的能跑，
否则它永远是空操作、覆盖不到。
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
class RegistryBackupError(RuntimeError):
    """拿不到可靠的注册表备份 —— 绝不在这种状态下继续跑卸载脚本。"""


class RegistryRestoreError(RuntimeError):
    """还原注册项失败 —— 必须报出来，不能静默。"""


def _reg(*args: str) -> subprocess.CompletedProcess:
    """调 `reg.exe`（绝对路径）。返回码/输出由调用方判断。"""
    return subprocess.run([_sys("reg.exe"), *args], capture_output=True,
                          creationflags=0x08000000)


def _err_text(proc) -> str:
    out = getattr(proc, "stderr", b"") or getattr(proc, "stdout", b"") or b""
    if isinstance(out, bytes):
        try:
            return out.decode("mbcs").strip()      # reg.exe 在本机是 cp936
        except (UnicodeDecodeError, LookupError):
            return out.decode("utf-8", "replace").strip()
    return str(out).strip()


def snapshot_registry(reg_runner=_reg, reg_key: str = REG_KEY,
                      backup_dir: str | None = None) -> str | None:
    """导出 `reg_key` 作为备份，返回备份文件路径；键本来不存在时返回 None。

    `reg export` 失败**抛 RegistryBackupError**（不再返回空串让调用方静默跳过还原）。
    导出后还会校验：文件存在、非空、且内容里确实含这个键名。
    """
    reg_runner = reg_runner or _reg
    backup_dir = backup_dir or tempfile.gettempdir()

    if reg_runner("query", reg_key).returncode != 0:
        return None                          # 键不存在，没什么可丢的

    # 路径带时间戳 + pid：两次跑不会互相覆盖（原来固定叫 dsh-uninstall-backup.reg）。
    backup = os.path.join(
        backup_dir, "dsh-uninstall-backup-%s-%d.reg"
        % (time.strftime("%Y%m%d-%H%M%S"), os.getpid()))
    exported = reg_runner("export", reg_key, backup, "/y")
    if exported.returncode != 0:
        raise RegistryBackupError(
            "reg export 失败（返回 %d）：%s —— 备份不可靠，中止测试，"
            "绝不继续跑卸载脚本" % (exported.returncode, _err_text(exported)))
    if not os.path.isfile(backup) or os.path.getsize(backup) == 0:
        raise RegistryBackupError("reg export 返回成功但备份文件缺失或为空：%s" % backup)
    # reg export 写的是 UTF-16-LE；确认内容里确实有我们导出的那个键名。
    with open(backup, encoding="utf-16-le", errors="replace") as fh:
        text = fh.read()
    leaf = reg_key.rsplit("\\", 1)[-1]
    if leaf not in text:
        raise RegistryBackupError(
            "备份文件 %s 里没有键名 %r —— 导出内容不可信，中止测试" % (backup, leaf))
    return backup


def restore_registry(backup: str | None, reg_runner=_reg,
                     reg_key: str = REG_KEY) -> None:
    """按 snapshot 的结果还原。

    `backup is None` → 之前没有这个键，把测试期间可能建出来的删掉；
    `backup` 是路径 → `reg import` 还原，**返回码非 0 抛 RegistryRestoreError**。
    """
    reg_runner = reg_runner or _reg
    if backup is None:
        reg_runner("delete", reg_key, "/f")
        return
    if not os.path.isfile(backup) or os.path.getsize(backup) == 0:
        raise RegistryRestoreError("还原时备份文件缺失或为空：%s" % backup)
    imported = reg_runner("import", backup)
    if imported.returncode != 0:
        raise RegistryRestoreError(
            "reg import 失败（返回 %d）：%s —— 注册项可能没还原，请用 "
            "scripts\\backup-dsh-registry.py --restore 手工恢复"
            % (imported.returncode, _err_text(imported)))
    os.remove(backup)


def run_with_registry_guard(reg_runner, run_uninstaller_check,
                            reg_key: str = REG_KEY) -> str | None:
    """先备份注册项、再跑卸载检查、最后还原。

    备份拿不到就抛 RegistryBackupError，**绝不调用** run_uninstaller_check。
    """
    backup = snapshot_registry(reg_runner=reg_runner, reg_key=reg_key)
    try:
        run_uninstaller_check()
    finally:
        restore_registry(backup, reg_runner=reg_runner, reg_key=reg_key)
    return backup


def _write_bat(root: str) -> str:
    """Generate uninstall.bat into `root` (a temp dir) and return its path.

    Uses the real generator — the point of these cases is the script the
    installer actually writes, not a hand-made stand-in.
    """
    import installer
    worker = installer.InstallWorker(root, installer.resources(),
                                     queue.Queue(), threading.Event(), test_mode=True)
    worker.target = root
    worker._write_uninstaller()
    return os.path.join(root, "uninstall.bat")


def _run_bat(bat: str, env: dict) -> tuple[int, str]:
    """Run a generated uninstall.bat; return (returncode, stdout as text).

    stdin=DEVNULL so the script's `pause` sees EOF instead of waiting for a
    keypress that will never come.
    """
    try:
        proc = subprocess.run([_sys("cmd.exe"), "/c", bat], stdin=subprocess.DEVNULL,
                              timeout=60, capture_output=True, env=env,
                              creationflags=0x08000000)
    except subprocess.TimeoutExpired:
        return -1, ""
    return proc.returncode, (proc.stdout or b"").decode("mbcs", "replace")


def _isolated_env(tmp: str) -> dict:
    """Environment for running the generated uninstaller without side effects.

    Three redirects, so the script can be run for real:

    * `USERPROFILE` / `APPDATA` / `OneDrive` / `LOCALAPPDATA` point at empty
      temp dirs, so the shortcut cleanup cannot reach the real Desktop or
      Start Menu.
    * `PATH` is a stub dir holding a copy of `findstr.exe` (the script uses
      it to list what it keeps) and a copy of `cmd.exe`. Bare `taskkill` /
      `netstat` / `reg` then resolve to nothing and those lines are no-ops,
      but `cmd` is present so the `KEPT=0` root-removal line
      (`start /b cmd /c rmdir /s /q "\\\\?\\%DIR%"`) actually runs — AW-16
      added it precisely so that path is no longer dead in the test.
    * `SystemRoot` points at an empty temp dir too, so *absolute*
      `%SystemRoot%\\System32\\<tool>.exe` calls are no-ops as well.

    The registry guard in `main()` is the belt to these braces.
    """
    stub = os.path.join(tmp, "stub-path")
    os.makedirs(stub, exist_ok=True)
    shutil.copy2(_sys("findstr.exe"), os.path.join(stub, "findstr.exe"))
    shutil.copy2(_sys("cmd.exe"), os.path.join(stub, "cmd.exe"))
    fake_home = os.path.join(tmp, "fake-home")
    fake_appdata = os.path.join(tmp, "fake-appdata")
    fake_root = os.path.join(tmp, "fake-systemroot")
    for d in (os.path.join(fake_home, "Desktop"),
              os.path.join(fake_appdata, "Microsoft", "Windows", "Start Menu", "Programs"),
              fake_root):
        os.makedirs(d, exist_ok=True)
    env = dict(os.environ)
    env["USERPROFILE"] = fake_home
    env["APPDATA"] = fake_appdata
    env["OneDrive"] = fake_home
    env["LOCALAPPDATA"] = fake_appdata
    env["PATH"] = stub
    env["SystemRoot"] = fake_root
    return env


def _check_uninstall_policy() -> None:
    """第 5 项（策略）：`installer.uninstall_verdict` 是纯函数，直接单测。

    守卫从 OR（launcher/harness/runtime 任一存在）改成标记制，就是这一条。
    """
    import installer
    check("uninstall_verdict: 有安装标记 → 放行",
          installer.uninstall_verdict(["harness", "launcher"], True)[0] == "proceed")
    check("uninstall_verdict: 只有一个 runtime\\ → 拒绝（旧的 OR 守卫会放行）",
          installer.uninstall_verdict(["runtime", "notes.txt"], False)[0] == "reject")
    # AW-16：老版本兜底不再只看三个目录名，还要 launcher\DSHLauncher.exe ——
    # 生成的 bat 一直这么查，纯函数以前没查，同一个输入两者会给出不同结论。
    check("uninstall_verdict: 无标记但三者全在 + launcher\\DSHLauncher.exe → legacy 放行",
          installer.uninstall_verdict(["launcher", "harness", "runtime"], False,
                                      launcher_exe_present=True)[0]
          == "proceed-legacy")
    # 滥用场景（AW-16 复查实测）：一个跟 DSH 无关、恰好有 launcher\+harness\+runtime
    # 三个子目录的目录。以前纯函数判 proceed-legacy（会白名单删掉那三个目录），
    # 现在必须和 bat 一样拒绝——将来谁把它接到真正的删除动作也删不掉东西。
    check("uninstall_verdict: 只有三个同名目录、没有 launcher\\DSHLauncher.exe → 拒绝",
          installer.uninstall_verdict(["launcher", "harness", "runtime"], False)[0]
          == "reject")
    check("uninstall_verdict: 三个同名目录缺一（有 exe 也不行）→ 拒绝",
          installer.uninstall_verdict(["launcher", "harness"], False,
                                      launcher_exe_present=True)[0] == "reject")
    _v, remove, keep = installer.uninstall_verdict(
        ["launcher", "harness", "runtime", "uninstall.bat", "shortcuts.txt",
         "repo", "notes.txt"], True)
    check("uninstall_verdict: 只删白名单内的条目",
          set(remove) == {"launcher", "harness", "runtime", "uninstall.bat",
                          "shortcuts.txt"}, remove)
    check("uninstall_verdict: 白名单外的条目保留",
          keep == ["notes.txt", "repo"], keep)
    _v, remove2, keep2 = installer.uninstall_verdict(["runtime", "repo"], False)
    check("uninstall_verdict: 拒绝时什么都不删", remove2 == [], remove2)
    check("uninstall_verdict: 拒绝时全部保留", set(keep2) == {"runtime", "repo"}, keep2)


def _check_uninstaller(tmp: str, env: dict) -> None:
    """第 5 项：生成的卸载脚本在不该动的地方必须拒绝执行。"""
    victim = os.path.join(tmp, "notaninstall")
    os.makedirs(os.path.join(victim, "sub"))
    canary = os.path.join(victim, "precious.txt")
    with open(canary, "w", encoding="ascii") as f:
        f.write("keep me")
    bat = _write_bat(victim)
    check("卸载脚本带守卫", "does not look like a DSH install" in
          open(bat, encoding="ascii").read())
    _rc, out = _run_bat(bat, env)
    check("卸载脚本自己会结束（没卡在 pause）", out != "")
    check("守卫拦住了，文件还在", os.path.exists(canary))
    check("守卫拦住了，子目录还在", os.path.isdir(os.path.join(victim, "sub")))


def _check_uninstaller_behavior(tmp: str, env: dict) -> None:
    """第 5 项：守卫与白名单删除的实测行为（都在 tempfile 里造结构）。

    旧的守卫是 OR 语义、删除是无差别删光，这两条用例就是锁死它们。
    """
    import installer
    marker_name = installer.MARKER_NAME

    # (1) 目录里只有一个 runtime\ —— 这正是旧守卫放行、然后删光的场景。
    root = os.path.join(tmp, "only-runtime")
    os.makedirs(os.path.join(root, "runtime"))
    with open(os.path.join(root, "runtime", "node.exe"), "w", encoding="ascii") as f:
        f.write("x")
    keepme = os.path.join(root, "runtime", "keepme.txt")
    with open(keepme, "w", encoding="ascii") as f:
        f.write("keep")
    _rc, out = _run_bat(_write_bat(root), env)
    check("只有一个 runtime\\ 时守卫拒绝",
          "does not look like a DSH install" in out, out[:200])
    check("被拒时 runtime\\ 里的文件没被动过", os.path.exists(keepme))

    # (2)(3) 有安装标记 → 放行；白名单外的 repo\ 必须被保留。
    root2 = os.path.join(tmp, "with-marker")
    os.makedirs(os.path.join(root2, "harness"))
    with open(os.path.join(root2, "harness", marker_name), "w", encoding="ascii") as f:
        f.write('{"version": "test"}')
    os.makedirs(os.path.join(root2, "launcher"))
    os.makedirs(os.path.join(root2, "runtime"))
    os.makedirs(os.path.join(root2, "repo", ".claude"))
    with open(os.path.join(root2, "repo", "README"), "w", encoding="ascii") as f:
        f.write("source tree")
    repo_file = os.path.join(root2, "repo", ".claude", "x")
    with open(repo_file, "w", encoding="ascii") as f:
        f.write("x")
    with open(os.path.join(root2, "shortcuts.txt"), "w", encoding="ascii") as f:
        f.write("")
    _rc, out2 = _run_bat(_write_bat(root2), env)
    check("有安装标记时守卫放行",
          "does not look like a DSH install" not in out2, out2[:200])
    check("白名单外的 repo\\ 被保留", os.path.isdir(os.path.join(root2, "repo")))
    check("白名单外的 repo\\.claude 内容还在", os.path.exists(repo_file))
    check("白名单内的 launcher\\ 被删", not os.path.exists(os.path.join(root2, "launcher")))
    check("白名单内的 harness\\ 被删", not os.path.exists(os.path.join(root2, "harness")))
    check("白名单内的 runtime\\ 被删", not os.path.exists(os.path.join(root2, "runtime")))
    check("白名单内的 shortcuts.txt 被删",
          not os.path.exists(os.path.join(root2, "shortcuts.txt")))
    check("保留的条目被列出来并说明未删除",
          "repo" in out2 and "LEFT IN PLACE" in out2, out2[-200:])
    check("有保留项时安装目录本身不删", os.path.isdir(root2))

    # (4) 无标记 + 三者全在（老版本安装）→ 警告后按白名单删，repo\ 仍保留。
    #     本机真实的那份安装（0.2.0-rc.2）就是这一档：harness\ 里没有标记。
    root3 = os.path.join(tmp, "legacy-install")
    os.makedirs(os.path.join(root3, "launcher"))
    with open(os.path.join(root3, "launcher", "DSHLauncher.exe"), "w", encoding="ascii") as f:
        f.write("MZ")
    os.makedirs(os.path.join(root3, "harness"))
    os.makedirs(os.path.join(root3, "runtime"))
    os.makedirs(os.path.join(root3, "repo"))
    with open(os.path.join(root3, "repo", "keep"), "w", encoding="ascii") as f:
        f.write("k")
    _rc, out3 = _run_bat(_write_bat(root3), env)
    check("无标记但三者全在 → 警告后放行",
          "no install marker" in out3
          and "does not look like a DSH install" not in out3, out3[:200])
    check("老版本安装：白名单外的 repo\\ 仍被保留",
          os.path.isdir(os.path.join(root3, "repo")))
    check("老版本安装：白名单内的 harness\\ 被删",
          not os.path.exists(os.path.join(root3, "harness")))

    # (5) 滥用场景（AW-16）：一个跟 DSH 无关、恰好有 launcher\+harness\+runtime
    #     三个子目录、但没有 launcher\DSHLauncher.exe 的目录。纯函数以前判
    #     proceed-legacy（会白名单删掉那三个目录），生成的 bat 一直判 reject。
    #     修好对齐后两者都拒绝，目录一根汗毛都不动。
    root4 = os.path.join(tmp, "three-dirs-no-exe")
    os.makedirs(os.path.join(root4, "launcher"))
    os.makedirs(os.path.join(root4, "harness"))
    os.makedirs(os.path.join(root4, "runtime"))
    canary4 = os.path.join(root4, "runtime", "keepme.txt")
    with open(canary4, "w", encoding="ascii") as f:
        f.write("keep")
    _rc, out4 = _run_bat(_write_bat(root4), env)
    check("滥用场景：三个同名目录但没有 launcher\\DSHLauncher.exe → 守卫拒绝",
          "does not look like a DSH install" in out4, out4[:200])
    check("滥用场景：三个目录一个都没被删",
          os.path.isdir(os.path.join(root4, "launcher"))
          and os.path.isdir(os.path.join(root4, "harness"))
          and os.path.exists(canary4))

    # (6) KEPT=0（无保留项）：删完白名单后目录里只剩 uninstall.bat，安装根目录本身
    #     也必须被删掉。这条以前没覆盖——隔离环境把 cmd 从 PATH 拿掉了，
    #     `start /b cmd /c rmdir /s /q "\\?\%DIR%"` 是空操作（也正是 AW-8 记的
    #     管道挂起现象）。现在 stub PATH 里补了 cmd.exe，这条路径真的会跑。
    root5 = os.path.join(tmp, "clean-install")
    os.makedirs(os.path.join(root5, "harness"))
    with open(os.path.join(root5, "harness", marker_name), "w", encoding="ascii") as f:
        f.write('{"version": "test"}')
    os.makedirs(os.path.join(root5, "launcher"))
    os.makedirs(os.path.join(root5, "runtime"))
    _rc, out5 = _run_bat(_write_bat(root5), env)
    check("无保留项：脚本跑到底（Uninstall finished）", "Uninstall finished" in out5,
          out5[-200:])
    check("无保留项：没有列出任何保留项", "LEFT IN PLACE" not in out5, out5[-200:])
    # 根目录的删除是 `start /b cmd /c rmdir` 异步做的，轮询等它消失。
    gone = False
    deadline = time.time() + 20
    while time.time() < deadline:
        if not os.path.isdir(root5):
            gone = True
            break
        time.sleep(0.2)
    check("无保留项：安装根目录被删掉", gone, "目录仍在：%s" % root5)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="dsh-sec")
    try:
        # 0 ---- 注册表护栏自测（打桩，绝不碰真实注册项）-------------------
        # AW-1：以前 reg export 失败时 snapshot 返回空串、restore 静默不还原。
        # 这两条断言修复后必须成立；撤掉修复就会变红。
        class _FakeReg:
            """冒充 reg.exe：只记调用、按开关给返回码，不碰真实注册表。"""

            def __init__(self, export_ok=True, import_ok=True, key_present=True):
                self.export_ok = export_ok
                self.import_ok = import_ok
                self.key_present = key_present
                self.calls: list = []
                self.created: list = []

            def __call__(self, *args):
                self.calls.append(args)

                class _P:                    # 冒充 CompletedProcess
                    returncode = 0
                    stdout = ""
                    stderr = ""
                p = _P()
                verb = args[0]
                if verb == "query":
                    p.returncode = 0 if self.key_present else 1
                    p.stderr = "" if self.key_present else \
                        "ERROR: The system was unable to find the specified registry key or value."
                elif verb == "export":
                    if self.export_ok:
                        with open(args[2], "w", encoding="utf-16-le") as fh:
                            fh.write("Windows Registry Editor Version 5.00\r\n\r\n"
                                     "[%s]\r\n" % args[1])
                        self.created.append(args[2])
                    else:
                        p.returncode = 1
                        p.stderr = "ERROR: Access is denied."
                elif verb == "import":
                    if not self.import_ok:
                        p.returncode = 1
                        p.stderr = ("ERROR: The system was unable to find the "
                                    "specified registry key or value.")
                return p

        def _cleanup(paths):
            for path in paths:
                try:
                    os.remove(path)
                except OSError:
                    pass

        # 0a ---- reg export 失败 → 中止，且绝不跑卸载检查 ------------------
        fake = _FakeReg(export_ok=False)
        ran: list = []
        raised = ""
        try:
            run_with_registry_guard(fake, lambda: ran.append("uninstaller"),
                                    reg_key=REG_KEY)
        except RegistryBackupError as exc:
            raised = str(exc)
        check("reg export 失败时报错中止", bool(raised), "没有抛 RegistryBackupError")
        check("reg export 失败时不跑卸载检查", ran == [], ran)
        _cleanup(fake.created)

        # 0b ---- reg import 失败 → 报错（还原失败不能静默）-----------------
        fake2 = _FakeReg(import_ok=False)
        ran2: list = []
        raised2 = ""
        try:
            run_with_registry_guard(fake2, lambda: ran2.append("uninstaller"),
                                    reg_key=REG_KEY)
        except RegistryRestoreError as exc:
            raised2 = str(exc)
        check("reg import 失败时报错", bool(raised2), "没有抛 RegistryRestoreError")
        check("reg import 失败前卸载检查确实跑过", ran2 == ["uninstaller"], ran2)
        _cleanup(fake2.created)

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

        # 1b ---- a download that is not an executable at all --------------
        # The size floor alone cannot tell an exe from a captive portal's HTML
        # error page, and on a release published without a digest there is
        # nothing else to catch it.
        html = os.path.join(tmp, "portal.htm")
        with open(html, "wb") as f:
            f.write(b"<html>" + b"x" * 2_000_000)
        rel_html = updater.LauncherRelease(
            tag="v9.9.9", version="9.9.9",
            url="file:///" + html.replace("\\", "/"),
            size=os.path.getsize(html), digest="")     # no digest: only MZ can save us
        work2 = os.path.join(tmp, "nonmz")
        os.makedirs(work2, exist_ok=True)
        events2: "queue.Queue[dict]" = queue.Queue()
        w2 = updater.LauncherUpdateWorker(
            exe_path=os.path.join(work2, "DSHLauncher.exe"), release=rel_html,
            events=events2, cancel=threading.Event(),
            log_path=os.path.join(work2, "u.log"))
        with open(w2.exe_path, "wb") as f:
            f.write(b"ORIGINAL")
        w2.start()
        w2.join(timeout=60)
        done2 = ""
        while True:
            try:
                ev = events2.get_nowait()
                if ev["kind"] == "done":
                    done2 = ev["msg"]
            except queue.Empty:
                break
        check("非可执行文件被拒（MZ 头）", "MZ" in done2, done2)
        check("被拒时原文件没被动过", open(w2.exe_path, "rb").read() == b"ORIGINAL")
        check("被拒的下载已丢弃", not os.path.exists(w2.staged))

        # 1c ---- no exe path (a source run) must not rename anything ------
        # os.path.abspath("") is the working directory, so an unguarded worker
        # would rename the launcher's own cwd aside.
        sentinel_dir = os.path.join(tmp, "cwd-guard")
        os.makedirs(sentinel_dir, exist_ok=True)
        with open(os.path.join(sentinel_dir, "sentinel.txt"), "w") as f:
            f.write("here")
        old_cwd = os.getcwd()
        try:
            os.chdir(sentinel_dir)
            raised = ""
            try:
                updater.LauncherUpdateWorker(
                    exe_path="", release=release, events=queue.Queue(),
                    cancel=threading.Event())
            except ValueError as exc:
                raised = str(exc)
        finally:
            os.chdir(old_cwd)
        check("空的 exe 路径被拒绝", bool(raised), "没有抛 ValueError")
        check("工作目录没被动过",
              os.path.isfile(os.path.join(sentinel_dir, "sentinel.txt"))
              and not os.path.exists(os.path.join(tmp, "DSHLauncher.old.exe")))

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

        # 5 ---- uninstaller: guard policy + whitelist deletion --------------
        # 5a 策略层：纯函数，直接单测，不碰文件系统。
        _check_uninstall_policy()
        # 5b 行为层：真的跑生成的卸载脚本（都在 tempfile 里造结构），
        #    用 _isolated_env 把 PATH/SystemRoot/USERPROFILE/APPDATA 改道，
        #    再用注册表护栏包住：先备份真实键，跑完还原；备份拿不到就中止，
        #    绝不在备份不可靠时跑这个会删注册项的脚本。
        try:
            env = _isolated_env(tmp)
            run_with_registry_guard(
                _reg, lambda: (_check_uninstaller(tmp, env),
                               _check_uninstaller_behavior(tmp, env)))
        except RegistryBackupError as exc:
            print("ABORT  注册表备份失败：%s" % exc)
            print("       备份不可靠 —— 卸载检查没有执行。")
            return 2
        except RegistryRestoreError as exc:
            check("注册表已还原", False, exc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("ALL PASS" if OK else "SOME CHECKS FAILED")
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
