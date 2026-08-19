#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH Launcher — frameless dark popup that starts / opens / stops the
DeepSeek Harness web UI (dsh web, http://127.0.0.1:3080).

Zero external dependencies: stdlib only (tkinter + subprocess + socket +
ctypes for the system-tray icon). Launch with pythonw.exe (no console).
All state lives under ./data/.

Buttons:
    启动  -> spawn  node --import tsx/esm apps/cli/src/bin.ts web  (PID -> data/pid.txt)
    打开  -> if not running, start first; open UI in Chrome
    关闭  -> taskkill the process tree listening on :3080 (pid.txt first, netstat fallback)
    最小化 -> hide the window to the system tray (notification area); the harness keeps running

Tray icon (always present while the launcher runs):
    double-click / 显示  -> restore the window
    启动后端 / 打开网页 / 关闭后端 / 退出  -> mirror the buttons

Window X / 退出 closes only this popup — the harness keeps running until 关闭.
"""
from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
import threading
import traceback
from ctypes import wintypes

# --------------------------------------------------------------------------
# paths / config
# --------------------------------------------------------------------------
def _launcher_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)    # PyInstaller: next to the exe
    return os.path.dirname(os.path.abspath(__file__))


LAUNCHER_DIR = _launcher_dir()
REPO_DIR = os.path.dirname(LAUNCHER_DIR)          # …/deepseek-harness
_repo_override = os.path.join(LAUNCHER_DIR, "repo.txt")
if os.path.exists(_repo_override):
    try:
        # utf-8-sig: tolerate a UTF-8 BOM some editors / Set-Content add.
        with open(_repo_override, encoding="utf-8-sig") as _f:
            _repo = _f.read().strip()
        if _repo:
            REPO_DIR = os.path.abspath(_repo)
    except OSError:
        pass
DATA_DIR = os.path.join(LAUNCHER_DIR, "data")
PID_FILE = os.path.join(DATA_DIR, "pid.txt")
LOG_FILE = os.path.join(DATA_DIR, "web.log")
ERROR_FILE = os.path.join(DATA_DIR, "error.log")
if getattr(sys, "frozen", False):
    _res_dir = getattr(sys, "_MEIPASS", LAUNCHER_DIR)
    ICON = os.path.join(_res_dir, "icon.ico")     # bundled inside the exe
else:
    ICON = os.path.join(LAUNCHER_DIR, "icon.ico")


def _resolve_node() -> str:
    """Prefer a bundled portable Node runtime next to the installation, then
    fall back to whatever `node` is on PATH. Keeps the launcher self-contained
    on machines where Node is not installed globally."""
    for p in (
        os.path.join(LAUNCHER_DIR, "runtime", "node.exe"),
        os.path.join(LAUNCHER_DIR, "node", "node.exe"),
        os.path.join(os.path.dirname(REPO_DIR), "runtime", "node.exe"),
    ):
        if os.path.exists(p):
            return p
    return "node"


NODE = _resolve_node()

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_X86 = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
# Overridable via DSH_LAUNCHER_PORT so the same launcher can be smoke-tested
# on a free port without disturbing an already-running instance.
WEB_PORT = int(os.environ.get("DSH_LAUNCHER_PORT", "3080"))
WEB_URL = f"http://127.0.0.1:{WEB_PORT}"
VERSION = "1.1.0"
SINGLETON_PORT = 3099
_singleton: socket.socket | None = None


def _start_cmd() -> list[str]:
    cmd = [NODE, "--import", "tsx/esm", "apps/cli/src/bin.ts", "web"]
    if WEB_PORT != 3080:
        cmd += ["--port", str(WEB_PORT)]
    return cmd


def _claim_singleton() -> bool:
    """Bind a local port as a single-instance lock. Only one popup may run."""
    global _singleton
    _singleton = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _singleton.bind(("127.0.0.1", SINGLETON_PORT))
        _singleton.listen(1)
        return True
    except OSError:
        try:
            _singleton.close()
        except OSError:
            pass
        _singleton = None
        return False


def _focus_existing_window() -> None:
    """Bring the already-open popup to the foreground (second shortcut click)."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "DSH Launcher")
        if hwnd:
            user32.ShowWindow(hwnd, 9)          # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


# --------------------------------------------------------------------------
# core logic (no tkinter) — also importable for headless testing
# --------------------------------------------------------------------------
def is_running(port: int = WEB_PORT) -> bool:
    """True if something is listening on the dsh web port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.35):
            return True
    except OSError:
        return False


def _pid_alive(pid: int) -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                             capture_output=True, text=True, creationflags=0x08000000)
        return str(pid) in out.stdout
    except Exception:
        return False


def _pids_on_port(port: int) -> list[int]:
    """PIDs whose sockets listen on the given port (via netstat)."""
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                         creationflags=0x08000000).stdout
    pids: list[int] = []
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line.upper():
            toks = line.split()
            if toks:
                try:
                    pids.append(int(toks[-1]))
                except ValueError:
                    pass
    return pids


def _read_pid() -> int | None:
    try:
        with open(PID_FILE, encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return None


def _write_pid(pid: int) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(pid))


def start_server() -> int | None:
    """Spawn dsh web in the background. Returns the new PID, or None if
    already running / spawn failed."""
    if is_running():
        return None
    os.makedirs(DATA_DIR, exist_ok=True)
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        log = open(LOG_FILE, "ab", buffering=0)
    except OSError:
        log = None
    try:
        proc = subprocess.Popen(
            _start_cmd(), cwd=REPO_DIR, stdout=log, stderr=log,
            startupinfo=info, creationflags=subprocess.CREATE_NO_WINDOW,
            shell=False,
        )
    except Exception:
        if log is not None:
            log.close()
        return None
    _write_pid(proc.pid)
    return proc.pid


def stop_server() -> int:
    """Terminate the dsh web process tree. Returns how many PIDs were killed."""
    pids: list[int] = []
    pid = _read_pid()
    if pid and _pid_alive(pid):
        pids.append(pid)
    for p in _pids_on_port(WEB_PORT):
        if p not in pids:
            pids.append(p)
    for p in pids:
        try:
            subprocess.run(["taskkill", "/PID", str(p), "/T", "/F"],
                           capture_output=True, creationflags=0x08000000)
        except Exception:
            pass
    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
    return len(pids)


def _wait_ready(timeout: float) -> bool:
    import time
    end = time.time() + timeout
    while time.time() < end:
        if is_running():
            return True
        time.sleep(0.4)
    return is_running()


def _chrome_path() -> str | None:
    for p in (CHROME, CHROME_X86):
        if os.path.exists(p):
            return p
    return None


def open_ui() -> bool:
    """Open the harness UI in Chrome, starting the server first if needed."""
    if not is_running():
        start_server()
        _wait_ready(10.0)
    chrome = _chrome_path()
    if chrome is None:
        return False
    subprocess.Popen([chrome, WEB_URL], creationflags=0x08000000)
    return True


# --------------------------------------------------------------------------
# Windows system-tray icon (stdlib ctypes — no external deps)
# --------------------------------------------------------------------------
class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt", _POINT)]


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeout", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
    ]


_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


def _setup_win32_prototypes() -> None:
    """Pin argument/return types so ctypes does not truncate 64-bit pointers."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    shell32 = ctypes.windll.shell32

    user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
    user32.RegisterClassW.restype = ctypes.c_ushort
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.DestroyIcon.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.CreatePopupMenu.argtypes = []
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.DestroyMenu.restype = wintypes.BOOL
    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.AppendMenuW.restype = wintypes.BOOL
    user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
    user32.TrackPopupMenu.restype = ctypes.c_int
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.GetMessageW.argtypes = [ctypes.POINTER(_MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [ctypes.POINTER(_MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(_MSG)]
    user32.DispatchMessageW.restype = ctypes.c_ssize_t

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = wintypes.DWORD

    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(_NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL


try:
    _setup_win32_prototypes()
except Exception:
    pass


class _TrayIcon:
    """A minimal Shell_NotifyIcon wrapper that runs its own message loop in a
    background thread. tkinter keeps its own loop on the main thread, so the
    two communicate through a thread-safe queue that the Launcher polls with
    `after`. Events are opaque strings/ints; the Launcher decides what to do."""

    WM_USER = 0x0400
    WM_TRAY = WM_USER + 20
    WM_LBUTTONUP = 0x0202
    WM_LBUTTONDBLCLK = 0x0203
    WM_RBUTTONUP = 0x0205
    WM_QUIT = 0x0012
    WM_NULL = 0x0000
    WM_DESTROY = 0x0002
    NIM_ADD = 0
    NIM_DELETE = 2
    NIF_MESSAGE = 1
    NIF_ICON = 2
    NIF_TIP = 4
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x10
    LR_DEFAULTSIZE = 0x40
    HWND_MESSAGE = -3
    MF_STRING = 0
    MF_SEPARATOR = 0x800
    TPM_RETURNCMD = 0x0100
    TPM_NONOTIFY = 0x0080
    TPM_RIGHTBUTTON = 0x0002
    TPM_BOTTOMALIGN = 0x0020

    def __init__(self, icon_path: str, tooltip: str,
                 menu_items: list[tuple[int, str, bool]]) -> None:
        """menu_items: list of (id, label, is_separator)."""
        self.icon_path = icon_path
        self.tooltip = tooltip
        self.menu_items = menu_items
        self.queue: "queue.Queue[tuple]" = __import__("queue").Queue()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._hwnd = None
        self._hicon = None
        self._proc_ref = None
        self._wc_ref = None
        self._ok = False
        self._nid = None
        self._err = ""

    # ---- public API -------------------------------------------------------
    def start(self) -> bool:
        if self._thread is not None:
            return self._ok
        self._thread = threading.Thread(target=self._run, daemon=True, name="dshtray")
        self._thread.start()
        self._ready.wait(timeout=5.0)
        return self._ok

    def stop(self) -> None:
        if self._thread is None:
            return
        self._ready.wait(timeout=5.0)
        if self._tid:
            ctypes.windll.user32.PostThreadMessageW(self._tid, self.WM_QUIT, 0, 0)
        self._thread.join(timeout=3.0)
        self._thread = None

    def poll(self) -> list[tuple]:
        events: list[tuple] = []
        while True:
            try:
                events.append(self.queue.get_nowait())
            except Exception:
                break
        return events

    # ---- Win32 plumbing (runs on the tray thread) --------------------------
    def _run(self) -> None:
        try:
            self._ok = self._run_impl()
        except Exception as exc:
            self._ok = False
            self._err = repr(exc)
        finally:
            self._ready.set()

    def _run_impl(self) -> bool:
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32

        self._tid = kernel32.GetCurrentThreadId()

        self._hicon = user32.LoadImageW(
            None, self.icon_path, self.IMAGE_ICON, 16, 16,
            self.LR_LOADFROMFILE | self.LR_DEFAULTSIZE)
        if not self._hicon:
            self._hicon = user32.LoadImageW(
                None, self.icon_path, self.IMAGE_ICON, 0, 0,
                self.LR_LOADFROMFILE)
        if not self._hicon:
            self._err = "LoadImageW failed (err=%d)" % kernel32.GetLastError()
            return False

        hinst = kernel32.GetModuleHandleW(None)
        cls_name = "DSHTrayWindow"
        self._proc_ref = _WNDPROC(self._wndproc)
        wc = _WNDCLASSW()
        wc.lpfnWndProc = self._proc_ref
        wc.hInstance = hinst
        wc.lpszClassName = cls_name
        self._wc_ref = wc
        if not user32.RegisterClassW(ctypes.byref(wc)):
            # Class already registered (a previous instance) is fine.
            if kernel32.GetLastError() != 1410:  # ERROR_CLASS_ALREADY_EXISTS
                self._err = "RegisterClassW failed (err=%d)" % kernel32.GetLastError()
                return False

        self._hwnd = user32.CreateWindowExW(
            0, cls_name, "DSHTray", 0, 0, 0, 0, 0, self.HWND_MESSAGE, None, hinst, None)
        if not self._hwnd:
            self._err = "CreateWindowExW failed (err=%d)" % kernel32.GetLastError()
            return False

        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
        nid.uCallbackMessage = self.WM_TRAY
        nid.hIcon = self._hicon or None
        nid.szTip = self.tooltip
        if not shell32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(nid)):
            self._err = "Shell_NotifyIconW(NIM_ADD) failed (err=%d)" % kernel32.GetLastError()
            return False
        self._nid = nid
        self._ok = True
        self._ready.set()

        msg = _MSG()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        try:
            shell32.Shell_NotifyIconW(self.NIM_DELETE, ctypes.byref(self._nid))
        except Exception:
            pass
        if self._hicon:
            user32.DestroyIcon(self._hicon)
            self._hicon = None
        return True

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == self.WM_TRAY:
            if lparam in (self.WM_LBUTTONDBLCLK, self.WM_LBUTTONUP):
                self.queue.put(("activate",))
            elif lparam == self.WM_RBUTTONUP:
                self._show_menu()
            return 0
        if msg == self.WM_DESTROY:
            ctypes.windll.user32.PostQuitMessage(0)
            return 0
        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self) -> None:
        user32 = ctypes.windll.user32
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            for cid, label, sep in self.menu_items:
                flags = self.MF_SEPARATOR if sep else self.MF_STRING
                if sep:
                    user32.AppendMenuW(menu, flags, 0, None)
                else:
                    user32.AppendMenuW(menu, flags, cid, label)
            pt = _POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            user32.SetForegroundWindow(self._hwnd)
            cmd = user32.TrackPopupMenu(
                menu, self.TPM_RETURNCMD | self.TPM_NONOTIFY | self.TPM_RIGHTBUTTON,
                pt.x, pt.y, 0, self._hwnd, None)
            if cmd:
                self.queue.put(("menu", cmd))
            user32.PostMessageW(self._hwnd, self.WM_NULL, 0, 0)
        finally:
            user32.DestroyMenu(menu)


# --------------------------------------------------------------------------
# tkinter popup
# --------------------------------------------------------------------------
import tkinter as tk

KEY = "#010203"          # transparent colour key (corner rounding)
BG = "#0E1116"
CARD = "#161B24"
BORDER = "#222A36"
TEXT = "#E8ECF3"
SUBTEXT = "#8A94A8"
ACCENT = "#4D6BFE"

GREEN, GREEN_H, GREEN_P = "#18B358", "#21C764", "#139A49"
BLUE, BLUE_H, BLUE_P = "#2F6BFF", "#4180FF", "#275AD6"
RED, RED_H, RED_P = "#E03B41", "#EE4A50", "#C22F35"

W, H = 380, 500

# tray menu ids
M_SHOW, M_START, M_OPEN, M_STOP, M_QUIT = 101, 102, 103, 104, 105


def _rounded_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


class Launcher:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("DSH Launcher")
        self.root.overrideredirect(True)
        self.root.configure(bg=KEY)
        self.root.attributes("-transparentcolor", KEY)
        try:
            self.root.iconbitmap(ICON)
        except tk.TclError:
            pass

        self._drag = (0, 0, 0, 0)
        self._drag_active = False
        self._toast_job: str | None = None
        self._btn_rect: dict[str, int] = {}
        self._minimized = False
        self._tray: _TrayIcon | None = None

        self.c = tk.Canvas(self.root, width=W, height=H, bg=KEY,
                           highlightthickness=0, bd=0)
        self.c.pack()
        self._build()

        # centre on screen
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")

        self._start_tray()
        self._start_poll()
        self.root.after(400, self._poll)          # initial status right away

    # ---- window chrome ----------------------------------------------------
    def _build(self) -> None:
        c = self.c
        c.create_rectangle(0, 0, W, H, fill=KEY, outline="")
        # window body (rounded)
        self.body = _rounded_rect(c, 1, 1, W - 1, H - 1, 22,
                                  fill=BG, outline=BORDER, width=1)

        # ---- title bar ----
        logo = _rounded_rect(c, 20, 16, 54, 50, 10, fill=ACCENT, outline="")
        c.create_text(37, 33, text=">_", fill="#FFFFFF",
                      font=("Consolas", 13, "bold"))
        c.create_text(66, 32, text="DSH Launcher", fill=TEXT,
                      font=("Segoe UI Semibold", 13), anchor="w")
        # minimize button (to tray)
        min_bg = _rounded_rect(c, W - 78, 18, W - 52, 44, 13,
                               fill="#1C232E", outline="")
        c.create_text(W - 65, 31, text="—", fill=SUBTEXT,
                      font=("Segoe UI Symbol", 11), tags=("min", "glyph"))
        c.addtag_withtag("min", min_bg)
        c.tag_bind("min", "<Enter>", lambda e: self._hover_rect(min_bg, "#27303F"))
        c.tag_bind("min", "<Leave>", lambda e: self._hover_rect(min_bg, "#1C232E"))
        c.tag_bind("min", "<ButtonPress-1>", lambda e: self._hover_rect(min_bg, "#10141C"))
        c.tag_bind("min", "<ButtonRelease-1>",
                   lambda e: (self._hover_rect(min_bg, "#1C232E"), self._on_minimize()))
        # close button
        close_bg = _rounded_rect(c, W - 46, 18, W - 20, 44, 13,
                                 fill="#1C232E", outline="")
        c.create_text(W - 33, 31, text="✕", fill=SUBTEXT,
                      font=("Segoe UI Symbol", 11), tags=("close", "glyph"))
        c.addtag_withtag("close", close_bg)
        c.tag_bind("close", "<Enter>", lambda e: self._hover_rect(close_bg, "#27303F"))
        c.tag_bind("close", "<Leave>", lambda e: self._hover_rect(close_bg, "#1C232E"))
        c.tag_bind("close", "<ButtonPress-1>", lambda e: self._hover_rect(close_bg, "#10141C"))
        c.tag_bind("close", "<ButtonRelease-1>",
                   lambda e: (self._hover_rect(close_bg, "#1C232E"), self._quit()))
        # gradient accent line under the title bar (ACCENT fading into BG)
        ax = [int(ACCENT[i:i + 2], 16) for i in (1, 3, 5)]
        bx = [int(BG[i:i + 2], 16) for i in (1, 3, 5)]
        x0, x1, y = 26, W - 26, 60
        for i in range(x1 - x0):
            t = i / (x1 - x0)
            rgb = tuple(int(ax[k] + (bx[k] - ax[k]) * t) for k in range(3))
            c.create_line(x0 + i, y, x0 + i, y + 2, fill="#%02x%02x%02x" % rgb)

        # ---- status capsule ----
        _rounded_rect(c, 20, 82, W - 20, 120, 19, fill=CARD, outline=BORDER)
        self.dot = c.create_oval(40, 97, 48, 105, fill="#6B7280", outline="")
        self.state_text = c.create_text(58, 101, text="已停止", fill=TEXT,
                                        font=("Segoe UI", 11, "bold"), anchor="w")
        self.addr_text = c.create_text(W - 32, 101, text=f"127.0.0.1:{WEB_PORT}",
                                       fill=SUBTEXT, font=("Consolas", 9), anchor="e")

        # ---- three buttons ----
        self._button("start", 136, "▶", "启动", GREEN, GREEN_H, GREEN_P,
                     self._on_start)
        self._button("open", 200, "↗", "打开", BLUE, BLUE_H, BLUE_P,
                     self._on_open)
        self._button("stop", 264, "■", "关闭", RED, RED_H, RED_P,
                     self._on_stop)

        # ---- toast (hidden) ----
        self.toast_pill = _rounded_rect(c, 64, 344, W - 64, 378, 17,
                                        fill="#1C232E", outline=BORDER,
                                        state="hidden")
        self.toast_text = c.create_text(W / 2, 361, text="", fill=TEXT,
                                        font=("Segoe UI", 10), state="hidden")

        # ---- footer ----
        c.create_line(20, 412, W - 20, 412, fill="#1A212C")
        self.exit_tag = c.create_text(34, 434, text="退出", fill=SUBTEXT,
                                      font=("Segoe UI", 9), tags=("exit",))
        c.create_text(W - 34, 434, text=f"v{VERSION} · DeepSeek Harness",
                      fill="#566173", font=("Segoe UI", 9), anchor="e")
        c.tag_bind("exit", "<ButtonPress-1>", lambda e: self._hover_rect(self.exit_tag, "#C7CFDD"))
        c.tag_bind("exit", "<ButtonRelease-1>",
                   lambda e: (self._hover_rect(self.exit_tag, SUBTEXT), self._quit()))
        c.tag_bind("exit", "<Enter>", lambda e: self._hover_rect(self.exit_tag, "#C7CFDD"))
        c.tag_bind("exit", "<Leave>", lambda e: self._hover_rect(self.exit_tag, SUBTEXT))

        # ---- drag (title bar only) ----
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._motion)

    def _button(self, tag, y, glyph, label, bg, hbg, pbg, cmd) -> None:
        c = self.c
        x1, y1, x2, y2 = 20, y, W - 20, y + 56
        rect = _rounded_rect(c, x1, y1, x2, y2, 16, fill=bg, outline="")
        self._btn_rect[tag] = rect
        c.create_text(x1 + 26, (y1 + y2) / 2, text=glyph, fill="#FFFFFF",
                      font=("Segoe UI Symbol", 15), tags=(tag, "glyph"))
        c.create_text(W / 2 + 14, (y1 + y2) / 2, text=label, fill="#FFFFFF",
                      font=("Segoe UI Semibold", 13), tags=(tag, "label"))
        c.addtag_withtag(tag, rect)
        c.tag_bind(tag, "<Enter>", lambda e, t=tag, h=hbg: self._hover_btn(t, h))
        c.tag_bind(tag, "<Leave>", lambda e, t=tag, b=bg: self._hover_btn(t, b))
        c.tag_bind(tag, "<ButtonPress-1>", lambda e, t=tag, p=pbg: self._hover_btn(t, p))
        c.tag_bind(tag, "<ButtonRelease-1>", lambda e, t=tag, b=bg, fn=cmd: self._release(t, b, fn))

    # ---- event helpers ----------------------------------------------------
    def _hover_rect(self, item_id, fill) -> None:
        self.c.itemconfig(item_id, fill=fill)

    def _hover_btn(self, tag, fill) -> None:
        self.c.itemconfig(self._btn_rect[tag], fill=fill)

    def _release(self, tag, bg, fn) -> None:
        self._hover_btn(tag, bg)
        if tag in self.c.gettags("current"):
            fn()

    def _press(self, ev) -> None:
        self._drag = (ev.x_root, ev.y_root, self.root.winfo_x(), self.root.winfo_y())
        tags = self.c.gettags("current")
        self._drag_active = ev.y < 62 and not any(
            t.startswith(("start", "open", "stop", "close", "exit", "min")) for t in tags)

    def _motion(self, ev) -> None:
        if self._drag_active:
            dx = ev.x_root - self._drag[0]
            dy = ev.y_root - self._drag[1]
            self.root.geometry(f"+{self._drag[2] + dx}+{self._drag[3] + dy}")

    # ---- tray --------------------------------------------------------------
    def _start_tray(self) -> None:
        items = [
            (M_SHOW, "显示 / 隐藏窗口", False),
            (0, "", True),
            (M_START, "启动后端", False),
            (M_OPEN, "打开网页", False),
            (M_STOP, "关闭后端", False),
            (0, "", True),
            (M_QUIT, "退出", False),
        ]
        try:
            self._tray = _TrayIcon(ICON, "DSH Launcher", items)
            self._tray.start()
        except Exception:
            self._tray = None
        self.root.after(200, self._poll_tray)

    def _poll_tray(self) -> None:
        if self._tray is not None:
            for ev in self._tray.poll():
                if ev[0] == "activate":
                    self._restore()
                elif ev[0] == "menu":
                    self._on_tray_menu(ev[1])
        self.root.after(200, self._poll_tray)

    def _on_tray_menu(self, cid: int) -> None:
        if cid == M_SHOW:
            if self._minimized:
                self._restore()
            else:
                self._minimize()
        elif cid == M_START:
            self._on_start()
        elif cid == M_OPEN:
            self._on_open()
        elif cid == M_STOP:
            self._on_stop()
        elif cid == M_QUIT:
            self._quit()

    def _on_minimize(self) -> None:
        self._minimize()

    def _minimize(self) -> None:
        self._minimized = True
        self.root.withdraw()
        self._toast("已最小化到系统托盘")   # queued; shows on restore

    def _restore(self) -> None:
        self._minimized = False
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass
        self._foreground()
        self._toast("已恢复")

    def _foreground(self) -> None:
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetAncestor(self.root.winfo_id(), 2)  # GA_ROOT
            if hwnd:
                user32.ShowWindow(hwnd, 9)
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _quit(self) -> None:
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
            self._tray = None
        self.root.destroy()

    # ---- actions ----------------------------------------------------------
    def _on_start(self) -> None:
        if is_running():
            self._toast("已在运行")
            return
        pid = start_server()
        if pid is None:
            self._toast("启动失败, 见 data/web.log")
        else:
            self._toast(f"已启动 (PID {pid})")
        self._poll(True)

    def _on_open(self) -> None:
        if _chrome_path() is None:
            self._toast("未找到 Chrome")
            return
        if open_ui():
            self._toast("已在浏览器打开")
        else:
            self._toast("打开失败")
        self._poll(True)

    def _on_stop(self) -> None:
        n = stop_server()
        self._toast("已终止" if n else "未在运行")
        self._poll(True)

    # ---- status / toast / poll --------------------------------------------
    def _toast(self, msg: str) -> None:
        self.c.itemconfig(self.toast_text, text=msg)
        self.c.itemconfig(self.toast_pill, state="normal")
        self.c.itemconfig(self.toast_text, state="normal")
        if self._toast_job:
            self.root.after_cancel(self._toast_job)
        self._toast_job = self.root.after(2600, self._hide_toast)

    def _hide_toast(self) -> None:
        self.c.itemconfig(self.toast_pill, state="hidden")
        self.c.itemconfig(self.toast_text, state="hidden")
        self._toast_job = None

    def _start_poll(self) -> None:
        self.root.after(1500, self._poll)

    def _poll(self, force=False) -> None:
        try:
            running = is_running()
        except Exception:
            running = False
        if running:
            self.c.itemconfig(self.dot, fill=GREEN)
            self.c.itemconfig(self.state_text, text="运行中", fill=TEXT)
        else:
            self.c.itemconfig(self.dot, fill="#6B7280")
            self.c.itemconfig(self.state_text, text="已停止", fill=SUBTEXT)
        self._start_poll()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    if not _claim_singleton():
        _focus_existing_window()
        sys.exit(0)
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        Launcher().run()
    except Exception:
        with open(ERROR_FILE, "a", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        raise


def _selftest() -> int:
    """Headless diagnostic for the packaged exe: report frozen paths and run
    one real start/stop cycle. Results go to data/selftest.txt (a windowed
    exe has no usable stdout)."""
    import json
    import shutil
    import time as _time
    rep = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "launcher_dir": LAUNCHER_DIR,
        "repo_dir": REPO_DIR,
        "data_dir": DATA_DIR,
        "node": NODE,
        "node_exists": os.path.exists(NODE) or shutil.which(NODE) is not None,
        "icon_found": os.path.exists(ICON),
        "chrome_found": _chrome_path() is not None,
        "repo_bin_found": os.path.exists(os.path.join(REPO_DIR, "apps", "cli", "src", "bin.ts")),
        "was_running": is_running(),
    }
    if not rep["was_running"]:
        pid = start_server()
        rep["started_pid"] = pid
        rep["became_running"] = _wait_ready(30)
        rep["stopped_killed"] = stop_server()
        _time.sleep(0.6)
        rep["running_after_stop"] = is_running()
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "selftest.txt"), "w", encoding="utf-8") as f:
        f.write(json.dumps(rep, indent=2))
    return 0 if rep.get("running_after_stop") is not True else 1


def _selftest_tray() -> int:
    """Headless tray smoke test: create the tray icon, pump for a moment, stop."""
    import json
    import time as _time
    rep: dict = {"tray_ok": False}
    icon: _TrayIcon | None = None
    try:
        icon = _TrayIcon(ICON, "DSH Launcher selftest",
                         [(M_SHOW, "显示 / 隐藏窗口", False), (M_QUIT, "退出", False)])
        rep["tray_started"] = icon.start()
        _time.sleep(0.8)
        rep["tray_alive"] = icon._thread is not None and icon._thread.is_alive()
        icon.stop()
        _time.sleep(0.2)
        rep["tray_stopped"] = icon._thread is None or not icon._thread.is_alive()
        rep["tray_ok"] = bool(rep.get("tray_started") and rep.get("tray_stopped"))
    except Exception as exc:
        rep["error"] = repr(exc)
    finally:
        if icon is not None:
            rep["tray_err"] = icon._err
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "selftest-tray.txt"), "w", encoding="utf-8") as f:
        f.write(json.dumps(rep, indent=2))
    return 0 if rep.get("tray_ok") else 1


if __name__ == "__main__":
    if "--selftest-tray" in sys.argv:
        sys.exit(_selftest_tray())
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
