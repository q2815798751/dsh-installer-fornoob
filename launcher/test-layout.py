#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Layout regression check for the two 环境检查 pages.

    python launcher\\test-layout.py

A grid cell can hold exactly one widget. When two land in the same cell Tk says
nothing — it just draws one over the other, and the user sees overlapping text.
That has happened twice now (the installer's preflight rows, then the launcher's
hint rows), both times because the row number was derived from a counter that
had already moved on. This renders both pages offscreen and looks for widgets
that share pixels, so the next one is caught by a test instead of by a user.

Needs a desktop session (tkinter), unlike the other self-checks.
"""
from __future__ import annotations

import os
import queue
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "installer"))

import importlib.util

import update_ui
import updater

# The panel itself, for the update-hint wiring. Same loader as test-security.py:
# launcher.pyw is not importable by name, and exec_module runs no side effects
# because everything real is behind __main__.
_spec = importlib.util.spec_from_file_location("launcher", os.path.join(HERE, "launcher.pyw"))
mod = importlib.util.module_from_spec(_spec)
sys.modules["launcher"] = mod
_spec.loader.exec_module(mod)


def _boxes(widget, base=(0, 0), out=None):
    """(widget, x, y, w, h, parent) for every descendant, in window coordinates."""
    if out is None:
        out = []
    for child in widget.winfo_children():
        try:
            x, y = base[0] + child.winfo_x(), base[1] + child.winfo_y()
            w, h = child.winfo_width(), child.winfo_height()
        except tk.TclError:
            continue
        out.append((child, x, y, w, h, widget))
        _boxes(child, (x, y), out)
    return out


def overlapping_siblings(win):
    """Sibling widgets whose bounding boxes intersect."""
    win.update_idletasks()
    win.update()
    items = [b for b in _boxes(win) if b[3] > 1 and b[4] > 1]
    bad = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a[5] is not b[5]:
                continue                    # only siblings can share a grid cell
            ax, ay, aw, ah = a[1:5]
            bx, by, bw, bh = b[1:5]
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                bad.append((a[0], b[0]))
    return bad


def _fake_host(root, install_dir, *, restart_ok=True, on_restart=None,
               on_launcher_release=None):
    def restart():
        if on_restart is not None:
            on_restart()
        return restart_ok

    return update_ui.Host(
        root=root, icon="", install_dir=install_dir,
        launcher_dir=os.path.join(install_dir, "launcher"),
        exe_path="", launcher_version="test",
        resolve_harness=lambda: (os.path.join(install_dir, "harness"), "npm"),
        stop_backend=lambda: 0, start_backend=lambda: None,
        wait_ready=lambda t: False, authenticated_url=lambda t: "",
        backend_running=lambda: False, open_url=lambda u: True,
        set_busy=lambda b: None, on_close=lambda: None,
        restart_launcher=restart,
        on_launcher_release=on_launcher_release or (lambda r: None))


# Worst case for row layout: a long path as a detail, and hints on several rows
# (a hint takes a row of its own — that is the bug this test exists for).
PANEL_CHECKS = [
    updater.Check("network", "网络连接 (npm 源)", updater.OK, "直连可用 (0.8s)"),
    updater.Check("network_proxy", "系统代理", updater.WARN, "直连失败，已改用系统代理",
                  "代理来自「Internet 选项」，安装时会传给 npm。"),
    updater.Check("disk", "磁盘空间", updater.OK, "剩余 12.4 GB"),
    updater.Check("writable", "安装目录可写", updater.OK,
                  r"C:\Users\Administrator\AppData\Local\DeepSeekHarness"),
    updater.Check("harness", "已安装的 dsh", updater.OK, "v0.1.5-rc.2（npm 布局）"),
    updater.Check("runtime", "便携版 Node.js", updater.FAIL, "缺少 runtime\\node.exe",
                  "先跑一次安装器把运行时装回来，或者点「重新检查」。"),
    updater.Check("ports", "端口占用", updater.WARN, "端口 3080 已被占用",
                  "可能是旧版本的 DSH 还在运行。"),
    updater.Check("backend", "后端当前状态", updater.OK, "正在运行（更新会先停止它）"),
]


def main() -> int:
    import installer
    import preflight

    root = tk.Tk()
    root.withdraw()
    install_dir = os.path.join(os.environ.get("TEMP") or ".", "dsh-layout-test")
    failures = 0

    def report(label: str, bad) -> None:
        nonlocal failures
        failures += len(bad)
        print("%-4s %s（重叠 %d 对）" % ("ok" if not bad else "FAIL", label, len(bad)))
        for a, b in bad[:8]:
            print("       %s 与 %s 共享像素" % (a, b))

    def check(label: str, ok: bool, extra: str = "") -> None:
        nonlocal failures
        if not ok:
            failures += 1
        print("%-4s %s%s" % ("ok" if ok else "FAIL", label,
                             ("  <- " + extra) if extra and not ok else ""))

    win = update_ui.UpdateWindow(_fake_host(root, install_dir))
    win.win.geometry("880x680+10000+10000")     # render far offscreen
    win._show_list()
    report("面板 · 版本列表", overlapping_siblings(win.win))
    win._show_preflight()
    report("面板 · 更新前环境检查（刚打开）", overlapping_siblings(win.win))
    for c in PANEL_CHECKS:
        win._pf_row(c)
    report("面板 · 更新前环境检查（全部行填好）", overlapping_siblings(win.win))

    # ---- a newer panel on offer: the list page must survive being rebuilt ----
    # The banner packs itself above the tabs, and the previous page's tabs frame
    # is destroyed by then, so this used to raise TclError on every rebuild —
    # which is any 返回版本列表 while an update is on offer.
    win.launcher_release = updater.LauncherRelease(
        tag="v9.9.9", version="9.9.9", url="https://example.invalid/n.exe",
        size=12345, published="2026-09-01", body="", digest="")
    for attempt in (1, 2):
        try:
            win._show_list()
            root.update()
            err = ""
        except tk.TclError as exc:
            err = str(exc)
        check("面板 · 带更新横幅重建列表页（第 %d 次）" % attempt, not err, err)
        if not err:
            check("面板 · 横幅在标签页上方",
                  win.banner.winfo_ismapped()
                  and win.banner.winfo_y() < win._tabs_frame.winfo_y(),
                  "banner_y=%s tabs_y=%s" % (win.banner.winfo_y(),
                                             win._tabs_frame.winfo_y()))

    # ---- the two failure wordings must not borrow each other's nouns ----
    def label_texts(widget) -> str:
        out = []
        for child in widget.winfo_children():
            if isinstance(child, tk.Label):
                try:
                    out.append(str(child.cget("text")))
                except tk.TclError:
                    pass
            out.append(label_texts(child))
        return "\n".join(out)

    win._target = "launcher"
    win._finish(False, "启动器更新失败：测试", False, False)
    root.update()
    text = label_texts(win.win)
    check("启动器失败页不提 harness", "harness" not in text, text[:200])
    check("启动器失败页说清楚照常使用", "照常使用" in text, text[:200])

    win._target = "harness"
    win._finish(False, "安装失败：测试", False, False)
    root.update()
    text = label_texts(win.win)
    check("本体失败页仍提 harness.old", "harness.old" in text, text[:200])

    # ---- auto-restart decisions (no timers: drive the hook directly) ----
    calls = []
    win2 = update_ui.UpdateWindow(
        _fake_host(root, install_dir, restart_ok=True,
                   on_restart=lambda: calls.append(1)))
    win2.win.geometry("880x680+10000+10000")
    win2._target = "launcher"
    win2._finish(True, "启动器已更新到 v9.9.9。", False, True)
    root.update()
    check("成功页安排了自动重启", win2._restart_job is not None)
    check("成功页不再要求用户点按钮", "自动重启" in label_texts(win2.win))
    win2._auto_restart()
    check("自动重启调用了一次", len(calls) == 1, str(calls))
    win2._restart()                       # a manual click landing at the same time
    check("重复重启被拦住", len(calls) == 1, str(calls))

    calls2 = []
    win3 = update_ui.UpdateWindow(
        _fake_host(root, install_dir, restart_ok=False,
                   on_restart=lambda: calls2.append(1)))
    win3.win.geometry("880x680+10000+10000")
    win3._target = "launcher"
    win3._finish(True, "启动器已更新到 v9.9.9。", False, True)
    root.update()
    win3._auto_restart()
    root.update()
    check("重启失败后窗口还在", bool(win3.win.winfo_exists()))
    check("重启失败后有说明", bool(win3._restart_note) and
          "立即重启" in str(win3._restart_note.cget("text")),
          str(win3._restart_note.cget("text") if win3._restart_note else ""))
    win3._restart()
    check("失败后手动重试会再试一次", len(calls2) == 2, str(calls2))

    # ---- the panel/tray hints for a new launcher ---------------------------
    panel = mod.Launcher.__new__(mod.Launcher)      # no Tk window, no tray
    canvas = tk.Canvas(root, width=400, height=282)
    panel.c = canvas
    panel.root = root
    panel._ver_text = canvas.create_text(380, 264, text="v0.0.0 · DSH", anchor="e")
    panel._btn_style = {"update": ("a", "b", "c", "d", "e")}
    panel._btn_rect = {"update": canvas.create_rectangle(1, 1, 2, 2)}
    panel._btn_glyph = {"update": canvas.create_text(1, 1, text="")}
    panel._btn_label = {"update": canvas.create_text(1, 1, text="检查更新")}
    panel._base_tray_items = [(mod.M_SHOW, "显示 / 隐藏窗口", False)]
    panel._tray = None
    panel._launcher_release = None

    mod.Launcher._apply_update_hint(panel)
    check("没有新版时按钮保持原样",
          canvas.itemcget(panel._btn_label["update"], "text") == "检查更新",
          canvas.itemcget(panel._btn_label["update"], "text"))
    check("没有新版时页脚显示当前版本",
          "可更新" not in canvas.itemcget(panel._ver_text, "text"))

    panel._launcher_release = updater.LauncherRelease(
        tag="v9.9.9", version="9.9.9", url="https://example.invalid/n.exe",
        size=1, published="2026-09-01", body="", digest="")
    mod.Launcher._apply_update_hint(panel)
    check("有新版时按钮改文案",
          canvas.itemcget(panel._btn_label["update"], "text") == "更新到 v9.9.9",
          canvas.itemcget(panel._btn_label["update"], "text"))
    check("有新版时页脚给出可更新提示",
          "v9.9.9" in canvas.itemcget(panel._ver_text, "text")
          and "可更新" in canvas.itemcget(panel._ver_text, "text"),
          canvas.itemcget(panel._ver_text, "text"))
    # A one-off itemconfig would be undone by _paint_btn on the next hover.
    check("按钮底色进了 _btn_style（hover 不会刷回去）",
          panel._btn_style["update"][0] == mod.PRIMARY, str(panel._btn_style["update"]))

    class FakeTray:
        def __init__(self):
            self.menu_items = []

    panel._tray = FakeTray()
    mod.Launcher._apply_update_hint(panel)
    check("托盘菜单最上面插了更新项",
          panel._tray.menu_items[0][0] == mod.M_UPDATE
          and "v9.9.9" in panel._tray.menu_items[0][1],
          str(panel._tray.menu_items[:2]))
    panel._launcher_release = None
    mod.Launcher._apply_update_hint(panel)
    check("提示可撤销（版本没了就复原）",
          panel._tray.menu_items == panel._base_tray_items
          and canvas.itemcget(panel._btn_label["update"], "text") == "检查更新")

    # The installer's own preflight page, driven by the real checks.
    other = tk.Tk()
    other.withdraw()
    ui = installer.SetupUI.__new__(installer.SetupUI)
    ui.root = other
    ui._frame = None
    ui.res = installer.resources()
    ui.target_var = tk.StringVar(value=install_dir)
    ui._pf_widgets, ui._pf_row = {}, 0
    ui._pf_status, ui._pf_events = tk.StringVar(), queue.Queue()
    ui._pf_result, ui._log_text, ui._worker, ui._bar = None, None, None, None
    ui._status_var = tk.StringVar()
    installer.SetupUI._show_preflight(ui)
    other.update()
    for c in preflight.run(install_dir).checks:
        installer.SetupUI._pf_add_row(ui, c)
    report("安装器 · 环境检查（真实预检）", overlapping_siblings(other))

    print("\n%s" % ("ALL OK" if not failures else "%d 处重叠" % failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
