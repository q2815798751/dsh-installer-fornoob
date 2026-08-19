#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DeepSeek Harness 一键安装程序 (DSH Setup).

把一个电脑小白需要的全部东西装到一台 Windows 机器上：
  1) 解压 DeepSeek Harness 源码 (repo.tar.gz) 与便携版 Node.js (runtime)
  2) 复制 DSH 启动器 (DSHLauncher.exe) 并写入 repo.txt 指向源码目录
  3) 用 corepack 运行 `pnpm install` 下载全部依赖 (需要联网)
  4) 创建桌面与开始菜单快捷方式、写卸载注册信息
  5) 提供 uninstall.bat 一键卸载

用 PyInstaller onefile 打包, 全部安装负载内嵌在 exe 里。

命令行模式 (供构建/自检用, 不弹窗):
  DSHSetup.exe --auto [--dir <安装目录>] [--node <node.exe>] [--repo <目录>]
"""
from __future__ import annotations

import os
import queue
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import zipfile

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "DeepSeek Harness"
APP_VERSION = "0.1.0-rc.5"
LAUNCHER_DISPLAY = "DSH 启动器"
WEB_PORT = 3080
SINGLETON_PORT = 3199


# --------------------------------------------------------------------------
# resource paths (frozen exe vs source checkout)
# --------------------------------------------------------------------------
def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resource_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.join(_project_root(), "payload")


def _resource(name: str) -> str:
    return os.path.join(_resource_dir(), name)


def resources() -> dict:
    """All payload paths, with dev-mode fallbacks into the source tree."""
    root = _project_root()
    return {
        "repo_tar": _resource("repo.tar.gz"),
        "node_zip": _resource("node-v24.18.0-win-x64.zip"),
        "launcher_exe": _resource("DSHLauncher.exe"),
        "icon": _resource("icon.ico"),
        "make_shortcut_ps1": _resource("make-shortcut.ps1"),
        "dev_launcher_exe": os.path.join(root, "launcher", "dist", "DSHLauncher.exe"),
        "dev_icon": os.path.join(root, "launcher", "icon.ico"),
        "dev_make_shortcut_ps1": os.path.join(root, "installer", "make-shortcut.ps1"),
    }


def _pick(res: dict, key: str, dev_key: str | None = None) -> str:
    p = res[key]
    if os.path.exists(p):
        return p
    if dev_key and os.path.exists(res[dev_key]):
        return res[dev_key]
    return p


def _claim_singleton() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", SINGLETON_PORT))
        s.listen(1)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# install worker
# --------------------------------------------------------------------------
class InstallCancelled(Exception):
    pass


class InstallWorker(threading.Thread):
    def __init__(self, target: str, res: dict, events: "queue.Queue[dict]",
                 cancel: threading.Event, test_mode: bool = False):
        super().__init__(daemon=True)
        self.target = os.path.abspath(target)
        self.res = res
        self.events = events
        self.cancel = cancel
        self.test_mode = test_mode   # --auto: skip desktop/registry integration
        self.log_path = os.path.join(self.target, "install.log")
        self.launcher_dir = os.path.join(self.target, "launcher")
        self.repo_dir = os.path.join(self.target, "repo")
        self.runtime_dir = os.path.join(self.target, "runtime")

    # ---- helpers ----------------------------------------------------------
    def emit(self, kind: str, **kw) -> None:
        self.events.put({"kind": kind, **kw})

    def progress(self, pct: float, text: str) -> None:
        self.emit("progress", pct=pct, text=text)

    def log(self, msg: str) -> None:
        line = time.strftime("[%H:%M:%S] ") + msg + "\n"
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise InstallCancelled()

    # ---- entry ------------------------------------------------------------
    def run(self) -> None:
        try:
            self._install()
            self.emit("done", ok=True, msg="安装完成")
        except InstallCancelled:
            self.log("安装已取消")
            self.emit("done", ok=False, msg="安装已取消")
        except Exception as exc:  # noqa: BLE001
            self.log("!! 安装失败: %r" % (exc,))
            self.emit("done", ok=False, msg="安装失败: %s" % exc)

    def _install(self) -> None:
        self.progress(2, "正在准备…")
        os.makedirs(self.target, exist_ok=True)
        self.log("install target: %s" % self.target)

        # 1) repo source
        self.log("解压源码 -> %s" % self.repo_dir)
        self._extract_tar(_pick(self.res, "repo_tar"), self.repo_dir, 5, 28, "正在解压 DeepSeek Harness 源码…")
        self._check_cancel()

        # 2) portable node
        self.log("解压 Node.js -> %s" % self.runtime_dir)
        self._extract_node(_pick(self.res, "node_zip"), self.runtime_dir, 30, 45, "正在解压 Node.js 运行时…")
        self._check_cancel()

        # 3) launcher
        self.progress(46, "正在安装启动器…")
        os.makedirs(self.launcher_dir, exist_ok=True)
        launcher_exe = _pick(self.res, "launcher_exe", "dev_launcher_exe")
        icon = _pick(self.res, "icon", "dev_icon")
        shutil.copy2(launcher_exe, os.path.join(self.launcher_dir, "DSHLauncher.exe"))
        if os.path.exists(icon):
            shutil.copy2(icon, os.path.join(self.launcher_dir, "icon.ico"))
        with open(os.path.join(self.launcher_dir, "repo.txt"), "w", encoding="utf-8") as f:
            f.write(self.repo_dir)
        self.log("launcher installed -> %s" % self.launcher_dir)
        self._check_cancel()

        # 4) uninstaller + registry (before deps, so a failure is still removable)
        self._write_uninstaller()
        if not self.test_mode:
            self._register_uninstall()

        # 5) dependencies
        self.progress(55, "正在安装依赖 (pnpm install)，首次需要联网，约 5~20 分钟…")
        self.log("start pnpm install (first run needs network)")
        self._pnpm_install()
        self._check_cancel()
        self.log("pnpm install finished")

        # 6) shortcuts
        if not self.test_mode:
            self.progress(93, "正在创建快捷方式…")
            self._make_shortcuts()
        self.progress(100, "完成")
        self.log("install complete: %s" % self.target)

    # ---- extraction -------------------------------------------------------
    def _extract_tar(self, tar_path: str, dest: str, p0: float, p1: float, label: str) -> None:
        if not os.path.exists(tar_path):
            raise RuntimeError("缺少安装负载: %s" % tar_path)
        os.makedirs(dest, exist_ok=True)
        with tarfile.open(tar_path, "r:gz") as tf:
            members = [m for m in tf.getmembers() if not (m.issym() or m.islnk())]
            total = len(members)
            for i, m in enumerate(members):
                self._check_cancel()
                if i % 400 == 0:
                    self.progress(p0 + (p1 - p0) * i / max(total, 1),
                                  "%s (%d/%d)" % (label, i, total))
                try:
                    tf.extract(m, dest, set_attrs=False)
                except OSError:
                    pass  # best-effort per file
        self.progress(p1, label)

    def _extract_node(self, zip_path: str, dest: str, p0: float, p1: float, label: str) -> None:
        if not os.path.exists(zip_path):
            raise RuntimeError("缺少安装负载: %s" % zip_path)
        tmp = dest + ".tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                total = len(names)
                for i, name in enumerate(names):
                    self._check_cancel()
                    if i % 150 == 0:
                        self.progress(p0 + (p1 - p0) * i / max(total, 1),
                                      "%s (%d/%d)" % (label, i, total))
                    try:
                        zf.extract(name, tmp)
                    except OSError:
                        pass
            inner = [d for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))]
            src = os.path.join(tmp, inner[0]) if len(inner) == 1 else tmp
            shutil.rmtree(dest, ignore_errors=True)
            shutil.move(src, dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.progress(p1, label)

    # ---- dependencies -----------------------------------------------------
    def _pnpm_install(self) -> None:
        self._check_cancel()
        node_exe = os.path.join(self.runtime_dir, "node.exe")
        if not os.path.exists(node_exe):
            raise RuntimeError("便携版 node.exe 缺失: %s" % node_exe)
        corepack_js = os.path.join(self.runtime_dir, "node_modules", "corepack", "dist", "corepack.js")
        if not os.path.exists(corepack_js):
            raise RuntimeError("便携版 Node 缺少 corepack，无法引导 pnpm 安装依赖")
        env = dict(os.environ)
        env["PATH"] = self.runtime_dir + os.pathsep + env.get("PATH", "")
        env["COREPACK_ENABLE_DOWNLOAD_PROMPT"] = "0"
        cmd = [node_exe, corepack_js, "pnpm", "install"]
        self.log("$ %s" % " ".join(cmd))
        proc = subprocess.Popen(
            cmd, cwd=self.repo_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env, shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        # stream output into install.log line by line
        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                try:
                    self.log(raw.decode("utf-8", "replace").rstrip("\n"))
                except OSError:
                    pass
                if self.cancel.is_set():
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True, creationflags=0x08000000)
                    raise InstallCancelled()
        finally:
            proc.stdout.close()
        code = proc.wait()
        if code != 0:
            raise RuntimeError("pnpm install 失败 (exit %d)，详见 %s" % (code, self.log_path))

    # ---- uninstaller / registry ------------------------------------------
    def _write_uninstaller(self) -> None:
        """Generate uninstall.bat (pure ASCII). cmd.exe does NOT collapse %%
        outside FOR loops, so batch-parameter expansions use a single % and
        FOR loop variables use %%; the batch deletes itself last via a
        detached process to avoid killing the running script."""
        bat = os.path.join(self.target, "uninstall.bat")
        lines = [
            "@echo off",
            "rem DeepSeek Harness uninstaller (generated by DSH Setup)",
            "setlocal",
            'set "DIR=%~dp0"',
            'if "%DIR:~-1%"=="\\" set "DIR=%DIR:~0,-1%"',
            "echo Stopping DSH Launcher and backend...",
            "taskkill /F /IM DSHLauncher.exe >nul 2>&1",
            'for /f "tokens=5" %%%%p in (\'netstat -ano ^| findstr ":%d" ^| findstr "LISTENING"\') do taskkill /F /PID %%%%p >nul 2>&1' % WEB_PORT,
            "echo Removing shortcuts...",
            'if exist "%~dp0shortcuts.txt" for /f "usebackq delims=" %%L in ("%~dp0shortcuts.txt") do del /q "%%L" >nul 2>&1',
            'del /q "%USERPROFILE%\\Desktop\\DSH*.lnk" >nul 2>&1',
            'if defined OneDrive del /q "%OneDrive%\\Desktop\\DSH*.lnk" >nul 2>&1',
            'rmdir /s /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\DeepSeek Harness" >nul 2>&1',
            "echo Removing registry entry...",
            'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DeepSeekHarness" /f >nul 2>&1',
            "echo Removing install directory...",
            'for /f "delims=" %%F in (\'dir /b /a-d "%~dp0"\') do if /i not "%%F"=="uninstall.bat" del /q "%~dp0%%F" >nul 2>&1',
            'for /d %%D in ("%~dp0*") do rmdir /s /q "\\\\?\\%%~fD" >nul 2>&1',
            "echo Uninstall finished.",
            "pause",
            'start "" /b cmd /c rmdir /s /q "\\\\?\\%DIR%" >nul 2>&1',
            'del "%~f0" >nul 2>&1',
        ]
        with open(bat, "w", encoding="ascii") as f:
            f.write("\r\n".join(lines) + "\r\n")
        self.log("uninstaller written -> %s" % bat)

    def _register_uninstall(self) -> None:
        key = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSeekHarness"
        bat = os.path.join(self.target, "uninstall.bat")
        exe = os.path.join(self.launcher_dir, "DSHLauncher.exe")
        vals = [
            ("DisplayName", 'DeepSeek Harness'),
            ("DisplayVersion", APP_VERSION),
            ("Publisher", "DeepSeek AI"),
            ("InstallLocation", self.target),
            ("DisplayIcon", '"%s,0"' % exe),
            ("UninstallString", 'cmd.exe /c ""%s""' % bat),
        ]
        for name, val in vals:
            subprocess.run(["reg", "add", key, "/f", "/v", name, "/d", val],
                           capture_output=True, creationflags=0x08000000)
        for name in ("NoModify", "NoRepair"):
            subprocess.run(["reg", "add", key, "/f", "/v", name, "/t", "REG_DWORD", "/d", "1"],
                           capture_output=True, creationflags=0x08000000)

    # ---- shortcuts --------------------------------------------------------
    def _desktop_dir(self) -> str:
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                capture_output=True, text=True, creationflags=0x08000000, timeout=20)
            p = out.stdout.strip()
            if p and os.path.isdir(p):
                return p
        except Exception:
            pass
        return os.path.join(os.path.expanduser("~"), "Desktop")

    def _make_shortcuts(self) -> None:
        ps1 = _pick(self.res, "make_shortcut_ps1", "dev_make_shortcut_ps1")
        if not os.path.exists(ps1):
            raise RuntimeError("缺少 make-shortcut.ps1")
        exe = os.path.join(self.launcher_dir, "DSHLauncher.exe")
        icon = os.path.join(self.launcher_dir, "icon.ico")
        desc = "DeepSeek Harness 启动器：启动后端 / 打开网页 / 关闭 / 最小化到托盘"
        lnks = [
            os.path.join(self._desktop_dir(), LAUNCHER_DISPLAY + ".lnk"),
        ]
        start_menu = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                                  "Start Menu", "Programs", "DeepSeek Harness")
        try:
            os.makedirs(start_menu, exist_ok=True)
            lnks.append(os.path.join(start_menu, LAUNCHER_DISPLAY + ".lnk"))
        except OSError:
            pass
        for lnk in lnks:
            self._run_powershell_script(ps1, [
                "-LnkPath", lnk,
                "-TargetPath", exe,
                "-IconPath", icon,
                "-WorkingDirectory", self.launcher_dir,
                "-Description", desc,
            ])
        self.shortcuts = lnks
        # precise list for the uninstaller (ANSI, so cmd reads it under the
        # same locale it was written on)
        try:
            with open(os.path.join(self.target, "shortcuts.txt"), "w", encoding="mbcs") as f:
                f.write("\n".join(lnks))
        except OSError:
            pass

    def _run_powershell_script(self, script: str, args: list[str]) -> None:
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script] + args
        r = subprocess.run(cmd, capture_output=True, text=True,
                           creationflags=0x08000000, timeout=60)
        if r.returncode != 0:
            self.log("shortcut 失败(%d): %s" % (r.returncode, r.stderr.strip()))


# --------------------------------------------------------------------------
# CLI / auto mode (used by the build script and CI-style self-checks)
# --------------------------------------------------------------------------
def _run_auto(argv: list[str]) -> int:
    target = "."
    if "--dir" in argv:
        target = argv[argv.index("--dir") + 1]
    res = resources()
    events: "queue.Queue[dict]" = queue.Queue()
    cancel = threading.Event()
    worker = InstallWorker(target, res, events, cancel, test_mode=True)
    worker.start()
    last_pct = 0
    while worker.is_alive():
        try:
            ev = events.get(timeout=0.25)
        except queue.Empty:
            continue
        if ev["kind"] == "progress":
            pct = int(ev["pct"])
            if pct != last_pct:
                last_pct = pct
                print("PROGRESS %3d%%  %s" % (pct, ev["text"]), flush=True)
        elif ev["kind"] == "log":
            print("  %s" % ev["msg"], flush=True)
        elif ev["kind"] == "done":
            print("DONE ok=%s msg=%s" % (ev["ok"], ev["msg"]), flush=True)
            return 0 if ev["ok"] else 1
    return 1


# --------------------------------------------------------------------------
# tkinter wizard
# --------------------------------------------------------------------------
class SetupUI:
    BG = "#0E1116"
    CARD = "#161B24"
    BORDER = "#222A36"
    TEXT = "#E8ECF3"
    SUBTEXT = "#8A94A8"
    ACCENT = "#4D6BFE"

    def __init__(self, res: dict) -> None:
        self.res = res
        self.root = tk.Tk()
        self.root.title("DeepSeek Harness 一键安装")
        self.root.configure(bg=self.BG)
        self.root.geometry("640x520")
        self.root.minsize(600, 480)
        try:
            self.root.iconbitmap(_pick(res, "icon", "dev_icon"))
        except Exception:
            pass

        self.events: "queue.Queue[dict]" = queue.Queue()
        self.worker: InstallWorker | None = None
        self.cancel = threading.Event()
        self.target_var = tk.StringVar(value=self._default_target())
        self.launch_var = tk.BooleanVar(value=True)
        self._log_text: tk.Text | None = None
        self._bar: ttk.Progressbar | None = None
        self._status_var = tk.StringVar(value="")

        self._frame: tk.Frame | None = None
        self._show_welcome()
        self.root.after(100, self._poll_events)

    def _default_target(self) -> str:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "DeepSeekHarness")

    # ---- page switching ---------------------------------------------------
    def _clear(self) -> None:
        if self._frame is not None:
            self._frame.destroy()

    def _card(self, parent: tk.Widget, pad: int = 14) -> tk.Frame:
        f = tk.Frame(parent, bg=self.CARD, highlightbackground=self.BORDER, highlightthickness=1)
        f.pack(fill="both", expand=True)
        return f

    def _show_welcome(self) -> None:
        self._clear()
        self._frame = tk.Frame(self.root, bg=self.BG, padx=24, pady=20)
        self._frame.pack(fill="both", expand=True)
        tk.Label(self._frame, text="DeepSeek Harness 一键安装",
                 bg=self.BG, fg=self.TEXT, font=("Segoe UI Semibold", 17)).pack(anchor="w")
        tk.Label(self._frame, text="本地运行的 AI Agent 框架（网页界面 http://127.0.0.1:%d）" % WEB_PORT,
                 bg=self.BG, fg=self.SUBTEXT, font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 14))

        card = self._card(self._frame)
        tk.Label(card, text="安装内容：", bg=self.CARD, fg=self.ACCENT,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=12, pady=(10, 4))
        for line in (
            "• DeepSeek Harness 框架（源码 + 内置 Node.js 运行时）",
            "• 桌面快捷方式「%s」（启动后端 / 打开网页 / 关闭 / 最小化到托盘）" % LAUNCHER_DISPLAY,
            "• 开始菜单快捷方式与「设置 → 应用」卸载入口",
        ):
            tk.Label(card, text=line, bg=self.CARD, fg=self.TEXT,
                     font=("Segoe UI", 10)).pack(anchor="w", padx=12)

        tk.Label(card, text="首次安装需要联网以下载依赖（约 5~20 分钟，占用约 2 GB 磁盘空间）。",
                 bg=self.CARD, fg="#E8A23D", font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(8, 10))

        row = tk.Frame(self._frame, bg=self.BG)
        row.pack(fill="x", pady=(16, 0))
        tk.Label(row, text="安装目录：", bg=self.BG, fg=self.TEXT, font=("Segoe UI", 10)).pack(side="left")
        ent = tk.Entry(row, textvariable=self.target_var, bg=self.CARD, fg=self.TEXT,
                       insertbackground=self.TEXT, relief="flat", font=("Consolas", 9))
        ent.pack(side="left", fill="x", expand=True, padx=8, ipady=4)
        tk.Button(row, text="浏览…", command=self._browse, bg=self.CARD, fg=self.TEXT,
                  activebackground=self.BORDER, relief="flat", cursor="hand2").pack(side="left")

        btns = tk.Frame(self._frame, bg=self.BG)
        btns.pack(fill="x", pady=(18, 0))
        tk.Button(btns, text="退出", command=self.root.destroy, bg=self.CARD, fg=self.SUBTEXT,
                  activebackground=self.BORDER, relief="flat", width=10, cursor="hand2").pack(side="left")
        tk.Button(btns, text="开始安装", command=self._begin, bg=self.ACCENT, fg="#FFFFFF",
                  activebackground="#5B7BFF", relief="flat", width=14, cursor="hand2").pack(side="right")

    def _browse(self) -> None:
        d = filedialog.askdirectory(title="选择安装目录", initialdir=self.target_var.get())
        if d:
            self.target_var.set(d)

    def _show_install(self) -> None:
        self._clear()
        self._frame = tk.Frame(self.root, bg=self.BG, padx=24, pady=20)
        self._frame.pack(fill="both", expand=True)
        tk.Label(self._frame, text="正在安装…", bg=self.BG, fg=self.TEXT,
                 font=("Segoe UI Semibold", 15)).pack(anchor="w")
        tk.Label(self._frame, textvariable=self._status_var, bg=self.BG, fg=self.SUBTEXT,
                 font=("Segoe UI", 10), wraplength=560, justify="left").pack(anchor="w", pady=(4, 12))
        self._bar = ttk.Progressbar(self._frame, maximum=100, value=0)
        self._bar.pack(fill="x")
        logwrap = tk.Frame(self._frame, bg=self.CARD, highlightbackground=self.BORDER, highlightthickness=1)
        logwrap.pack(fill="both", expand=True, pady=(14, 0))
        self._log_text = tk.Text(logwrap, bg=self.CARD, fg="#B7C2D4", relief="flat",
                                 font=("Consolas", 8), wrap="none", state="disabled",
                                 highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(logwrap, orient="vertical", command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log_text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        self._cancel_btn = tk.Button(self._frame, text="取消", command=self._cancel_click,
                                     bg=self.CARD, fg=self.SUBTEXT, activebackground=self.BORDER,
                                     relief="flat", width=10, cursor="hand2")
        self._cancel_btn.pack(anchor="e", pady=(12, 0))

        # start the worker
        self.cancel.clear()
        self._worker = InstallWorker(self.target_var.get(), self.res, self.events, self.cancel)
        self._worker.start()
        self._log_offsets: dict = {}
        self.root.after(300, self._poll_log)

    def _show_done(self, ok: bool, msg: str) -> None:
        self._clear()
        self._frame = tk.Frame(self.root, bg=self.BG, padx=24, pady=20)
        self._frame.pack(fill="both", expand=True)
        color = "#18B358" if ok else "#E03B41"
        tk.Label(self._frame, text=("安装完成 🎉" if ok else "安装未完成"),
                 bg=self.BG, fg=color, font=("Segoe UI Semibold", 17)).pack(anchor="w")
        tk.Label(self._frame, text=msg, bg=self.BG, fg=self.TEXT,
                 font=("Segoe UI", 10), wraplength=560, justify="left").pack(anchor="w", pady=(6, 10))
        if ok:
            tk.Checkbutton(self._frame, text="立即启动「%s」（自动运行后端并驻留系统托盘）" % LAUNCHER_DISPLAY,
                           variable=self.launch_var, bg=self.BG, fg=self.TEXT,
                           activebackground=self.BG, selectcolor=self.CARD,
                           font=("Segoe UI", 10), cursor="hand2").pack(anchor="w")
            tk.Label(self._frame,
                     text="提示：首次打开网页后，请到「设置 → 模型」填入你的 DeepSeek API Key。\n"
                          "关闭窗口不会停止后端；点启动器里的「关闭」或运行 uninstall.bat 可彻底停止。",
                     bg=self.BG, fg=self.SUBTEXT, font=("Segoe UI", 9), justify="left",
                     wraplength=560).pack(anchor="w", pady=(10, 0))
        else:
            tk.Label(self._frame, text="安装日志：%s" % self._worker.log_path if self._worker else msg,
                     bg=self.BG, fg=self.SUBTEXT, font=("Segoe UI", 9), wraplength=560,
                     justify="left").pack(anchor="w")
        btns = tk.Frame(self._frame, bg=self.BG)
        btns.pack(fill="x", pady=(18, 0))
        tk.Button(btns, text="退出", command=self.root.destroy, bg=self.CARD, fg=self.SUBTEXT,
                  activebackground=self.BORDER, relief="flat", width=10, cursor="hand2").pack(side="left")
        if ok:
            tk.Button(btns, text="完成", command=self._finish, bg=self.ACCENT, fg="#FFFFFF",
                      activebackground="#5B7BFF", relief="flat", width=14, cursor="hand2").pack(side="right")
        else:
            tk.Button(btns, text="重试", command=self._show_install, bg=self.ACCENT, fg="#FFFFFF",
                      activebackground="#5B7BFF", relief="flat", width=14, cursor="hand2").pack(side="right")

    # ---- actions ----------------------------------------------------------
    def _begin(self) -> None:
        target = self.target_var.get().strip()
        if not target:
            messagebox.showwarning("提示", "请选择安装目录", parent=self.root)
            return
        if os.path.isdir(target) and os.listdir(target):
            if not messagebox.askyesno("提示", "目录已存在且不为空：\n%s\n\n将覆盖安装（已存在的文件会被覆盖），继续吗？" % target,
                                       parent=self.root):
                return
        self._show_install()

    def _cancel_click(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            if messagebox.askyesno("取消", "确定要取消安装吗？", parent=self.root):
                self.cancel.set()
                self._cancel_btn.config(state="disabled", text="正在取消…")

    def _finish(self) -> None:
        if self.launch_var.get() and self._worker is not None:
            exe = os.path.join(self._worker.launcher_dir, "DSHLauncher.exe")
            if os.path.exists(exe):
                try:
                    subprocess.Popen([exe], cwd=self._worker.launcher_dir,
                                     creationflags=0x08000000)
                except Exception:
                    pass
        self.root.destroy()

    # ---- event / log polling ----------------------------------------------
    def _poll_events(self) -> None:
        try:
            while True:
                ev = self.events.get_nowait()
                if ev["kind"] == "progress":
                    self._status_var.set(ev["text"])
                    if self._bar is not None:
                        self._bar["value"] = ev["pct"]
                elif ev["kind"] == "done":
                    self._show_done(ev["ok"], ev["msg"])
                    return
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _poll_log(self) -> None:
        if self._log_text is None or self._worker is None:
            return
        path = self._worker.log_path
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    data = f.read()
                self._log_text.config(state="normal")
                self._log_text.delete("1.0", "end")
                self._log_text.insert("end", data)
                self._log_text.see("end")
                self._log_text.config(state="disabled")
        except OSError:
            pass
        self.root.after(400, self._poll_log)


def _run_selfcheck() -> int:
    """Headless check that every payload resource made it into the frozen exe.
    Writes selfcheck.json next to the exe (a windowed exe has no stdout)."""
    import json
    res = resources()
    rep: dict = {"frozen": bool(getattr(sys, "frozen", False)), "resources": {}}
    checks = {
        "repo_tar": _pick(res, "repo_tar"),
        "node_zip": _pick(res, "node_zip"),
        "launcher_exe": _pick(res, "launcher_exe", "dev_launcher_exe"),
        "icon": _pick(res, "icon", "dev_icon"),
        "make_shortcut_ps1": _pick(res, "make_shortcut_ps1", "dev_make_shortcut_ps1"),
    }
    for key, p in checks.items():
        rep["resources"][key] = {
            "exists": os.path.exists(p),
            "mb": round(os.path.getsize(p) / 1048576.0, 1) if os.path.exists(p) else 0,
        }
    ok = all(rep["resources"][k]["exists"] for k in checks)
    rep["ok"] = ok
    out = os.path.join(os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else ".",
                       "selfcheck.json")
    try:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, ensure_ascii=False)
    except OSError:
        pass
    return 0 if ok else 1


def main() -> int:
    if not _claim_singleton():
        messagebox.showwarning(APP_NAME, "安装程序已在运行。")
        return 1
    res = resources()
    if "--selfcheck" in sys.argv:
        return _run_selfcheck()
    if "--auto" in sys.argv:
        return _run_auto(sys.argv)
    SetupUI(res).root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
