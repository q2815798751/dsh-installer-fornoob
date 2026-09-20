#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH — frameless dark panel for the DeepSeek Harness web UI
(dsh web, http://127.0.0.1:3080).

Zero external dependencies: stdlib only (tkinter + subprocess + socket +
ctypes for the system-tray icon). Launch with pythonw.exe (no console).
All state lives under ./data/.

The panel is one primary action plus two quiet secondaries. The primary
button follows the state: 启动 when stopped, 正在启动 (with a progress strip)
while the backend comes up, 打开网页 once it is serving.

    primary  -> start the backend, or open the browser if it is already up
    停止     -> taskkill the process tree listening on :3080
    检查更新 -> update_ui.UpdateWindow: versions, changelogs, install, rollback
    最小化   -> hide to the system tray; the harness keeps running

Nothing blocks the tkinter thread: readiness is waited for on a worker and
reported back through root.after, so the window stays draggable throughout.

Window X / 退出 closes only this panel — the harness keeps running until 停止.
"""
from __future__ import annotations

import ctypes
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
from ctypes import wintypes

import update_ui

# --------------------------------------------------------------------------
# paths / config
# --------------------------------------------------------------------------
def _launcher_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)    # PyInstaller: next to the exe
    return os.path.dirname(os.path.abspath(__file__))


LAUNCHER_DIR = _launcher_dir()
INSTALL_DIR = os.path.dirname(LAUNCHER_DIR)

# The harness is an npm install under <install>\harness:
#     harness\node_modules\@deepseek-ai\dsh\lib\bin.js
# Installer 1.4 and earlier put a source checkout under <install>\repo and ran
# pnpm install + build on it instead. Both layouts are resolved here so a
# machine installed the old way keeps working, and so the updater can migrate
# it to the npm layout without a reinstall.
NPM_ENTRY = os.path.join("node_modules", "@deepseek-ai", "dsh", "lib", "bin.js")
SOURCE_ENTRY = os.path.join("apps", "cli", "src", "bin.ts")


def _marker(name: str) -> str | None:
    """Read a `launcher/<name>.txt` path override, tolerating a BOM."""
    path = os.path.join(LAUNCHER_DIR, name)
    try:
        with open(path, encoding="utf-8-sig") as f:
            value = f.read().strip()
        return os.path.abspath(value) if value else None
    except OSError:
        return None


def resolve_harness() -> tuple[str, str]:
    """Find the installed harness. Returns (dir, mode).

    mode is "npm" (…\\harness), "source" (…\\repo, installer ≤1.4) or "missing".
    Cheap enough to call before every start, which matters because an update
    can change both the path and the layout underneath a running launcher.
    """
    candidates: list[str] = []
    for marker in ("harness.txt", "repo.txt"):
        found = _marker(marker)
        if found and found not in candidates:
            candidates.append(found)
    for name in ("harness", "repo"):
        default = os.path.join(INSTALL_DIR, name)
        if default not in candidates:
            candidates.append(default)
    for d in candidates:
        if os.path.exists(os.path.join(d, NPM_ENTRY)):
            return d, "npm"
    for d in candidates:
        if os.path.exists(os.path.join(d, SOURCE_ENTRY)):
            return d, "source"
    return (candidates[0] if candidates else INSTALL_DIR), "missing"


HARNESS_DIR, HARNESS_MODE = resolve_harness()


def refresh_harness() -> tuple[str, str]:
    """Re-resolve after an update: both the path and the layout can change."""
    global HARNESS_DIR, HARNESS_MODE
    HARNESS_DIR, HARNESS_MODE = resolve_harness()
    return HARNESS_DIR, HARNESS_MODE


DATA_DIR = os.path.join(LAUNCHER_DIR, "data")
PID_FILE = os.path.join(DATA_DIR, "pid.txt")
LOG_FILE = os.path.join(DATA_DIR, "web.log")
ERROR_FILE = os.path.join(DATA_DIR, "error.log")
if getattr(sys, "frozen", False):
    _res_dir = getattr(sys, "_MEIPASS", LAUNCHER_DIR)
    ICON = os.path.join(_res_dir, "icon.ico")     # bundled inside the exe
    LOGO = os.path.join(_res_dir, "logo.png")     # whale mark for the panel header
else:
    ICON = os.path.join(LAUNCHER_DIR, "icon.ico")
    LOGO = os.path.join(LAUNCHER_DIR, "logo.png")


def _resolve_node() -> str:
    """Prefer a bundled portable Node runtime next to the installation, then
    fall back to whatever `node` is on PATH. Keeps the launcher self-contained
    on machines where Node is not installed globally."""
    for p in (
        os.path.join(LAUNCHER_DIR, "runtime", "node.exe"),
        os.path.join(INSTALL_DIR, "runtime", "node.exe"),
        os.path.join(os.path.dirname(HARNESS_DIR), "runtime", "node.exe"),
    ):
        if os.path.exists(p):
            return p
    return "node"


NODE = _resolve_node()

# Last-resort browser paths, tried only if the shell cannot open the URL.
# Edge comes first: every supported Windows ships it, so it is the one
# fallback that is actually present on a machine with no other browser.
BROWSER_FALLBACKS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)
# Overridable via DSH_LAUNCHER_PORT so the same launcher can be smoke-tested
# on a free port without disturbing an already-running instance.
WEB_PORT = int(os.environ.get("DSH_LAUNCHER_PORT", "3080"))
WEB_URL = f"http://127.0.0.1:{WEB_PORT}"
VERSION = "1.5.2"
# Upstream's BRAND_GUIDELINES.zh.md asks third-party projects to use the "DSH"
# abbreviation rather than the full DeepSeek Harness trademark, and the web
# client's own manifest uses short_name "DSH". Everything user-visible follows
# that; the exe filename deliberately does not change, because the self-update
# matches on the release asset name DSHLauncher.exe.
DISPLAY_NAME = "DSH"
WINDOW_TITLE = "DSH"
# Titles this panel has used before, so an instance started by an older build
# is still recognised (and can be focused or replaced) after an upgrade.
LEGACY_WINDOW_TITLES = ("DSH Launcher",)
# Generous: the npm layout is up in ~2s, but a source-layout install runs the
# CLI through tsx, which compiles on the way up.
START_TIMEOUT = 120.0
SINGLETON_PORT = 3099
_singleton: socket.socket | None = None


# `dsh web` prints its ready line with a per-run auth token; without the token
# the UI answers 401, so this is the URL the "打开" button must use.
WEB_URL_RE = re.compile(r"dsh web:\s*(http://127\.0\.0\.1:\d+/\?token=[\w.\-]+)")
# Byte offset in web.log where the current server's output begins, so a URL
# from a previous run is never mistaken for this one's.
_log_offset = 0
_LOG_MARKER_TS = 0.0


def _start_cmd() -> list[str]:
    # --no-open keeps browser handoff ours: `dsh web` would otherwise open the
    # default browser itself on every start, which would fight with the 启动 /
    # 打开按钮 split and hand the user a second tab for the 打开 click.
    if HARNESS_MODE == "source":
        # installer ≤1.4: a checkout run through tsx, which needs cwd=repo.
        cmd = [NODE, "--import", "tsx/esm", SOURCE_ENTRY, "web", "--no-open"]
    else:
        # npm layout: the published package ships already-built JS, so there is
        # nothing to transpile and no cwd requirement.
        cmd = [NODE, os.path.join(HARNESS_DIR, NPM_ENTRY), "web", "--no-open"]
    if WEB_PORT != 3080:
        cmd += ["--port", str(WEB_PORT)]
    return cmd


def _start_cwd() -> str:
    return HARNESS_DIR if os.path.isdir(HARNESS_DIR) else INSTALL_DIR


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


def _release_singleton() -> None:
    global _singleton
    if _singleton is not None:
        try:
            _singleton.close()
        except OSError:
            pass
        _singleton = None


def _find_panel_window() -> tuple[int, str]:
    """(hwnd, title) of a running panel — this build's, or an older one's.

    Matching the legacy titles matters: the panel is renamed to DSH in 1.5.2,
    and someone upgrading still has the old build running. Without this, the
    new exe would find no window, exit, and appear to do nothing at all.
    """
    try:
        user32 = ctypes.windll.user32
        for title in (WINDOW_TITLE,) + LEGACY_WINDOW_TITLES:
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                return hwnd, title
    except Exception:
        pass
    return 0, ""


def _focus_window(hwnd: int) -> None:
    """Bring an existing panel to the foreground (second shortcut click)."""
    try:
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)              # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _ask(prompt: str) -> bool:
    """Yes/no via a native dialog. There is no Tk root up yet to parent it."""
    MB_YESNO, MB_ICONQUESTION, MB_TOPMOST = 0x4, 0x20, 0x40000
    try:
        answer = ctypes.windll.user32.MessageBoxW(
            None, prompt, DISPLAY_NAME, MB_YESNO | MB_ICONQUESTION | MB_TOPMOST)
        return answer == 6                      # IDYES
    except Exception:
        return False


def _kill_singleton_holder() -> None:
    for pid in _pids_on_port(SINGLETON_PORT):
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, creationflags=0x08000000)
        except Exception:
            pass
    time.sleep(1.0)


# --------------------------------------------------------------------------
# core logic (no tkinter) — also importable for headless testing
# --------------------------------------------------------------------------
def is_running(port: int | None = None) -> bool:
    """True if something is listening on the dsh web port.

    `port=None` resolves to WEB_PORT at call time, not at import time — a
    default argument would freeze whichever port was configured when this
    module was imported, and every caller here means "the current one".
    """
    if port is None:
        port = WEB_PORT
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
    global _log_offset
    if is_running():
        return None
    refresh_harness()          # an update may have moved it since we started
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        _log_offset = os.path.getsize(LOG_FILE)
    except OSError:
        _log_offset = 0
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        log = open(LOG_FILE, "ab", buffering=0)
    except OSError:
        log = None
    try:
        proc = subprocess.Popen(
            _start_cmd(), cwd=_start_cwd(), stdout=log, stderr=log,
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
    end = time.time() + timeout
    while time.time() < end:
        if is_running():
            return True
        time.sleep(0.4)
    return is_running()


def _authenticated_url(timeout: float = 25.0) -> str:
    """The tokenized URL `dsh web` announces once it is ready.

    The auth token is minted per run, so the server's own startup line is the
    only reliable source — and we already capture that line into web.log.
    Reading starts at the offset the current run began at, so a token from an
    earlier run can never be handed to the browser. Falls back to the bare URL
    when the line never appears: a 401 the user can retry beats opening
    nothing at all.
    """
    end = time.time() + timeout
    while time.time() < end:
        found = _try_authenticated_url()
        if found:
            return found
        time.sleep(0.4)
    return WEB_URL


def _try_authenticated_url() -> str:
    """One immediate look for this run's tokenized URL. "" if not up yet.

    The non-blocking half of _authenticated_url, so the panel can poll for
    readiness from the event loop instead of parking a thread on it.
    """
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            f.seek(_log_offset)
            found = WEB_URL_RE.findall(f.read())
        if found:
            return found[-1]
    except OSError:
        pass
    return ""


def _fallback_browser() -> str | None:
    """First browser that exists by path, used only if the shell cannot open."""
    for p in BROWSER_FALLBACKS:
        if os.path.exists(p):
            return p
    return None


def _open_url(url: str) -> bool:
    """Open a URL in whatever browser Windows has registered for http(s).

    `os.startfile` routes through ShellExecute, so it honours the user's
    default browser, their per-user choice, and the existing window's tab
    reuse — none of which a hardcoded path does. `webbrowser.open` is the
    stdlib backup; the by-path fallback exists only for the rare shell where
    both refuse.
    """
    try:
        os.startfile(url)                                   # noqa: S606 — Windows-only
        return True
    except OSError:
        pass
    try:
        import webbrowser
        if webbrowser.open(url):
            return True
    except Exception:
        pass
    fallback = _fallback_browser()
    if fallback is None:
        return False
    try:
        subprocess.Popen([fallback, url], creationflags=0x08000000)
        return True
    except Exception:
        return False


def open_ui() -> bool:
    """Open the harness UI in the default browser, starting the server first."""
    if not is_running():
        start_server()
        _wait_ready(10.0)
    return _open_url(_authenticated_url())


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
        self.queue: "queue.Queue[tuple]" = queue.Queue()
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

# One primary action and one row of quiet secondaries, instead of four
# equally-loud coloured blocks: 启动/打开 were competing with 关闭 for
# attention even though only one of them is what people open this for.
PRIMARY, PRIMARY_H, PRIMARY_P = "#4D6BFE", "#5B7BFF", "#3D57D6"
GHOST, GHOST_H, GHOST_P = "#1A2230", "#232E40", "#131A25"
GHOST_TEXT, GHOST_TEXT_H = "#C3CCDC", "#FFFFFF"
DANGER, DANGER_TEXT = "#E03B41", "#FF8A8F"
TRACK = "#1B2432"
OK_GREEN = "#18B358"

W, H = 400, 282

# tray menu ids
M_SHOW, M_START, M_OPEN, M_STOP, M_QUIT = 101, 102, 103, 104, 105


def _rr_points(x1, y1, x2, y2, r):
    """Vertex list for a rounded rectangle. Split out from _rounded_rect so
    the progress bar can re-shape an existing polygon in place."""
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


def _rounded_rect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    return c.create_polygon(_rr_points(x1, y1, x2, y2, r), smooth=True, **kw)


class Launcher:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
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
        self._btn_glyph: dict[str, int] = {}
        self._btn_label: dict[str, int] = {}
        self._btn_style: dict[str, tuple] = {}
        self._logo_img = None
        self._minimized = False
        self._tray: _TrayIcon | None = None
        # "stopped" | "starting" | "running" | "failed"
        self._state = "stopped"
        self._quitting = False
        self._started_at = 0.0
        self._prog_phase = 0.0
        self._prog_job: str | None = None
        self._poll_job: str | None = None
        self._running_probe: threading.Thread | None = None
        # Callbacks handed over by worker threads, run by the main loop.
        self._ui_queue: "queue.Queue" = queue.Queue()
        self._open_after_start = False
        # True while the updater owns the installation; the action buttons stay
        # visible but inert, and ✕ refuses to kill the process out from under a
        # half-applied update. Starting the backend is a *separate* busy flag:
        # it must not block ✕.
        self._updating = False
        self._starting = False
        self._update_win: update_ui.UpdateWindow | None = None

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
        self.root.after(100, self._poll_ui)       # worker -> main-thread callbacks
        self.root.after(400, self._poll)          # initial status right away

    # ---- window chrome ----------------------------------------------------
    def _build(self) -> None:
        c = self.c
        c.create_rectangle(0, 0, W, H, fill=KEY, outline="")
        self.body = _rounded_rect(c, 1, 1, W - 1, H - 1, 20,
                                  fill=BG, outline=BORDER, width=1)

        # ---- title bar ----
        # The official whale mark ships as a PNG next to the exe; Tk 8.6 reads
        # PNG natively, so this needs no image library at runtime.
        try:
            self._logo_img = tk.PhotoImage(file=LOGO)
            c.create_image(24, 13, image=self._logo_img, anchor="nw")
        except (tk.TclError, OSError):
            self._logo_img = None
            _rounded_rect(c, 24, 13, 56, 45, 9, fill=ACCENT, outline="")
        c.create_text(62, 22, text=DISPLAY_NAME, fill=TEXT,
                      font=("Segoe UI Semibold", 15), anchor="w")
        c.create_text(62, 40, text="DeepSeek Harness", fill="#5F6A7D",
                      font=("Segoe UI", 8), anchor="w")

        self._chromebutton("min", W - 78, 12, "—", self._on_minimize)
        self._chromebutton("close", W - 46, 12, "✕", self._quit)

        # accent hairline under the title bar, fading into the background
        ax = [int(ACCENT[i:i + 2], 16) for i in (1, 3, 5)]
        bx = [int(BG[i:i + 2], 16) for i in (1, 3, 5)]
        x0, x1, y = 20, W - 20, 50
        for i in range(x1 - x0):
            t = i / (x1 - x0)
            c.create_line(x0 + i, y, x0 + i, y + 1,
                          fill="#%02x%02x%02x" % tuple(
                              int(ax[k] + (bx[k] - ax[k]) * t) for k in range(3)))

        # ---- status row ----
        self.dot = c.create_oval(24, 70, 32, 78, fill="#5A6478", outline="")
        self.state_text = c.create_text(42, 74, text="已停止", fill=SUBTEXT,
                                        font=("Segoe UI", 10, "bold"), anchor="w")
        self.addr_text = c.create_text(W - 20, 74, text=f"127.0.0.1:{WEB_PORT}",
                                       fill="#48525F", font=("Consolas", 8),
                                       anchor="e")

        # ---- one primary action, two quiet secondaries ----
        self._button("primary", 20, 90, W - 20, 142, "▶", "启动",
                     PRIMARY, PRIMARY_H, PRIMARY_P, "#FFFFFF", "#FFFFFF",
                     self._on_primary)
        half = (W - 20 - 20 - 8) // 2
        self._button("stop", 20, 150, 20 + half, 186, "■", "停止",
                     GHOST, GHOST_H, GHOST_P, GHOST_TEXT, DANGER_TEXT,
                     self._on_stop)
        self._button("update", 20 + half + 8, 150, W - 20, 186, "↻", "检查更新",
                     GHOST, GHOST_H, GHOST_P, GHOST_TEXT, GHOST_TEXT_H,
                     self._on_update)

        # ---- progress strip (drawn only while starting) ----
        self._prog_track = _rounded_rect(c, 20, 198, W - 20, 220, 11,
                                         fill=TRACK, outline="", state="hidden")
        self._prog_fill = _rounded_rect(c, 20, 198, 120, 220, 11,
                                        fill=ACCENT, outline="", state="hidden")

        # ---- toast (hidden until something happens) ----
        self.toast_pill = _rounded_rect(c, 20, 196, W - 20, 224, 14,
                                        fill="#1B212C", outline=BORDER,
                                        state="hidden")
        self.toast_text = c.create_text(W / 2, 210, text="", fill=TEXT,
                                        font=("Segoe UI", 9), state="hidden")

        # ---- footer ----
        c.create_line(20, 246, W - 20, 246, fill="#1A212C")
        self.exit_tag = c.create_text(24, 264, text="退出", fill="#6B7686",
                                      font=("Segoe UI", 8), tags=("exit",), anchor="w")
        c.create_text(W - 20, 264, text=f"v{VERSION} · {DISPLAY_NAME}",
                      fill="#3F4854", font=("Segoe UI", 8), anchor="e")
        for ev, fill in (("<Enter>", "#C7CFDD"), ("<Leave>", "#6B7686"),
                         ("<ButtonPress-1>", "#C7CFDD")):
            c.tag_bind("exit", ev, lambda e, f=fill: self._hover_rect(self.exit_tag, f))
        c.tag_bind("exit", "<ButtonRelease-1>",
                   lambda e: (self._hover_rect(self.exit_tag, "#6B7686"), self._quit()))

        # ---- drag (title bar only) ----
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._motion)

        self._apply_state()

    def _chromebutton(self, tag, x, y, glyph, cmd) -> None:
        """Minimise / close: 26x26 squares in the title bar."""
        c = self.c
        rect = _rounded_rect(c, x, y, x + 26, y + 26, 13, fill="#171E29", outline="")
        c.create_text(x + 13, y + 13, text=glyph, fill="#6B7686",
                      font=("Segoe UI Symbol", 10), tags=(tag, "glyph"))
        c.addtag_withtag(tag, rect)
        for ev, fill in (("<Enter>", "#212B3A"), ("<Leave>", "#171E29")):
            c.tag_bind(tag, ev, lambda e, r=rect, f=fill: self._hover_rect(r, f))
        c.tag_bind(tag, "<ButtonPress-1>",
                   lambda e, r=rect: self._hover_rect(r, "#101722"))
        c.tag_bind(tag, "<ButtonRelease-1>",
                   lambda e, r=rect: (self._hover_rect(r, "#171E29"), cmd()))

    def _button(self, tag, x1, y1, x2, y2, glyph, label,
                fill, hover, press, text, text_hover, cmd) -> None:
        c = self.c
        rect = _rounded_rect(c, x1, y1, x2, y2, 14, fill=fill, outline="")
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        self._btn_rect[tag] = rect
        self._btn_glyph[tag] = c.create_text(
            cx - 34, cy, text=glyph, fill=text,
            font=("Segoe UI Symbol", 13), tags=(tag, "glyph"), anchor="e")
        self._btn_label[tag] = c.create_text(
            cx - 20, cy, text=label, fill=text,
            font=("Segoe UI Semibold", 12), tags=(tag, "label"), anchor="w")
        self._btn_style[tag] = (fill, hover, press, text, text_hover)
        c.addtag_withtag(tag, rect)
        c.tag_bind(tag, "<Enter>", lambda e, t=tag: self._paint_btn(t, "hover"))
        c.tag_bind(tag, "<Leave>", lambda e, t=tag: self._paint_btn(t, "normal"))
        c.tag_bind(tag, "<ButtonPress-1>", lambda e, t=tag: self._paint_btn(t, "press"))
        c.tag_bind(tag, "<ButtonRelease-1>",
                   lambda e, t=tag, fn=cmd: self._release(t, fn))

    def _paint_btn(self, tag: str, mode: str) -> None:
        """mode: normal | hover | press | disabled."""
        fill, hover, press, text, text_hover = self._btn_style[tag]
        if mode == "disabled":
            self.c.itemconfig(self._btn_rect[tag], fill="#161D28")
            colour = "#4A5462"
        else:
            self.c.itemconfig(self._btn_rect[tag],
                              fill={"normal": fill, "hover": hover, "press": press}[mode])
            colour = text_hover if mode in ("hover", "press") else text
        self.c.itemconfig(self._btn_glyph[tag], fill=colour)
        self.c.itemconfig(self._btn_label[tag], fill=colour)

    def _set_btn(self, tag: str, glyph: str, label: str) -> None:
        self.c.itemconfig(self._btn_glyph[tag], text=glyph)
        self.c.itemconfig(self._btn_label[tag], text=label)

    # ---- event helpers ----------------------------------------------------
    def _hover_rect(self, item_id, fill) -> None:
        self.c.itemconfig(item_id, fill=fill)

    def _btn_enabled(self, tag: str) -> bool:
        """Whether a button should respond at all right now."""
        if self._updating:
            return False
        if tag == "primary":
            return self._state != "starting"
        if tag == "stop":
            return self._state == "running"
        return True                              # 检查更新

    def _release(self, tag, fn) -> None:
        if self._btn_enabled(tag):
            self._paint_btn(tag, "hover")
        if tag in self.c.gettags("current") and self._btn_enabled(tag):
            fn()

    def _press(self, ev) -> None:
        self._drag = (ev.x_root, ev.y_root, self.root.winfo_x(), self.root.winfo_y())
        tags = self.c.gettags("current")
        self._drag_active = ev.y < 52 and not any(
            t.startswith(("primary", "stop", "update", "close", "exit", "min"))
            for t in tags)

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
            self._tray = _TrayIcon(ICON, DISPLAY_NAME, items)
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
            if self._state == "running":
                self._toast("已在运行")
            else:
                self._start_flow()
        elif cid == M_OPEN:
            if self._state == "running":
                self._open_browser()
            else:
                self._start_flow()          # will open once it is up
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
        # Starting the backend is explicitly NOT a reason to refuse closing:
        # the backend is its own process and outlives us either way.
        self._quitting = True
        if self._updating:
            # Killing the launcher would kill the updater thread mid-swap and
            # strand a half-replaced tree on disk. The update window offers a
            # clean cancel that rolls back first.
            self._quitting = False
            self._toast("更新进行中，请先在更新窗口取消")
            self._focus_update_window()
            return
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
            self._tray = None
        self.root.destroy()

    # ---- actions ----------------------------------------------------------
    def _on_primary(self) -> None:
        """The one button: start when stopped, open the browser when running."""
        if self._updating:
            self._toast("更新进行中，请稍候")
            return
        if self._state == "running":
            self._open_browser()
        else:
            self._start_flow()

    def _open_browser(self) -> None:
        # The URL is already in web.log from the run that is up, so this needs
        # no waiting — the freezing 35-second _wait_ready dance is gone.
        url = _try_authenticated_url() or WEB_URL
        if _open_url(url):
            self._toast("已在浏览器打开")
        else:
            self._toast("打开失败，请手动访问 %s" % WEB_URL)

    def _start_flow(self, open_when_ready: bool = False) -> None:
        """Start the backend without ever blocking the UI.

        `dsh web` takes a couple of seconds on the npm layout and noticeably
        longer from the source layout, where tsx compiles on the way up. The
        old code returned the instant Popen succeeded, so the panel claimed
        "已启动" while the dot still said 已停止 — and pressing 打开 in that
        window froze the whole window for up to 35 seconds.
        """
        if self._starting:
            return
        if is_running():
            self._set_state("running")
            if open_when_ready:
                self._open_browser()
            return
        self._open_after_start = open_when_ready
        pid = start_server()
        if pid is None:
            self._toast("启动失败, 见 data/web.log")
            self._set_state("failed")
            return
        self._started_at = time.time()
        self._set_state("starting")
        background = threading.Thread(
            target=self._await_ready, args=(pid,), daemon=True, name="dsh-start")
        background.start()

    def _await_ready(self, pid: int) -> None:
        """Worker thread: wait for the port, then for the token line."""
        url = ""
        while time.time() - self._started_at < START_TIMEOUT:
            if self._stop_waiting():
                return
            url = _try_authenticated_url()
            if url:
                break
            if not _pid_alive(pid) and not is_running():
                self._ui(lambda: self._start_failed("后端进程退出了，见 data/web.log"))
                return
            time.sleep(0.4)
        if self._stop_waiting():
            return
        if url:
            self._ui(lambda: self._start_succeeded(url))
        else:
            self._ui(lambda: self._start_failed(
                "等了 %d 秒后端还没就绪，见 data/web.log" % START_TIMEOUT))

    def _stop_waiting(self) -> bool:
        return self._quitting or self._updating

    def _ui(self, fn) -> None:
        """Hand `fn` to the tkinter thread. Workers never touch Tk directly.

        `root.after()` from a non-main thread happens to work under a real
        mainloop() and raises "main thread is not in main loop" whenever the
        loop is driven any other way. A queue drained by the main thread is
        safe either way — and it is the pattern update_ui already uses.
        """
        self._ui_queue.put(fn)

    def _poll_ui(self) -> None:
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_ui)

    def _start_succeeded(self, url: str) -> None:
        self._set_state("running")
        self._toast("已启动，用时 %.0f 秒" % (time.time() - self._started_at))
        if self._open_after_start:
            self._open_after_start = False
            self._open_browser()

    def _start_failed(self, msg: str) -> None:
        self._set_state("failed")
        self._toast(msg)

    def _on_stop(self) -> None:
        if self._updating:
            self._toast("更新进行中，请稍候")
            return
        if self._state == "starting":
            self._toast("正在启动，稍后再试")
            return
        n = stop_server()
        self._toast("已停止" if n else "未在运行")
        self._set_state("stopped")
        self._poll(True)

    def _on_update(self) -> None:
        if self._update_win is not None and self._focus_update_window():
            return
        host = update_ui.Host(
            root=self.root,
            icon=ICON,
            install_dir=INSTALL_DIR,
            launcher_dir=LAUNCHER_DIR,
            # Self-update only makes sense for a real installed exe; a dev run
            # of the .pyw has no exe to replace.
            exe_path=sys.executable if getattr(sys, "frozen", False) else "",
            launcher_version=VERSION,
            resolve_harness=refresh_harness,
            stop_backend=stop_server,
            start_backend=start_server,
            wait_ready=_wait_ready,
            authenticated_url=_authenticated_url,
            backend_running=is_running,
            open_url=_open_url,
            set_busy=self._set_updating,
            on_close=self._on_update_closed,
            restart_launcher=self._restart_launcher,
        )
        try:
            self._update_win = update_ui.UpdateWindow(host)
        except Exception:
            self._update_win = None
            try:
                os.makedirs(DATA_DIR, exist_ok=True)
                with open(ERROR_FILE, "a", encoding="utf-8") as f:
                    f.write(traceback.format_exc())
            except OSError:
                pass
            self._toast("打开更新窗口失败，见 data/error.log")

    def _focus_update_window(self) -> bool:
        """Raise the update window if it is still alive. Returns False when it
        has been destroyed, so the caller can open a fresh one."""
        if self._update_win is None:
            return False
        try:
            self._update_win.win.deiconify()
            self._update_win.win.lift()
            self._update_win.win.focus_force()
            return True
        except tk.TclError:
            self._update_win = None
            return False

    def _on_update_closed(self) -> None:
        self._update_win = None
        refresh_harness()         # an update may have installed a new layout
        self._poll(True)          # the update may have started/stopped the backend

    def _restart_launcher(self) -> None:
        """Relaunch the just-replaced exe and exit.

        Release the single-instance socket *before* spawning, otherwise the new
        process finds the port taken by a launcher that is about to disappear
        and exits immediately.
        """
        exe = sys.executable if getattr(sys, "frozen", False) else ""
        if not exe or not os.path.exists(exe):
            self._toast("请手动重新打开启动器")
            return
        self._release_singleton()
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
            self._tray = None
        try:
            subprocess.Popen([exe], cwd=LAUNCHER_DIR,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            self._toast("重启失败，请手动重新打开启动器")
            return
        self.root.after(400, self.root.destroy)

    def _set_updating(self, busy: bool) -> None:
        """Dim (and disarm) the action buttons while the updater owns the
        install directory."""
        self._updating = busy
        self._apply_state()

    # ---- state ------------------------------------------------------------
    def _set_state(self, state: str) -> None:
        self._state = state
        self._apply_state()

    def _apply_state(self) -> None:
        """Repaint everything that depends on what the backend is doing.

        There are four states now, not two: "starting" is the one the old
        panel lacked, and its absence is why a click on 启动 looked like it
        did nothing for half a minute.
        """
        state = self._state
        if state == "running":
            dot, text, colour = OK_GREEN, "运行中", TEXT
            glyph, label = "↗", "打开网页"
        elif state == "starting":
            dot, text, colour = ACCENT, "正在启动…", TEXT
            glyph, label = "◌", "正在启动"
        elif state == "failed":
            dot, text, colour = DANGER, "启动失败", "#FF8A8F"
            glyph, label = "▶", "重试启动"
        else:
            dot, text, colour = "#5A6478", "已停止", SUBTEXT
            glyph, label = "▶", "启动"

        self.c.itemconfig(self.dot, fill=dot)
        self.c.itemconfig(self.state_text, text=text, fill=colour)
        self._set_btn("primary", glyph, label)
        for tag in ("primary", "stop", "update"):
            self._paint_btn(tag, "normal")
        self._set_progress(state == "starting")

    # ---- progress ---------------------------------------------------------
    def _set_progress(self, active: bool) -> None:
        if active and self._prog_job is None:
            self._prog_phase = 0.0
            self.c.itemconfig(self._prog_track, state="normal")
            self._tick_progress()
        elif not active and self._prog_job is not None:
            self.root.after_cancel(self._prog_job)
            self._prog_job = None
            self.c.itemconfig(self._prog_track, state="hidden")
            self.c.itemconfig(self._prog_fill, state="hidden")

    def _tick_progress(self) -> None:
        """Slide a highlight across the track.

        Deliberately indeterminate: how long `dsh web` takes depends on the
        layout (npm is ~2s, a source checkout compiles through tsx first), so
        a real percentage would be a lie. The status dot breathes on the same
        tick, so a slow start still reads as alive rather than hung.
        """
        self._prog_phase = (self._prog_phase + 0.018) % 1.0
        x0, x1 = 20, W - 20
        span = x1 - x0
        width = int(span * 0.34)
        left = x0 + int((span + width) * self._prog_phase) - width
        vis1, vis2 = max(x0, left), min(x1, left + width)
        if vis2 - vis1 > 8:
            self.c.coords(self._prog_fill, *_rr_points(vis1, 198, vis2, 220, 11))
            self.c.itemconfig(self._prog_fill, state="normal")
        else:
            self.c.itemconfig(self._prog_fill, state="hidden")

        # breathing dot + elapsed seconds, updated on the same tick
        level = int(120 + 135 * abs(((self._prog_phase * 2) % 1.0) - 0.5) * 2)
        self.c.itemconfig(self.dot, fill="#%02x%02x%02x" % (level // 3, level // 2, level))
        self._prog_job = self.root.after(40, self._tick_progress)

    # ---- status / toast / poll --------------------------------------------
    def _toast(self, msg: str) -> None:
        self.c.itemconfig(self.toast_text, text=msg)
        self.c.itemconfig(self.toast_pill, state="normal")
        self.c.itemconfig(self.toast_text, state="normal")
        if self._toast_job:
            self.root.after_cancel(self._toast_job)
        self._toast_job = self.root.after(2800, self._hide_toast)

    def _hide_toast(self) -> None:
        self.c.itemconfig(self.toast_pill, state="hidden")
        self.c.itemconfig(self.toast_text, state="hidden")
        self._toast_job = None

    def _start_poll(self) -> None:
        self.root.after(1500, self._poll)

    def _poll(self, force: bool = False) -> None:
        """Refresh the status dot — without blocking the event loop.

        `is_running()` costs up to 0.35s on a closed port, and it used to run
        on the tkinter thread every 1.5 seconds: a visible micro-stutter.
        """
        if self._state != "starting" and (
                self._running_probe is None or not self._running_probe.is_alive()):
            self._running_probe = threading.Thread(
                target=self._probe_running, daemon=True, name="dsh-poll")
            self._running_probe.start()
        self._start_poll()

    def _probe_running(self) -> None:
        try:
            running = is_running()
        except Exception:
            running = False
        self._ui(lambda: self._on_probe(running))

    def _on_probe(self, running: bool) -> None:
        if self._state == "starting":
            return                    # the start flow owns the state until it ends
        self._set_state("running" if running else "stopped")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    if not _claim_singleton():
        hwnd, title = _find_panel_window()
        if hwnd and title == WINDOW_TITLE:
            _focus_window(hwnd)                 # same build: just raise it
            sys.exit(0)
        # Either an older build still owns the lock — which is exactly what an
        # upgrade looks like, since the running process keeps running from the
        # exe file we just replaced — or nobody is visible at all. Ask, rather
        # than exiting silently and looking broken.
        if hwnd or _pids_on_port(SINGLETON_PORT):
            if not _ask("检测到旧版本的 %s 面板还在运行（可能缩在系统托盘里）。\n\n"
                        "结束它并启动新版本吗？" % DISPLAY_NAME):
                if hwnd:
                    _focus_window(hwnd)
                sys.exit(0)
            _kill_singleton_holder()
            if not _claim_singleton():
                sys.exit(0)
        else:
            sys.exit(0)
    os.makedirs(DATA_DIR, exist_ok=True)
    if getattr(sys, "frozen", False):
        # Left behind by a self-update; the process that owned it has exited by
        # the time the user gets here, so this is just a retry.
        update_ui.updater.cleanup_launcher_backup(sys.executable)
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
        "install_dir": INSTALL_DIR,
        "harness_dir": HARNESS_DIR,
        "harness_mode": HARNESS_MODE,
        "data_dir": DATA_DIR,
        "node": NODE,
        "node_exists": os.path.exists(NODE) or shutil.which(NODE) is not None,
        "icon_found": os.path.exists(ICON),
        "browser_fallback": _fallback_browser(),
        "harness_entry_found": bool(HARNESS_DIR) and os.path.exists(os.path.join(
            HARNESS_DIR, NPM_ENTRY if HARNESS_MODE == "npm" else SOURCE_ENTRY)),
        "was_running": is_running(),
    }
    if not rep["was_running"]:
        pid = start_server()
        rep["started_pid"] = pid
        rep["became_running"] = _wait_ready(30)
        # Exercises the token extraction the 打开 button depends on.
        rep["authenticated_url"] = _authenticated_url(30)
        rep["stopped_killed"] = stop_server()
        _time.sleep(0.6)
        rep["running_after_stop"] = is_running()
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "selftest.txt"), "w", encoding="utf-8") as f:
        f.write(json.dumps(rep, indent=2))
    return 0 if rep.get("running_after_stop") is not True else 1


def _selftest_update() -> int:
    """Headless check of the update path that does not touch the disk: list the
    official releases, classify them, and run the environment checks. Verifies
    that updater.py made it into the frozen exe and that the network route the
    update depends on is actually usable from here."""
    import json
    harness_dir, mode = refresh_harness()
    rep: dict = {"install_dir": INSTALL_DIR, "harness_dir": harness_dir,
                 "mode": mode, "launcher_dir": LAUNCHER_DIR,
                 "launcher_version": VERSION}
    try:
        releases, tags = update_ui.updater.list_versions()
        rep["releases"] = len(releases)
        rep["stable"] = sum(1 for r in releases if r.stable)
        rep["preview"] = len(releases) - rep["stable"]
        rep["newest"] = releases[0].version if releases else None
        rep["dist_tags"] = tags
        rep["installed"] = update_ui.updater.installed_version(harness_dir, mode)
        newest = releases[0] if releases else None
        if newest is not None:
            rep["changelog_chars"] = len(update_ui.updater.changelog_for(newest.version))
            report = update_ui.updater.preflight(
                INSTALL_DIR, harness_dir, mode, release=newest,
                backend_running=is_running())
            rep["checks"] = [{"key": c.key, "status": c.status, "detail": c.detail}
                             for c in report.checks]
            rep["blockers"] = [c.key for c in report.blockers]
            rep["proxy"] = report.proxy
        newer = update_ui.updater.newer_launcher(VERSION)
        rep["launcher_update_available"] = newer.version if newer else None
    except Exception as exc:  # noqa: BLE001
        rep["error"] = repr(exc)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "selftest-update.txt"), "w", encoding="utf-8") as f:
        f.write(json.dumps(rep, indent=2, ensure_ascii=False))
    return 0 if not rep.get("error") and not rep.get("blockers") else 1


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
    if "--selftest-update" in sys.argv:
        sys.exit(_selftest_update())
    if "--selftest-tray" in sys.argv:
        sys.exit(_selftest_tray())
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
