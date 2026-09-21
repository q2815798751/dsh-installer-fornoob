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

import update_ui
import updater


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


def _fake_host(root, install_dir):
    return update_ui.Host(
        root=root, icon="", install_dir=install_dir,
        launcher_dir=os.path.join(install_dir, "launcher"),
        exe_path="", launcher_version="test",
        resolve_harness=lambda: (os.path.join(install_dir, "harness"), "npm"),
        stop_backend=lambda: 0, start_backend=lambda: None,
        wait_ready=lambda t: False, authenticated_url=lambda t: "",
        backend_running=lambda: False, open_url=lambda u: True,
        set_busy=lambda b: None, on_close=lambda: None,
        restart_launcher=lambda: None)


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

    win = update_ui.UpdateWindow(_fake_host(root, install_dir))
    win.win.geometry("880x680+10000+10000")     # render far offscreen
    win._show_list()
    report("面板 · 版本列表", overlapping_siblings(win.win))
    win._show_preflight()
    report("面板 · 更新前环境检查（刚打开）", overlapping_siblings(win.win))
    for c in PANEL_CHECKS:
        win._pf_row(c)
    report("面板 · 更新前环境检查（全部行填好）", overlapping_siblings(win.win))

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
