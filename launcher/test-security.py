#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安全回归自检 — 不需要联网也能跑。

    python launcher/test-security.py

锁住这几条，它们都是「改回去很容易、但改回去代价很大」的东西：

  1  自更新下载的文件必须对得上发布声明的 sha256，对不上就丢弃、不动原文件
  2  装好的面板绝不用 PATH 里的 node（开发目录里允许）
  3  所有系统命令走绝对路径，不经过 PATH 解析 —— Python 侧（`_SYS32`）和
     **生成的卸载脚本**（AW-5：`_bat_sys32` → `%SystemRoot%\\System32\\<tool>.exe`）
     都算；生成的脚本里不能再出现裸的 `taskkill`/`netstat`/`tasklist`/`findstr`/
     `reg`/`cmd` 调用。`del`/`dir`/`rmdir`/`start` 是 cmd 内部命令（System32 里
     没有 del.exe），cmd 从不经 PATH 解析它们，所以它们只能是裸名
  4  后端只杀 node.exe，不会因为端口被占就杀掉别人的进程；端口按**精确**匹配，
     `:3080` 不会命中 `:30801`。面板（`launcher.pyw`）和**生成的卸载脚本**
     用的是同一份判定（`netproc.py`）——卸载脚本以前既不做镜像名校验，
     端口还是子串匹配（AW-4）
  5  卸载脚本只在真正的安装目录里动手：守卫要求安装标记
     （`harness\\.dsh-installed.json`），删除只动白名单（`launcher` `harness`
     `runtime` `uninstall.bat` `shortcuts.txt` `install.log` `smoke.log`），
     白名单外的条目列出来并保留。老版本（无标记）兜底路径要求三个目录
     `launcher` `harness` `runtime` 全在**且** `launcher\\DSHLauncher.exe` 存在 ——
     纯函数 `uninstall_verdict` 与生成的 bat 必须给出同一个结论
  6  安装目录不能是盘根 / 系统目录 / 用户目录本身（`installer.is_unsafe_target`）：
     盘根（`D:\\`）会让生成的卸载脚本把 `%~dp0` 退化成 `D:` 并对着盘根删；
     `%SystemRoot%`、`%ProgramFiles%`、`%USERPROFILE%` 本身、桌面/文档根同理。
     只拒这些目录**本身**，它们里面的专属子目录（`C:\\Users\\<你>\\DSH`）是允许的。
     AW-18：`abspath`/`normpath` 不解析 8.3 短名，所以 `C:\\PROGRA~1`
     （= `C:\\Program Files`）会绕过守卫——现在靠可注入的 `resolve` 钩子
     （默认 `GetLongPathNameW`）展开成长名再比对，短名与长名同判。`resolve`
     可注入，所以「策略层」仍能用假解析器单测、不碰文件系统。`\\\\?\\UNC\\s\\sh`
     与 `\\\\s\\sh` 也统一为拒绝；尾点（`C:\\Windows.`）按 Windows 语义剥掉。
  7  卸载脚本只删 `shortcuts.txt` 里记录的快捷方式（精确路径），不再用
     `del /q "%USERPROFILE%\\Desktop\\DSH*.lnk"` 通配删桌面（那会删掉用户自己
     起的、名字同样以 `DSH` 开头的快捷方式）；开始菜单目录用**不带 `/s`** 的
     `rmdir` 删（只删空目录），不再 `rmdir /s /q` 连整个文件夹一起删——用户放进
     该文件夹的快捷方式会保留（AW-6，判定在纯函数 `installer.shortcut_cleanup_lines`）
  8  `shortcuts.txt` 用 **UTF-8** 写，写失败绝不把一次已成功的安装判成失败
     （`installer.write_shortcuts_file` 捕获 `(OSError, UnicodeError)`；旧写法
     `encoding="mbcs"` 只捕 `OSError`，用户名/桌面路径含当前代码页之外的字符时
     `UnicodeEncodeError` 会在 ~97% 处逃出去）。生成的 bat 读这个文件前先
     `chcp 65001`、读后还原（`for /f` 按当前控制台代码页解码文件，不切会把
     UTF-8 清单解错、连中文名都删不掉）——AW-7
  9  `--dir` 后面没跟值时给**可读错误**而不是 `IndexError`（旧写法
     `argv[argv.index("--dir") + 1]` 在 windowed exe 里表现为静默无反应）；
     `--auto` 现在**必须显式传 `--dir`**，不再默认装到 `"."`（从源码树误跑一次
     就会把 `runtime/` `harness/` 解进当前目录——AUTOWORK 规则 5 的红线）。
     判定在纯函数 `installer._take_dir_arg` / `installer._auto_target` 里，
     报错经 `installer._cli_error`（无 stdout 时弹窗）——AW-9
 10 过时的用户可见文案不能再回来：内存提示不能说「构建前端」（现在没有本地
     构建，`npm install --ignore-scripts` 装预编译包，实测 npm 峰值内存约
     0.7 GB，门限已按实测从 4 GB 下调到 2 GB）；覆盖安装的确认框和「已安装
     版本」提示必须讲清卸载对**非 DSH 文件**做什么（AW-2 白名单：只删安装器
     自己创建的那几项，其余保留并列出）；仓库里的 `.py` 源码不能再出现旧包
     管理器名（现在是 npm）——AW-12
 11 `scripts\\build.ps1` 内嵌进 `DSHSetup.exe` 的那个便携 Node zip 必须按
     **预先固定**的 sha256 校验（常量 `$NODE_ZIP_SHA256`，来源是
     `https://nodejs.org/dist/<ver>/SHASUMS256.txt`）。基准绝不能是「下载时
     算出来的哈希」——那等于没校验；已存在的 zip 复用前也要校验，对不上就删掉
     重新下载，下载完再校验一次，对不上直接 `throw`（AW-13）。判定在纯函数
     `Test-FileSha256` 里（`launcher\\test-security.py` 用 PowerShell 的 AST
     解析器把它抽出来实跑，只对临时小文件算哈希，不下载）

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

AW-5 之后生成的脚本用 `%SystemRoot%\\System32\\<tool>.exe` 绝对路径调外部命令，所以
隔离不再是「从 PATH 里拿掉」而是「假的 `%SystemRoot%\\System32\\` 里只放该放的东西」：
`_isolated_env()` 往假的 System32 里放**真的 `findstr.exe` 和 `cmd.exe` 拷贝**（脚本
列保留项、以及删安装根目录要用它们），其余 `taskkill`/`netstat`/`tasklist`/`reg`
在假目录里**不存在** → 那些行自然变成空操作，碰不到真实进程和真实注册项。
`cmd.exe` 必须有（AW-16）：脚本删完白名单、无保留项时，`start /b
%SystemRoot%\\System32\\cmd.exe /c rmdir /s /q "\\\\?\\%DIR%"` 删安装根目录那条路径
要真的能跑，否则它永远是空操作、覆盖不到。
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import queue
import re
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

# AW-7 uses characters outside the machine's ANSI code page on purpose, and a
# FAIL message can then quote one of them. Without this, printing that message
# to a cp936 console raises UnicodeEncodeError and aborts the run instead of
# reporting the failure — a test that cannot report a red is worse than useless.
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):        # not a reconfigurable stream
    pass


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
    * `SystemRoot` points at a temp dir whose `System32\\` holds copies of the
      *real* `findstr.exe` and `cmd.exe` — the two tools the script must be able
      to run (it lists what it keeps with `findstr`, and removes the install
      root with `cmd /c rmdir`). Every other external tool the script calls
      absolutely (`taskkill`, `netstat`, `tasklist`, `reg`) is simply absent
      from that fake System32, so those lines are no-ops and touch no real
      process and no real registry key. AW-5 made the script call these by
      absolute path, so this redirect — not PATH — is what isolates them now.
    * `PATH` is a stub dir that likewise holds `findstr.exe` and `cmd.exe`;
      nothing needs it any more (every external call is absolute), it is kept
      only as belt to the System32 braces.

    The registry guard in `main()` is the belt to these braces.
    """
    stub = os.path.join(tmp, "stub-path")
    os.makedirs(stub, exist_ok=True)
    shutil.copy2(_sys("findstr.exe"), os.path.join(stub, "findstr.exe"))
    shutil.copy2(_sys("cmd.exe"), os.path.join(stub, "cmd.exe"))
    shutil.copy2(_sys("chcp.com"), os.path.join(stub, "chcp.com"))
    fake_home = os.path.join(tmp, "fake-home")
    fake_appdata = os.path.join(tmp, "fake-appdata")
    fake_root = os.path.join(tmp, "fake-systemroot")
    fake_sys32 = os.path.join(fake_root, "System32")
    os.makedirs(fake_sys32, exist_ok=True)
    shutil.copy2(_sys("findstr.exe"), os.path.join(fake_sys32, "findstr.exe"))
    shutil.copy2(_sys("cmd.exe"), os.path.join(fake_sys32, "cmd.exe"))
    # AW-7: the shortcut read is wrapped in `chcp 65001` … restore, so the fake
    # System32 must hold the real chcp.com or those lines would be no-ops and
    # the UTF-8 shortcuts.txt would be mis-decoded.
    shutil.copy2(_sys("chcp.com"), os.path.join(fake_sys32, "chcp.com"))
    for d in (os.path.join(fake_home, "Desktop"),
              os.path.join(fake_appdata, "Microsoft", "Windows", "Start Menu", "Programs")):
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


def _check_target_policy() -> None:
    """拒绝盘根 / 系统目录 / 用户目录本身作为安装目录（AW-3）。

    `installer.is_unsafe_target` 是纯函数（只看传进来的 `env`，不碰文件系统），
    所以这里直接单测、不造目录、不碰注册表。

    判定规则：**只拒绝这些目录「本身」**——盘根（`D:\\`）、`%SystemRoot%`、
    `%ProgramFiles%` 系列、`%USERPROFILE%` 本身、桌面/文档根；它们**里面的子目录
    是允许的**（`C:\\Users\\sechen\\DSH`、以及本机真实的 `C:\\Users\\sechen\\deepseek`）。
    """
    import installer
    # 注入的 env：让这些用例在任何机器上都给出同一个结论。
    env = {
        "SystemRoot": r"C:\Windows",
        "windir": r"C:\Windows",
        "ProgramFiles": r"C:\Program Files",
        "ProgramFiles(x86)": r"C:\Program Files (x86)",
        "ProgramW6432": r"C:\Program Files",
        "USERPROFILE": r"C:\Users\sechen",
        "OneDrive": r"C:\Users\sechen\OneDrive",
    }
    unsafe = [
        ("D:\\", "盘根"),
        ("C:\\", "盘根"),
        (r"C:", "盘根（没有反斜杠的裸盘符）"),
        ("\\\\?\\D:\\", "盘根（卸载脚本自己用的 \\\\?\\ 形式）"),
        ("Z:\\", "不存在的盘根也要拒绝（证明判定不看文件系统）"),
        (r"C:\Windows", "SystemRoot"),
        (r"C:\Windows\\", "SystemRoot 带尾反斜杠"),
        (r"c:\windows", "SystemRoot（大小写不同）"),
        (r"C:\Program Files", "ProgramFiles"),
        (r"C:\Program Files (x86)", "ProgramFiles(x86)"),
        (r"C:\Users\sechen", "USERPROFILE 本身"),
        (r"C:\Users\sechen\Documents\..", "USERPROFILE（经 .. 绕回来）"),
        (r"C:\Users\sechen\Desktop", "桌面根"),
        (r"C:\Users\sechen\Documents", "文档根"),
        (r"C:\Users\sechen\OneDrive\Documents", "OneDrive 文档根"),
    ]
    for path, why in unsafe:
        check("拒绝安装目录：%s（%s）" % (path, why),
              installer.is_unsafe_target(path, env) is True, path)
    # 拒绝时必须给出可操作提示，且提示里点出「装到专属子目录」。
    msg = installer.unsafe_target_message("D:\\", env)
    check("拒绝盘根时给出可操作提示",
          bool(msg) and "DSH" in msg and "C:\\Users" in msg, msg)

    allowed = [
        (r"C:\Users\sechen\DSH", "专属子目录"),
        (r"C:\Users\sechen\deepseek", "本机真实安装目录（必须是 USERPROFILE 的子目录）"),
        (r"C:\Users\sechen\Documents\DSH", "文档根的子目录"),
        (r"C:\Users\sechen\DSH-not-created-yet", "路径不必已存在"),
    ]
    for path, why in allowed:
        check("允许安装目录：%s（%s）" % (path, why),
              installer.is_unsafe_target(path, env) is False, path)
    check("允许时提示为空", installer.unsafe_target_message(r"C:\Users\sechen\DSH", env) == "")

    # AW-18：8.3 短名（C:\PROGRA~1 = C:\Program Files）。abspath/normpath 是纯词法
    # 的，不解析短名，所以短名会幸存到守卫这里——必须靠可注入的 `resolve` 钩子把它
    # 展开成长名再比对。这里注入一个**假解析器**，把「策略层」与文件系统解耦：
    # 短名展开成长名后必须被拒。（这正是现有 75 条测试全绿却放过它的原因——矩阵里
    # 没有 8.3。）
    short = {r"C:\PROGRA~1": r"C:\Program Files",
             r"C:\PROGRA~2": r"C:\Program Files (x86)"}

    def fake_resolve(p):
        return short.get(p, p)

    for path in (r"C:\PROGRA~1", r"C:\PROGRA~2"):
        check("拒绝 8.3 短名：%s（注入解析器展开为长名）" % path,
              installer.is_unsafe_target(path, env, fake_resolve) is True, path)
    check("8.3 短名的拒绝提示可操作",
          bool(installer.unsafe_target_message(r"C:\PROGRA~1", env, fake_resolve)), "")

    # 真实解析器：本机 8.3 已启用（`dir /x C:\` 可见 PROGRA~1），默认 resolve
    # （GetLongPathNameW）必须把短名展开、从而真的拒绝。用**真实 env** 钉一遍，
    # 这样即便注入的 env 是假的，产品默认路径也被覆盖。
    if os.path.isdir(r"C:\PROGRA~1") and os.environ.get("ProgramFiles"):
        expanded = installer._resolve_long_path(r"C:\PROGRA~1")
        check("默认解析器把 C:\\PROGRA~1 展开为长名",
              expanded.lower() == os.environ["ProgramFiles"].lower(), expanded)
        check("默认解析器下 C:\\PROGRA~1 被拒（真实 env）",
              installer.is_unsafe_target(r"C:\PROGRA~1") is True)
        check("默认解析器下 C:\\PROGRA~2 被拒（真实 env）",
              installer.is_unsafe_target(r"C:\PROGRA~2") is True)
    else:
        print("SKIP  8.3 实测（本机没有 C:\\PROGRA~1 或 ProgramFiles）")

    # AW-18：UNC 两种拼法必须同判。`\\server\share` 一直是拒绝（splitdrive 把它
    # 当成 drive），而等价的 `\\?\UNC\server\share` 以前被放行——同一共享两种拼法
    # 结论相反。`_canonical_target` 现在把 `\\?\UNC\` 折回 `\\`，统一为拒绝。
    check("拒绝共享根 \\\\server\\share",
          installer.is_unsafe_target(r"\\server\share", env) is True)
    check("拒绝共享根 \\\\?\\UNC\\server\\share（字面量拼法，与上一条同判）",
          installer.is_unsafe_target(r"\\?\UNC\server\share", env) is True)

    # AW-18：尾点/尾空格的纯函数契约。纯函数以前放行 `C:\Windows.`，而
    # `_canonical_target` 的 docstring 却声称处理「杂散空白」——契约与实现不一致。
    # 现在按 Windows 语义剥掉每个组件的尾点/尾空格。用 **no-op 解析器**验证
    # 「纯函数自己」就覆盖了这条（不依赖文件系统）。
    noop = lambda p: p
    check("拒绝尾点：C:\\Windows.（纯契约，no-op 解析器）",
          installer.is_unsafe_target(r"C:\Windows.", env, noop) is True)
    check("拒绝尾点：C:\\Windows...（纯契约，no-op 解析器）",
          installer.is_unsafe_target(r"C:\Windows...", env, noop) is True)

    # 用**真实** env 再钉一遍关键结论（这两条与机器无关：USERPROFILE 本身就是
    # 用户目录、它的子目录是我们要的安装位置）。
    home = os.environ.get("USERPROFILE") or ""
    if home:
        check("真实 USERPROFILE 本身被拒", installer.is_unsafe_target(home) is True, home)
        check("真实 USERPROFILE 下的 DSH 子目录被允许",
              installer.is_unsafe_target(os.path.join(home, "DSH")) is False)
    systemroot = os.environ.get("SystemRoot") or ""
    if systemroot:
        check("真实 SystemRoot 被拒", installer.is_unsafe_target(systemroot) is True, systemroot)
    check("空路径不算 unsafe（另行处理）", installer.is_unsafe_target("") is False)


# --------------------------------------------------------------------------
# AW-4：按端口杀进程 —— 端口必须精确匹配，且只杀 node.exe
# --------------------------------------------------------------------------
# netstat -ano 的样例行，列格式照抄本机实测（Proto / Local / Foreign /
# State / PID）。用假数据而不是真跑 netstat：这里要钉的是**判定**，
# 而且要能在任何机器上给出同一个结论。
_NS_ROWS = {
    1111: "  TCP    0.0.0.0:3080           0.0.0.0:0              LISTENING       1111",
    2222: "  TCP    0.0.0.0:30801          0.0.0.0:0              LISTENING       2222",
    3333: "  TCP    0.0.0.0:30800          0.0.0.0:0              LISTENING       3333",
    4444: "  TCP    [::]:3080              [::]:0                 LISTENING       4444",
    5555: "  TCP    127.0.0.1:3080         127.0.0.1:52341        ESTABLISHED     5555",
    6666: "  TCP    127.0.0.1:52341        127.0.0.1:3080         ESTABLISHED     6666",
}
# 这些 PID 上跑的镜像名。只有 1111 是「精确落在 :3080 且是 node.exe」。
_NS_IMAGES = {1111: "node.exe", 2222: "node.exe", 3333: "node.exe",
              4444: "explorer.exe", 5555: "node.exe", 6666: "node.exe"}


def _findstr_hits(dump: str, pattern: str) -> list[int]:
    """跑一遍生成的 bat 里那两段 findstr，返回活下来的行的 PID。

    用真的 findstr.exe、喂真的 netstat 文本——这是「生成的 bat 确实按精确
    端口匹配」的实证，而且不碰任何进程。
    """
    out = dump
    for args in (["/R", "/C:" + pattern], ["LISTENING"]):
        proc = subprocess.run([_sys("findstr.exe"), *args],
                              input=out.encode("mbcs"), capture_output=True)
        out = (proc.stdout or b"").decode("mbcs", "replace")
    return [int(line.split()[-1]) for line in out.splitlines() if line.split()]


def _check_port_kill_policy() -> None:
    """AW-4 策略层：`netproc` 是纯函数，直接单测，不碰进程也不碰文件系统。"""
    import netproc

    check(":3080 精确命中", netproc.listening_pid(_NS_ROWS[1111], 3080) == 1111)
    check(":3080 的 IPv6 写法也命中",
          netproc.listening_pid(_NS_ROWS[4444], 3080) == 4444)
    check(":30801 不命中（旧的子串匹配会命中）",
          netproc.listening_pid(_NS_ROWS[2222], 3080) is None)
    check(":30800 不命中（旧的子串匹配会命中）",
          netproc.listening_pid(_NS_ROWS[3333], 3080) is None)
    check("对端是 :3080 的 ESTABLISHED 行不命中",
          netproc.listening_pid(_NS_ROWS[6666], 3080) is None)
    check("本地 :3080 但不是 LISTENING 的行不命中",
          netproc.listening_pid(_NS_ROWS[5555], 3080) is None)

    dump = "\r\n".join(_NS_ROWS[pid] for pid in sorted(_NS_ROWS))
    check("整份 netstat 里只有 1111 和 4444 命中",
          netproc.listening_pids(dump, 3080) == [1111, 4444],
          netproc.listening_pids(dump, 3080))

    pat = netproc.port_findstr_pattern(3080)
    check("端口模式不是子串（:3080 后面不能再跟数字）", pat == ":3080[^0-9]", pat)
    check("生成的 findstr 两段管道选出的是同一批行",
          _findstr_hits(dump, pat) == netproc.listening_pids(dump, 3080),
          _findstr_hits(dump, pat))

    check("node.exe 的 tasklist 行被认出",
          netproc.is_node_image('"node.exe","1111","Console","1","10 K"'))
    check("非 node 镜像不被认成 node",
          netproc.is_node_image('"explorer.exe","4444","Console","1","10 K"') is False)
    check("tasklist 查不到进程时不算 node",
          netproc.is_node_image("INFO: No tasks are running which match the "
                                "specified criteria.") is False)
    check("镜像名比较大小写不敏感", netproc.is_node_image('"Node.EXE","1"'))
    check("tasklist 查询形式与 bat 里那句同源",
          netproc.tasklist_batch_fragment("%%p")
          == 'tasklist /FI "PID eq %%p" /FO CSV /NH',
          netproc.tasklist_batch_fragment("%%p"))
    check("tasklist_args 与 bat 片段同源",
          netproc.tasklist_args(7) == ["/FI", "PID eq 7", "/FO", "CSV", "/NH"])
    # AW-5：生成的 bat 传绝对路径的 exe token 进来，片段要原样带上它。
    check("tasklist 片段可换用绝对路径调用（生成的 bat 就是这么用的）",
          netproc.tasklist_batch_fragment(
              "%%p", "%SystemRoot%\\System32\\tasklist.exe")
          == "%SystemRoot%\\System32\\tasklist.exe "
             '/FI "PID eq %%p" /FO CSV /NH')


#: 生成的 bat 里必须以绝对路径调用的外部系统命令（AW-5）。
_EXTERNAL_TOOLS = ("taskkill", "netstat", "tasklist", "findstr", "reg", "cmd")


def _bare_tool_calls(text: str) -> list[str]:
    """扫生成的 bat，返回**裸调用**的外部系统命令名（正确时应为空）。

    只看命令位置：跳过 `rem` 注释行；一个工具名只要前面不是路径分隔符
    （也就是不是 `%SystemRoot%\\System32\\taskkill.exe` 那种绝对路径的一部分）
    就算裸调用。cmd 的内部命令（`del`/`dir`/`rmdir`/`start`/`echo`/`set`/`if`/
    `for`/`goto`/`pause`/`exit`）**不在**名单里——System32 里没有它们的 .exe，
    cmd 也从不经 PATH 解析它们，所以它们只能是裸名，也没有劫持面。
    AW-7 把 `chcp`（`.com`，不是 `.exe`）也纳入名单，所以后缀匹配放宽成 `\\.\\w+`。
    """
    hits: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.lower().startswith("rem") or s.startswith("::"):
            continue
        for m in re.finditer(
                r"(?i)(?<![\w\\/.:-])(taskkill|netstat|tasklist|findstr|reg|cmd|chcp)"
                r"(?=\.\w+|\s|$|\"|')", s):
            hits.append(m.group(1).lower())
    return hits


def _check_uninstaller_absolute_paths(tmp: str) -> None:
    """AW-5 文本层：生成的 bat 里外部命令一律绝对路径，没有裸调用。

    纯文本断言，不跑脚本：拿生成器真正写出来的脚本文本扫一遍。
    """
    root = os.path.join(tmp, "abs-paths")
    os.makedirs(root, exist_ok=True)
    bat = open(_write_bat(root), encoding="ascii").read()

    bare = _bare_tool_calls(bat)
    check("生成的 bat 里没有裸的外部命令调用", bare == [], bare)
    for tool in _EXTERNAL_TOOLS:
        token = "%%SystemRoot%%\\System32\\%s.exe" % tool
        check("生成的 bat 用绝对路径调 %s" % tool, token in bat, token)
    # 反向自检：正则不能过宽（把绝对路径也当裸名）也不能过窄（漏掉裸名）。
    check("绝对路径不会误判成裸调用",
          _bare_tool_calls(r"%SystemRoot%\System32\taskkill.exe /F /IM x") == [])
    check("裸调用会被认出来（正则确实有效）",
          _bare_tool_calls("taskkill /F /IM x") == ["taskkill"])


def _check_uninstaller_kill_text(tmp: str) -> None:
    """AW-4 文本层：生成的 bat 里那段杀进程的写法。"""
    root = os.path.join(tmp, "kill-text")
    os.makedirs(root, exist_ok=True)
    bat = open(_write_bat(root), encoding="ascii").read()
    check("生成的 bat 里端口是精确匹配", 'findstr.exe /R /C:":3080[^0-9]"' in bat)
    check("生成的 bat 不再用旧的子串 findstr", 'findstr ":3080"' not in bat)
    check("生成的 bat 按镜像名校验 node.exe", 'findstr.exe /i "node.exe"' in bat)
    check("生成的 bat 用 /T 杀进程树", "taskkill.exe /PID %%p /T /F" in bat)
    check("生成的 bat 不再有无镜像校验的裸 taskkill /F /PID",
          "taskkill /F /PID" not in bat)


def _check_shortcut_cleanup_text(tmp: str) -> None:
    """AW-6 文本层：只删 shortcuts.txt 记录的快捷方式，开始菜单目录只删空的。

    两层都扫：纯函数 `installer.shortcut_cleanup_lines()`（不跑脚本、不碰文件
    系统），以及生成器真正写出来的 bat 文本。旧写法（`del /q "…\\Desktop\\DSH*.lnk"`
    通配删桌面、`rmdir /s /q "…\\Programs\\DSH"` 递归删整个文件夹）必须消失。
    """
    import installer
    joined = "\n".join(installer.shortcut_cleanup_lines())
    check("快捷方式清理：没有任何通配删除", "*" not in joined, joined)
    check("快捷方式清理：没有 rmdir /s（只删空目录）",
          re.search(r"(?i)rmdir\s+/s", joined) is None, joined)
    check("快捷方式清理：按 shortcuts.txt 精确删",
          "%~dp0shortcuts.txt" in joined, joined)
    check("快捷方式清理：两个开始菜单目录名都在，且都是不带 /s 的 rmdir",
          joined.count('rmdir "') == 2
          and "Start Menu\\Programs\\DeepSeek Harness\"" in joined
          and "Start Menu\\Programs\\DSH\"" in joined, joined)

    root = os.path.join(tmp, "shortcut-text")
    os.makedirs(root, exist_ok=True)
    bat = open(_write_bat(root), encoding="ascii").read()
    check("生成的 bat 不再通配删桌面快捷方式（旧写法会删用户自建的 DSH*.lnk）",
          "DSH*.lnk" not in bat, "bat 里仍有通配删除")
    check("生成的 bat 不再递归删开始菜单文件夹",
          not any("rmdir /s" in line and "%APPDATA%" in line
                  for line in bat.splitlines()))
    check("生成的 bat 仍按 shortcuts.txt 精确删快捷方式",
          'for /f "usebackq delims=" %%L in ("%~dp0shortcuts.txt")' in bat)
    check("生成的 bat 用不带 /s 的 rmdir 删两个开始菜单目录",
          'rmdir "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\DSH" >nul' in bat
          and 'rmdir "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs'
              '\\DeepSeek Harness" >nul' in bat)


def _check_uninstaller_tail_text(tmp: str) -> None:
    r"""AW-8 文本层：收尾的「自删」与「删目录」必须按设计排序。

    设计（见 `_write_uninstaller` 的 docstring 与生成的 bat 尾部）：

    * 无保留项时，**一个** detached cmd 先删脚本、再删目录（`del` 在
      `rmdir` 之前），这样 rmdir 跑的时候目录已经空、也不再有正在执行的
      批处理把它占住。
    * 删目录的路径是**裸** `%DIR%`，不是 extended-length 路径
      （`\\?\...`）—— 实测 cmd 内建的 rmdir 会拒绝后者并报
      「文件名、目录名或卷标语法不正确」，这正是「残留一个空安装目录」的根因。
    * 脚本自己的 `del "%~f0"` 必须是**最后一行**：cmd 一发现正在执行的
      批处理被删就停止读后续行，后面放任何命令都不会执行。

    纯文本断言，不跑脚本、不碰注册表 —— 放在注册表护栏之外，永远会跑。
    """
    root = os.path.join(tmp, "tail-text")
    os.makedirs(root, exist_ok=True)
    bat = open(_write_bat(root), encoding="ascii").read()
    lines = bat.splitlines()

    check("AW-8：删目录不再用 extended-length 路径（cmd 的 rmdir 会拒绝）",
          "\\\\?\\" not in bat, "bat 里仍有 \\\\?\\ 路径")
    check("AW-8：旧的并发写法（异步 rmdir + extended-length 路径）已消失",
          'rmdir /s /q "\\\\?\\%DIR%"' not in bat)
    check("AW-8：删目录仍由 detached 进程执行（start /b）",
          'start "" /b' in bat)

    tail = [ln for ln in lines if ln.startswith('if "%KEPT%"=="0" start "" /b')]
    check("AW-8：无保留项时有一条 detached 收尾行", len(tail) == 1, tail)
    tail_line = tail[0] if tail else ""
    del_pos = tail_line.find('del /f /q "%~f0"')
    rmdir_pos = tail_line.find('rmdir /s /q "%DIR%"')
    check("AW-8：detached 进程先自删（del）再删目录（rmdir）",
          del_pos != -1 and rmdir_pos != -1 and del_pos < rmdir_pos, tail_line)
    # 反向自检：正则/查找不能恒真也不能恒假。
    check("AW-8：反序写法会被认出来（查找确实有效）",
          _selfdel_before_rmdir('start "" /b cmd /c rmdir /s /q "d" ^& del /f /q "s"')
          is False)

    nonempty = [ln for ln in lines if ln.strip() != ""]
    check("AW-8：脚本的自删 del 是最后一行（其后没有任何命令）",
          bool(nonempty) and nonempty[-1] == 'del "%~f0" >nul 2>&1',
          nonempty[-1] if nonempty else "<empty>")


def _selfdel_before_rmdir(line: str) -> bool:
    """给定一行收尾命令，判断它是否「先 del 脚本、后 rmdir 目录」。"""
    del_pos = line.find('del /f /q "%~f0"')
    rmdir_pos = line.find('rmdir /s /q "%DIR%"')
    return del_pos != -1 and rmdir_pos != -1 and del_pos < rmdir_pos


def _mbcs_unrepresentable() -> str:
    r"""一个本机 ANSI 代码页表示不了的字符（AW-7）。

    `mbcs` 就是「当前 ANSI 代码页」，所以它拒绝哪些字符是机器相关的
    （本机 cp936，别处可能 cp1252）。返回第一个本机编码不了的候选；
    若所有候选都恰好能编码，返回 ""，调用方对 mbcs 相关断言打 SKIP 而不是瞎猜。
    """
    for ch in ("\u0551", "\u0e01", "\u05d0", "\u0905", "\U0001F600"):
        try:
            ch.encode("mbcs")
        except UnicodeEncodeError:
            return ch
    return ""


def _call(fn, *args):
    """调用 `fn`，返回 `(结果, 异常文本)`——不抛，让断言的失败是 FAIL 不是崩溃。"""
    try:
        return fn(*args), ""
    except Exception as exc:  # noqa: BLE001 - the point is to report it
        return None, "%s: %s" % (type(exc).__name__, exc)


def _check_cli_args() -> None:
    r"""第 9 项：`--dir` 缺值的崩溃与 `--auto` 的危险默认值（AW-9）。

    (a) `argv[argv.index("--dir") + 1]` 没有边界检查：`--dir` 后面没跟值会
        `IndexError`。在 windowed exe（`sys.stdout is None`）里 `_say()` 什么都不
        打印、进程就那么没了 —— 用户完全不知道发生了什么。
    (b) `--auto` 的默认目标是 `"."`：从源码树里误跑一次就把 `runtime/` `harness/`
        解进当前目录（AUTOWORK 规则 5 的红线）。现在**要求必须显式传 `--dir`**。

    全是纯函数 + 早退路径，不装任何东西、不碰注册表、不碰文件系统。
    唯一两次 `_run_auto` 调用用 stub 顶住 `preflight.run`：万一有人把默认值改回
    `"."`，这里会立刻抛错、断言变红，而**不会**真的开始往当前目录解压安装。
    """
    import contextlib
    import io
    import installer

    # ---- (a) `--dir` 后面没值：可读错误，不是 IndexError ----------------
    res, raised = _call(installer._take_dir_arg, ["--auto", "--dir"])
    val, err = res if isinstance(res, tuple) and len(res) == 2 else (None, "")
    check("AW-9a：--dir 末尾缺值 → 可读错误而不是 IndexError",
          raised == "" and val is None and bool(err), raised or res)
    check("AW-9a：--dir 缺值的错误信息可读（点名 --dir 与用法）",
          "--dir" in err and "用法" in err, err)

    res, raised = _call(installer._take_dir_arg, ["--auto", "--dir", r"C:\Users\x\DSH"])
    check("AW-9a：--dir 有值时正常取出",
          raised == "" and res == (r"C:\Users\x\DSH", ""), raised or res)

    res, raised = _call(installer._take_dir_arg, ["--auto"])
    check("AW-9a：没有 --dir 时不报「缺值」（默认由调用方决定）",
          raised == "" and res == (None, ""), raised or res)

    # ---- (b) `--auto` 必须显式传 --dir ---------------------------------
    res, raised = _call(installer._auto_target, ["--auto"])
    tgt, err = res if isinstance(res, tuple) and len(res) == 2 else (None, "")
    check("AW-9b：--auto 不带 --dir → 拒绝（不再默认当前目录）",
          raised == "" and tgt is None and bool(err), raised or res)
    check("AW-9b：拒绝文案点名 --dir 并说明为什么",
          "--dir" in err and "当前目录" in err, err)

    res, raised = _call(installer._auto_target, ["--auto", "--dir"])
    check("AW-9b：--auto --dir 缺值 → 同一个可读错误",
          raised == "" and res is not None and res[0] is None and bool(res[1]),
          raised or res)

    res, raised = _call(installer._auto_target, ["--auto", "--dir", "T"])
    check("AW-9b：--auto --dir T → 取到 T",
          raised == "" and res == ("T", ""), raised or res)

    # ---- 接线：`_run_auto` 真的走上面这条判定 ---------------------------
    proceeded = []
    orig_pf = installer.preflight.run

    def _pf_stub(target):
        proceeded.append(target)
        raise RuntimeError("AW-9 guard: --auto 在没有 --dir 的情况下继续了")
    installer.preflight.run = _pf_stub
    try:
        for label, argv in (("--auto 单独", ["--auto"]),
                            ("--auto --dir 缺值", ["--auto", "--dir"])):
            buf = io.StringIO()
            raised = ""
            rc = None
            try:
                with contextlib.redirect_stdout(buf):
                    rc = installer._run_auto(argv)
            except Exception as exc:  # noqa: BLE001
                raised = "%s: %s" % (type(exc).__name__, exc)
            check("AW-9：%s → 返回 2、不抛异常" % label,
                  raised == "" and rc == 2, raised or rc)
            check("AW-9：%s → 打印了可读错误" % label,
                  "ERROR" in buf.getvalue() and "--dir" in buf.getvalue(),
                  buf.getvalue()[:160])
    finally:
        installer.preflight.run = orig_pf
    check("AW-9：两条拒绝都在 preflight 之前返回（没有真的开始安装）",
          proceeded == [], proceeded)
    check("AW-9：被拒绝时没有在当前目录建 runtime/harness",
          not os.path.exists(os.path.join(os.getcwd(), "runtime"))
          and not os.path.exists(os.path.join(os.getcwd(), "harness")))

    # `--diag --dir` 缺值同样不能是 IndexError（只读命令，但也不该崩）
    buf = io.StringIO()
    raised = ""
    rc = None
    try:
        with contextlib.redirect_stdout(buf):
            rc = installer._run_diag(["--diag", "--dir"])
    except Exception as exc:  # noqa: BLE001
        raised = "%s: %s" % (type(exc).__name__, exc)
    check("AW-9a：--diag --dir 缺值 → 返回 2、不抛 IndexError",
          raised == "" and rc == 2, raised or rc)

    # ---- windowed exe（stdout 是 None）时不能静默：必须弹窗 -------------
    shown = []
    orig_show = installer.messagebox.showerror
    orig_stdout = sys.stdout
    installer.messagebox.showerror = (
        lambda title, msg, **kw: shown.append((title, msg)))
    try:
        sys.stdout = None
        rc_ns = installer._cli_error("--dir 后面缺少安装目录路径。")
    finally:
        sys.stdout = orig_stdout
        installer.messagebox.showerror = orig_show
    check("AW-9a：windowed（无 stdout）时弹窗而不是静默退出",
          rc_ns == 2 and len(shown) == 1 and "--dir" in shown[0][1], shown)


def _check_shortcuts_encoding(tmp: str) -> None:
    r"""AW-7 文本/纯函数层：shortcuts.txt 用 UTF-8 写、写失败不逃逸、bat 按 65001 读。

    不碰注册表也不跑脚本，放在注册表护栏之外，永远会跑。
    """
    import installer

    # ---- 写侧：UTF-8，且内容能被 utf-8 读回 ----------------------------
    root = os.path.join(tmp, "shortcuts-encoding")
    os.makedirs(root, exist_ok=True)
    bad = _mbcs_unrepresentable()
    lnks = [r"C:\Users\sechen\Desktop\DSH.lnk"]
    if bad:
        lnks.append("C:\\Users\\%s\\Desktop\\DSH.lnk" % bad)
    ok = None
    wrote_escaped = ""
    try:
        ok = installer.write_shortcuts_file(root, lnks)
    except Exception as exc:                       # noqa: BLE001 - the point
        wrote_escaped = repr(exc)
    path = os.path.join(root, "shortcuts.txt")
    check("write_shortcuts_file：正常写入不抛异常", wrote_escaped == "", wrote_escaped)
    check("write_shortcuts_file：成功时返回 True", ok is True)
    check("write_shortcuts_file：文件确实写出来了", os.path.isfile(path))
    raw = open(path, "rb").read() if os.path.isfile(path) else b""
    try:
        text = raw.decode("utf-8")
        decoded = True
    except UnicodeDecodeError:
        text, decoded = "", False
    check("shortcuts.txt 是 UTF-8 编码（能被 utf-8 解码）", decoded and raw != b"")
    check("shortcuts.txt 内容能被 utf-8 读回（逐行一致）",
          text.splitlines() == lnks, text.splitlines())

    if bad:
        check("shortcuts.txt 里确实写进了非 ASCII 路径（UTF-8 多字节）",
              bad.encode("utf-8") in raw)
        # 旧写法（mbcs）对同一路径会抛 UnicodeEncodeError —— 这正是被修的 bug。
        raised = ""
        try:
            with open(os.path.join(root, "mbcs-probe.txt"), "w",
                      encoding="mbcs") as f:
                f.write("\n".join(lnks))
        except UnicodeError as exc:
            raised = type(exc).__name__
        check("旧写法（mbcs）对同一路径抛 UnicodeEncodeError（bug 真的存在）",
              raised == "UnicodeEncodeError", raised)
        try:
            os.remove(os.path.join(root, "mbcs-probe.txt"))
        except OSError:
            pass
    else:
        print("SKIP   本机 ANSI 代码页能表示所有探针字符 —— 跳过 mbcs 相关断言")

    # ---- 失败路径：写入抛异常必须被吞掉、不逃逸 ------------------------
    class _RaisingFile:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def write(self, _s):
            raise UnicodeEncodeError("utf-8", "x", 0, 1, "boom")

    escaped = ""
    result = None
    try:
        result = installer.write_shortcuts_file(
            root, ["x"], opener=lambda *a, **k: _RaisingFile())
    except Exception as exc:                       # noqa: BLE001 - the point
        escaped = repr(exc)
    check("写入抛 UnicodeEncodeError 时不逃逸（被吞掉）", escaped == "", escaped)
    check("写入抛 UnicodeEncodeError 时返回 False", result is False)

    def _raise_oserror(*a, **k):
        raise OSError(28, "No space left on device")

    escaped2 = ""
    result2 = None
    try:
        result2 = installer.write_shortcuts_file(root, ["x"], opener=_raise_oserror)
    except Exception as exc:                       # noqa: BLE001
        escaped2 = repr(exc)
    check("写入抛 OSError 时也不逃逸（旧行为保留）", escaped2 == "", escaped2)
    check("写入抛 OSError 时返回 False", result2 is False)

    # ---- bat 侧：读 UTF-8 前先 chcp 65001，读后还原，且走绝对路径 ------
    broot = os.path.join(tmp, "shortcuts-encoding-bat")
    os.makedirs(broot, exist_ok=True)
    bat = open(_write_bat(broot), encoding="ascii").read()
    check("生成的 bat 在读 shortcuts.txt 前切到 65001",
          "%SystemRoot%\\System32\\chcp.com 65001 >nul" in bat)
    check("生成的 bat 读完后恢复原代码页",
          "%SystemRoot%\\System32\\chcp.com %OLDCP% >nul" in bat)
    check("生成的 bat 先捕获原代码页再切",
          'for /f "tokens=2 delims=:" %%C in (\'%SystemRoot%\\System32\\chcp.com\')'
          ' do set "OLDCP=%%C"' in bat)
    check("生成的 bat 里 chcp 也走绝对路径（没有裸 chcp）",
          re.search(r"(?im)^\s*chcp\s", bat) is None)


def _kill_block(bat_path: str) -> list[str]:
    """从生成的 uninstall.bat 里**原样**取出「按端口杀后端」那一段。"""
    lines = open(bat_path, encoding="ascii").read().splitlines()
    start = next(i for i, l in enumerate(lines) if 'for /f "tokens=5"' in l)
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == ")")
    return lines[start:end + 1]


#: 那段杀进程逻辑里必须以绝对路径调用的工具（AW-5 后要重定向到替身）。
_STUB_RETARGET_TOOLS = ("netstat", "tasklist", "taskkill", "findstr")


def _retarget_tools(block_text: str, stub: str) -> tuple[str, list[str]]:
    r"""把切出来的那段里的 `%SystemRoot%\System32\<tool>.exe` 换成 stub 目录里的替身。

    为什么要换（AW-5）：生成的脚本现在用绝对路径调工具，而 cmd **拒绝执行一个以
    `.exe` 命名的批处理**（实测：报「不是有效的 Win32 应用程序」），所以没法把
    PATH 替身直接搬成 `.exe`。这里把每个工具引用**原样**换成 `<stub>\<tool>.bat`
    （`findstr` 用真的 `findstr.exe` 拷贝，它只读、无害）。替换是逐 token 的，且
    **逐个断言真的发生**：生成器若改回裸名或换了写法，返回的 `missing` 非空 →
    调用方判 FAIL，不会静默替换不到、让行为用例假绿。
    """
    missing: list[str] = []
    for tool in _STUB_RETARGET_TOOLS:
        token = "%%SystemRoot%%\\System32\\%s.exe" % tool
        if token not in block_text:
            missing.append(tool)
            continue
        ext = ".exe" if tool == "findstr" else ".bat"
        block_text = block_text.replace(token, os.path.join(stub, tool + ext))
    return block_text, missing


def _run_kill_block(tmp: str, name: str, rows: list[str],
                    images: dict) -> tuple[list[str], list[str]]:
    """把那一段放进一个最小 bat 里跑一遍，返回 (taskkill 收到的每行参数, 没替换到的工具)。

    netstat / tasklist / taskkill 是 stub 目录里的替身 .bat，findstr 是真的
    findstr.exe 拷贝 —— **真的 taskkill 一次都不调用**（红线）。为什么只跑这一段、
    而不是整个卸载脚本：cmd 执行**另一个 .bat 且不加 `call`** 时不会返回（替身
    taskkill.bat 会顶掉调用者），而脚本里第一句 `%SystemRoot%\\...\\taskkill.exe
    /F /IM DSHLauncher.exe` 就会撞上这点，后面的端口循环根本轮不到执行。这一段是从
    生成的脚本里切出来的，所以钉住的仍然是生成器写出来的东西——AW-5 后按 token
    重定向到替身（见 `_retarget_tools`），重定向是否成功由返回的 `missing` 报出来。
    """
    work = os.path.join(tmp, name)
    stub = os.path.join(work, "stub")
    os.makedirs(stub, exist_ok=True)
    shutil.copy2(_sys("findstr.exe"), os.path.join(stub, "findstr.exe"))
    log = os.path.join(work, "kills.txt")

    def w(fname, text):
        with open(os.path.join(stub, fname), "w", newline="\r\n") as fh:
            fh.write(text)

    w("netstat.bat", "@echo off\n" + "\n".join("echo " + r for r in rows) + "\n")
    w("tasklist.bat", "@echo off\n" + "\n".join(
        'if "%%~2"=="PID eq %d" echo "%s","%d","Console","1","10 K"'
        % (pid, images[pid], pid) for pid in images) + "\n")
    w("taskkill.bat", '@echo off\n>>"%DSH_TEST_KILL_LOG%" echo %*\n')

    root = os.path.join(work, "inst")
    os.makedirs(root, exist_ok=True)
    block_text = "\n".join(_kill_block(_write_bat(root)))
    block_text, missing = _retarget_tools(block_text, stub)
    harness = os.path.join(work, "harness.bat")
    with open(harness, "w", newline="\r\n") as fh:
        fh.write("@echo off\n" + block_text + "\n")

    env = dict(os.environ)
    env["PATH"] = stub
    env["DSH_TEST_KILL_LOG"] = log
    subprocess.run([_sys("cmd.exe"), "/c", harness], stdin=subprocess.DEVNULL,
                   capture_output=True, env=env, cwd=stub, timeout=60,
                   creationflags=0x08000000)
    kills: list[str] = []
    if os.path.exists(log):
        with open(log, encoding="mbcs") as fh:
            kills = [line.strip() for line in fh if line.strip()]
    return kills, missing


def _check_port_kill_behavior(tmp: str) -> None:
    """AW-4 行为层：真的跑一遍生成出来的那段杀进程逻辑（进程工具全是替身）。"""
    # 顺序是刻意的：唯一可杀的那条放最后，替身 taskkill 顶掉调用者之前，
    # 其余几条都会被真的判断一遍。
    rows = [_NS_ROWS[2222], _NS_ROWS[3333], _NS_ROWS[4444],
            _NS_ROWS[5555], _NS_ROWS[6666], _NS_ROWS[1111]]
    kills, missing = _run_kill_block(tmp, "kill-mixed", rows, _NS_IMAGES)
    # AW-5：这一段现在用绝对路径调工具，行为用例靠 _retarget_tools 把 token 换成
    # 替身；没换到就说明生成器改了写法 —— 直接判 FAIL，别让后面几条默默变绿/变红。
    check("行为用例：生成的 bat 仍按绝对路径调工具（重定向没落空）",
          missing == [], missing)
    check("混合列表里只杀了精确 :3080 上的 node.exe",
          kills == ["/PID 1111 /T /F"], kills)
    check("杀的是进程树（带 /T）", bool(kills) and "/T" in kills[0], kills)
    check(":30801 / :30800 上的 node.exe 没被杀",
          all("2222" not in k and "3333" not in k for k in kills), kills)
    check(":3080 上不是 node.exe 的进程没被杀",
          all("4444" not in k for k in kills), kills)
    check("ESTABLISHED 行（本地/对端 :3080）没被杀",
          all("5555" not in k and "6666" not in k for k in kills), kills)

    # 单条场景：判定不成立就一个都不杀（脚本跑到底，日志文件根本不会出现）。
    only_other, _ = _run_kill_block(tmp, "kill-nonnode", [_NS_ROWS[4444]], _NS_IMAGES)
    check("端口对但镜像不是 node.exe → 一个都不杀", only_other == [], only_other)
    only_sub, _ = _run_kill_block(tmp, "kill-substr", [_NS_ROWS[2222]], _NS_IMAGES)
    check(":30801 上的 node.exe → 一个都不杀", only_sub == [], only_sub)


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
    #     也必须被删掉，连脚本自己一起。这条以前没覆盖——隔离环境把 cmd 从 PATH
    #     拿掉了，`start /b cmd /c rmdir /s /q "\\?\%DIR%"` 是空操作（也正是 AW-8
    #     记的管道挂起现象）。现在 stub PATH 里补了 cmd.exe，这条路径真的会跑。
    #     AW-8 之后收尾是「detached cmd 先 del 脚本、再 rmdir 裸 %DIR%」，不再用
    #     cmd 会拒绝的 extended-length 路径，所以目录真的会被删干净。
    root5 = os.path.join(tmp, "clean-install")
    os.makedirs(os.path.join(root5, "harness"))
    with open(os.path.join(root5, "harness", marker_name), "w", encoding="ascii") as f:
        f.write('{"version": "test"}')
    os.makedirs(os.path.join(root5, "launcher"))
    os.makedirs(os.path.join(root5, "runtime"))
    bat5 = _write_bat(root5)
    _rc, out5 = _run_bat(bat5, env)
    check("无保留项：脚本跑到底（Uninstall finished）", "Uninstall finished" in out5,
          out5[-200:])
    check("无保留项：没有列出任何保留项", "LEFT IN PLACE" not in out5, out5[-200:])
    # 收尾的删除是 detached 进程异步做的（`start /b`），轮询等它消失。
    gone = False
    deadline = time.time() + 20
    while time.time() < deadline:
        if not os.path.isdir(root5):
            gone = True
            break
        time.sleep(0.2)
    check("无保留项：安装根目录被删掉", gone, "目录仍在：%s" % root5)
    check("无保留项：卸载脚本自己也一起没了（自删生效）",
          gone and not os.path.exists(bat5), "bat 仍在：%s" % bat5)


def _check_shortcut_cleanup_behavior(tmp: str, env: dict) -> None:
    """AW-6 行为层：只删 shortcuts.txt 记录的快捷方式，用户自建的保留。

    构造得让旧写法必然失败：一个用户自建的 `DSH其他.lnk` 与安装器自己的
    `DSH.lnk` 同处一个目录（桌面 + 开始菜单）。旧写法里
    `del /q "%USERPROFILE%\\Desktop\\DSH*.lnk"` 会通配删掉桌面上那个，
    `rmdir /s /q "...\\Programs\\DSH"` 会连整个开始菜单文件夹一起删掉。
    只有记在 shortcuts.txt 里的项该被删。全程在 tempfile 里，USERPROFILE /
    APPDATA 由 `_isolated_env` 指向临时目录，碰不到真实桌面与开始菜单。
    """
    import installer
    marker_name = installer.MARKER_NAME

    root = os.path.join(tmp, "shortcut-cleanup")
    os.makedirs(os.path.join(root, "harness"))
    with open(os.path.join(root, "harness", marker_name), "w", encoding="ascii") as f:
        f.write('{"version": "test"}')
    os.makedirs(os.path.join(root, "launcher"))
    os.makedirs(os.path.join(root, "runtime"))

    desktop = os.path.join(env["USERPROFILE"], "Desktop")
    start_menu = os.path.join(env["APPDATA"], "Microsoft", "Windows",
                              "Start Menu", "Programs", "DSH")
    os.makedirs(start_menu, exist_ok=True)
    # 安装器自己的两个快捷方式（会写进 shortcuts.txt）……
    mine = [os.path.join(desktop, "DSH.lnk"),
            os.path.join(start_menu, "DSH.lnk")]
    # ……以及用户自建的、名字同样以 DSH 开头的两个（不在清单里）。
    theirs = [os.path.join(desktop, "DSH其他.lnk"),
              os.path.join(start_menu, "DSH其他.lnk")]
    for path in mine + theirs:
        with open(path, "w", encoding="ascii") as f:
            f.write("lnk")
    with open(os.path.join(root, "shortcuts.txt"), "w", encoding="ascii") as f:
        f.write("\n".join(mine))

    _rc, out = _run_bat(_write_bat(root), env)

    check("AW-6：shortcuts.txt 记录的桌面快捷方式被删",
          not os.path.exists(mine[0]), out[-200:])
    check("AW-6：shortcuts.txt 记录的开始菜单快捷方式被删",
          not os.path.exists(mine[1]), out[-200:])
    check("AW-6：用户自建的桌面 DSH其他.lnk 被保留（旧写法会通配删掉）",
          os.path.exists(theirs[0]))
    check("AW-6：用户自建的开始菜单 DSH其他.lnk 被保留（旧写法会递归删掉）",
          os.path.exists(theirs[1]))
    check("AW-6：开始菜单目录里还有别的东西时，目录本身被保留",
          os.path.isdir(start_menu))


def _check_shortcuts_encoding_behavior(tmp: str, env: dict) -> None:
    r"""AW-7 行为层：生成的 bat 真的能删掉一个非 ASCII 名字的快捷方式。

    这是 `chcp 65001` 的端到端证明：名字取本机 ANSI 代码页表示不了的字符
    （cp936 上的亚美尼亚字母），shortcuts.txt 用 UTF-8 写（`write_shortcuts_file`）。
    把 chcp 那两行拿掉，cmd 会用当前代码页解码这个文件，这个名字的快捷方式就删不掉
    （实测）——而旧的 mbcs 写法连文件都写不出来。全程在 tempfile 里，
    `_isolated_env` 把 USERPROFILE/APPDATA/SystemRoot/PATH 改道到临时目录，
    碰不到真实桌面与开始菜单。
    """
    import installer
    bad = _mbcs_unrepresentable()
    if not bad:
        print("SKIP   AW-7 行为层：本机 ANSI 代码页能表示探针字符，跳过")
        return

    root = os.path.join(tmp, "shortcuts-encoding-behavior")
    os.makedirs(os.path.join(root, "harness"))
    with open(os.path.join(root, "harness", installer.MARKER_NAME), "w",
              encoding="ascii") as f:
        f.write('{"version": "test"}')
    os.makedirs(os.path.join(root, "launcher"))
    os.makedirs(os.path.join(root, "runtime"))

    targets = os.path.join(tmp, "shortcuts-encoding-targets")
    os.makedirs(targets, exist_ok=True)
    mine = [os.path.join(targets, "DSH%s.lnk" % bad),
            os.path.join(targets, "DSH.lnk")]
    for p in mine:
        with open(p, "w", encoding="ascii") as f:
            f.write("lnk")
    installer.write_shortcuts_file(root, mine)

    _rc, out = _run_bat(_write_bat(root), env)

    check("AW-7：非 ASCII 名字的快捷方式被删掉（chcp 65001 生效）",
          not os.path.exists(mine[0]), out[-200:])
    check("AW-7：ASCII 名字的快捷方式也被删掉", not os.path.exists(mine[1]))


def _check_stale_wording() -> None:
    """AW-12：过时的用户可见文案（前端构建 / 4 GB / 旧包管理器名）不能再出现。

    纯字符串断言，放在注册表护栏之外，永远会跑。内存那条把 `_total_ram_gb`
    打桩成一个小值，逼出「内存偏小」分支再检查它的提示文案；`_reg_query` 同理
    打桩，避免真的去读注册表。
    """
    import preflight
    import installer

    # 1) 内存提示：现在没有本地构建，提示不能再提「构建前端」或 4 GB
    saved_ram = preflight._total_ram_gb
    try:
        preflight._total_ram_gb = lambda: 1.0
        low = preflight._check_memory()
        preflight._total_ram_gb = lambda: 64.0
        enough = preflight._check_memory()
    finally:
        preflight._total_ram_gb = saved_ram
    hint = low.hint or ""
    check("AW-12：内存不足的提示不再提「构建前端」", "构建前端" not in hint, hint)
    check("AW-12：内存不足的提示说明现状（没有本地构建）",
          "没有本地构建" in hint, hint)
    check("AW-12：内存不足的提示不再出现被删掉的 tsc 构建的 4 GB",
          "4 GB" not in hint, hint)
    check("AW-12：内存不足的提示给出实测量级（不到 1 GB）",
          "1 GB" in hint, hint)
    check("AW-12：内存门限按实测下调（不再是被删掉的 tsc 构建的 4 GB）",
          preflight.REQUIRED_RAM_GB == 2.0, preflight.REQUIRED_RAM_GB)
    check("AW-12：内存不足的 detail 用同一个门限",
          "%.0f GB" % preflight.REQUIRED_RAM_GB in (low.detail or ""),
          low.detail)
    check("AW-12：内存够用时不给提示", not (enough.hint or ""), enough.hint)
    check("AW-12：内存够用时状态是 ok",
          enough.status == preflight.OK, enough.status)

    # 2) 「已安装版本」提示：要讲清卸载对非 DSH 文件做什么（AW-2 白名单）
    saved_q = preflight._reg_query
    try:
        preflight._reg_query = lambda *a, **k: "0.2.0-rc.2"
        existing = preflight._check_existing()
    finally:
        preflight._reg_query = saved_q
    ex = existing.hint or ""
    check("AW-12：已有版本的提示提到卸载只删安装器自己创建的文件",
          "安装器自己创建" in ex, ex)
    check("AW-12：已有版本的提示说明其他文件会被保留并列出",
          "保留" in ex and "列出来" in ex, ex)

    # 3) 覆盖安装确认框（抽成了纯函数 installer.overwrite_prompt）
    prompt = installer.overwrite_prompt(r"C:\Users\sechen\DSH")
    check("AW-12：覆盖提示仍点名目标目录",
          r"C:\Users\sechen\DSH" in prompt, prompt)
    check("AW-12：覆盖提示说了「覆盖」", "覆盖" in prompt, prompt)
    check("AW-12：覆盖提示说明卸载只删安装器创建的白名单项",
          "安装器自己创建" in prompt and "launcher" in prompt, prompt)
    check("AW-12：覆盖提示说明白名单外的文件不会被删除、会列出来",
          "不会被删除" in prompt and "列出来" in prompt, prompt)

    # 4) 源码里不能再出现旧包管理器名（现在的链路是 npm）
    #    拼出来写，免得这一行自己命中扫描。
    needle = "pn" + "pm"
    root = os.path.dirname(HERE)
    hits = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if needle in line:
                            hits.append("%s:%d"
                                        % (os.path.relpath(path, root), i))
            except OSError:
                continue
    check("AW-12：仓库里的 .py 源码不再出现旧的包管理器名 %s" % needle,
          hits == [], hits)


# --------------------------------------------------------------------------
# 4j ---- AW-13: the portable Node zip that gets embedded in DSHSetup.exe
# --------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(HERE)
BUILD_PS1 = os.path.join(REPO_ROOT, "scripts", "build.ps1")
NODE_ZIP = os.path.join(REPO_ROOT, "payload", "node-v24.18.0-win-x64.zip")

# Runs inside PowerShell. It parses build.ps1 with the real AST parser, pulls
# out the `Test-FileSha256` function definition and calls it against a tiny
# throwaway file -- so the test exercises the *actual* function in the build
# script, without ever downloading the 35 MB payload.
_PS_HARNESS = r"""
$ErrorActionPreference = 'Stop'
$target = $args[0]
$ast = [System.Management.Automation.Language.Parser]::ParseFile($target, [ref]$null, [ref]$null)
$fn = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Test-FileSha256' }, $true) | Select-Object -First 1
if (-not $fn) { Write-Output 'NOFUNC'; exit 3 }
Invoke-Expression $fn.Extent.Text
$tmp = [System.IO.Path]::GetTempFileName()
try {
    [System.IO.File]::WriteAllText($tmp, 'dsh-aw13-probe', [System.Text.Encoding]::ASCII)
    $good = (Get-FileHash -LiteralPath $tmp -Algorithm SHA256).Hash
    Write-Output ("MATCH " + (Test-FileSha256 -Path $tmp -Expected $good))
    Write-Output ("LOWER " + (Test-FileSha256 -Path $tmp -Expected $good.ToLower()))
    Write-Output ("WRONG " + (Test-FileSha256 -Path $tmp -Expected ('0' * 64)))
    Write-Output ("MISSING " + (Test-FileSha256 -Path ($tmp + '.missing') -Expected $good))
} finally {
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
}
"""


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pick_powershell() -> tuple[str | None, str]:
    """挑一个**真的能跑 `Get-FileHash`** 的 PowerShell；返回 (路径, 原因)。

    为什么不直接 `shutil.which("powershell")`：从 pwsh（PowerShell 7）里启动
    Windows PowerShell 5.1 时，5.1 会继承 PS7 的 `PSModulePath`，于是它先找到
    PS7 的 `Microsoft.PowerShell.Utility`（只支持 Core，5.1 加载不了），
    `Get-FileHash` 反而报「不是 cmdlet」——GitHub runner 的默认 shell 就是 pwsh，
    CI 上第一次跑 `selfcheck.py` 就是这么红的（AW-14 记了这次）。所以两个都**实测**
    一遍，用第一个真能用的；都不可用就返回 (None, 原因)，由调用方 SKIP（规则 9）。
    """
    tried: list[str] = []
    for exe in ("pwsh", "powershell"):
        path = shutil.which(exe)
        if not path:
            continue
        probe = ("if (Get-Command Get-FileHash -ErrorAction SilentlyContinue) "
                 "{ exit 0 } else { exit 4 }")
        try:
            proc = subprocess.run([path, "-NoProfile", "-NonInteractive",
                                   "-Command", probe],
                                  capture_output=True, timeout=60,
                                  creationflags=0x08000000)
        except (OSError, subprocess.SubprocessError) as exc:      # noqa: BLE001
            tried.append("%s（起不来：%s）" % (exe, exc.__class__.__name__))
            continue
        if proc.returncode == 0:
            return path, ""
        tried.append("%s（这个宿主里没有 Get-FileHash）" % exe)
    return None, "、".join(tried) if tried else "PATH 里没有 pwsh 也没有 powershell"


def _check_build_ps1_hash() -> None:
    """AW-13：build.ps1 必须按**预先固定**的 sha256 校验 Node 载荷。

    纯文本断言 + 一次真的 PowerShell 调用。功能那半边只对临时小文件算哈希，
    **绝不下载 35 MB**、也不跑 build.ps1 的下载分支。
    """
    if not os.path.isfile(BUILD_PS1):
        check("AW-13：build.ps1 存在", False, BUILD_PS1)
        return
    with open(BUILD_PS1, encoding="utf-8") as fh:
        text = fh.read()

    # --- 文本层：校验确实接进去了，而且基准是固定常量 -------------------
    check("AW-13：build.ps1 用 Get-FileHash 校验载荷", "Get-FileHash" in text)

    m = re.search(r"\$NODE_ZIP_SHA256\s*=\s*'([0-9A-Fa-f]{64})'", text)
    pinned = m.group(1).upper() if m else ""
    check("AW-13：期望值是预先固定的 64 位 hex 常量（不是下载时算出来的）",
          bool(pinned), m.group(0) if m else "没找到 $NODE_ZIP_SHA256 = '<64hex>'")

    check("AW-13：复用已存在的 zip 前也按固定常量校验（两处调用）",
          text.count("-Expected $NODE_ZIP_SHA256") >= 2,
          text.count("-Expected $NODE_ZIP_SHA256"))

    # 顺序：先校验 → 不通过就删掉旧 zip → 再下载。
    i_verify = text.find("-Expected $NODE_ZIP_SHA256")
    i_remove = text.find("Remove-Item -LiteralPath $NODE_ZIP")
    i_download = text.find("Invoke-WebRequest")
    check("AW-13：校验不过就删掉旧 zip 重新下载",
          -1 < i_verify < i_remove < i_download,
          "verify=%d remove=%d download=%d" % (i_verify, i_remove, i_download))

    check("AW-13：下载后仍校验，对不上直接 throw（不是只 warn）",
          bool(re.search(r"throw\s+\"portable Node zip failed", text)))

    # 基准绝不能是「刚算出来的哈希」——那等于没校验。
    computed = re.search(r"-Expected\s*\(", text)
    check("AW-13：没有把「刚算出的哈希」当基准", computed is None,
          computed.group(0) if computed else "")
    # 反向自检：上面这条正则真的抓得到「算出来的基准」，不是恒真。
    check("AW-13：正则确实能识别「算出来的基准」",
          bool(re.search(r"-Expected\s*\(",
                         "Test-FileSha256 -Path $z -Expected (Get-FileHash $z)")))

    check("AW-13：旧的无条件复用文案已删除",
          'Write-Host "==> portable Node zip already present"' not in text)

    # --- 与真实文件对账（本机 payload 里有那个 zip）---------------------
    if os.path.isfile(NODE_ZIP):
        real = _sha256_file(NODE_ZIP).upper()
        check("AW-13：脚本里的常量 == payload 里真实 zip 的 sha256",
              pinned == real, "脚本 %s / 文件 %s" % (pinned, real))
    else:
        print("---- payload 里没有 node zip，跳过「常量 == 真实文件」这条")

    # --- 函数层：真的让 PowerShell 跑 Test-FileSha256 --------------------
    # 挑一个**真的能用 Get-FileHash** 的 PowerShell —— 见 _pick_powershell()：
    # 光看「哪个 exe 在 PATH 里」会挑到一个跑不动这个函数的（CI 上第一次就是
    # 这么红的）。都不可用就 SKIP，不判失败（规则 9）。
    ps, why = _pick_powershell()
    if not ps:
        print("---- 跳过 Test-FileSha256 的实跑：%s" % why)
        return
    print("---- Test-FileSha256 实跑用：%s" % ps)
    work = tempfile.mkdtemp(prefix="dsh-aw13-")
    harness = os.path.join(work, "probe.ps1")
    try:
        with open(harness, "w", encoding="utf-8") as fh:
            fh.write(_PS_HARNESS)
        # 故意不加 -ExecutionPolicy Bypass；默认策略放行本进程新建的 .ps1。
        proc = subprocess.run(
            [ps, "-NoProfile", "-NonInteractive", "-File", harness, BUILD_PS1],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120)
        err = (proc.stderr or "").strip()
        if proc.returncode != 0 and "execution polic" in err.lower():
            print("---- 执行策略不允许跑 .ps1，跳过 Test-FileSha256 的实跑：%s" % err)
            return
        out = proc.stdout or ""
        vals = {}
        for line in out.splitlines():
            parts = line.strip().split(" ", 1)
            if len(parts) == 2:
                vals[parts[0]] = parts[1]
        check("AW-13：PowerShell 里能取到并运行 Test-FileSha256",
              "MATCH" in vals, (out.strip() or err)[:200])
        check("AW-13：哈希一致时放行", vals.get("MATCH") == "True", vals.get("MATCH"))
        check("AW-13：hex 大小写不同也算一致", vals.get("LOWER") == "True",
              vals.get("LOWER"))
        check("AW-13：哈希不匹配时拒绝（复用/下载都靠这条拒绝）",
              vals.get("WRONG") == "False", vals.get("WRONG"))
        check("AW-13：文件不存在时拒绝", vals.get("MISSING") == "False",
              vals.get("MISSING"))
    finally:
        shutil.rmtree(work, ignore_errors=True)


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

        # 4b ---- 拒绝盘根/系统目录作为安装目录（AW-3）--------------------
        # 纯函数，不碰文件系统也不碰注册表 —— 放在注册表护栏之外，永远会跑。
        _check_target_policy()

        # 4c ---- 按端口杀进程：精确匹配 + 只杀 node.exe（AW-4）------------
        # 策略层与文本层都不碰注册表，放在护栏之外，永远会跑。
        _check_port_kill_policy()
        _check_uninstaller_kill_text(tmp)
        # 4d ---- 生成的 bat 里系统命令一律绝对路径（AW-5）----------------
        # 纯文本断言，不跑脚本、不碰注册表。
        _check_uninstaller_absolute_paths(tmp)

        # 4e ---- 快捷方式清理只删清单里的项、只删空目录（AW-6）------------
        # 纯函数 + 生成的 bat 文本，都不碰注册表，放在护栏之外，永远会跑。
        _check_shortcut_cleanup_text(tmp)

        # 4f ---- shortcuts.txt 的编码陷阱（AW-7）--------------------------
        # 写侧纯函数 + 生成的 bat 文本，都不碰注册表，放在护栏之外。
        _check_shortcuts_encoding(tmp)

        # 4g ---- 收尾的自删/删目录排序（AW-8）-----------------------------
        # 纯文本断言，不跑脚本、不碰注册表，放在护栏之外，永远会跑。
        _check_uninstaller_tail_text(tmp)

        # 4h ---- `--dir` 缺值与 `--auto` 的默认目标（AW-9）-----------------
        # 纯函数 + 早退路径，不装东西、不碰注册表，放在护栏之外，永远会跑。
        _check_cli_args()

        # 4i ---- 过时的用户可见文案（AW-12）--------------------------------
        # 纯字符串断言（内存提示打桩逼出 warn 分支），不碰注册表/文件系统，
        # 放在护栏之外，永远会跑。
        _check_stale_wording()

        # 4j ---- Node 载荷的 sha256 校验（AW-13）----------------------------
        # 纯文本 + 一次真的 PowerShell 调用（只对临时小文件算哈希，不下载、
        # 不跑 build.ps1 的下载分支），不碰注册表，放在护栏之外，永远会跑。
        _check_build_ps1_hash()

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
                               _check_uninstaller_behavior(tmp, env),
                               _check_shortcut_cleanup_behavior(tmp, env),
                               _check_shortcuts_encoding_behavior(tmp, env),
                               _check_port_kill_behavior(tmp)))
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
