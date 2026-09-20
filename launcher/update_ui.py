#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「检查更新」窗口 — launcher.pyw 的第四个按钮打开的那个。

单独一个模块而不是塞进 launcher.pyw：启动面板是 380x500 的无边框小窗，
更新要的是另一个尺寸的东西（版本列表 + 更新日志 + 进度 + 实时日志）。两者
只共享颜色和几个回调，用 Host 传进来，所以这里不 import launcher。

四个页面，按顺序走：
    列表   版本列表（正式版 / 测试版两个页签）+ 该版本的更新日志
    检查   更新前环境检查（网络 / 磁盘 / 目录 / 后端），逐项列出
    进行   下载 → 解压 → 重建 → 试运行，带进度条和滚动日志
    结果   成功 / 失败（失败会说明是否已回滚）
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Callable

import updater

# --------------------------------------------------------------------------
# palette — kept in step with launcher.pyw
# --------------------------------------------------------------------------
BG = "#0E1116"
CARD = "#161B24"
BORDER = "#222A36"
TEXT = "#E8ECF3"
SUBTEXT = "#8A94A8"
ACCENT = "#4D6BFE"
GREEN = "#18B358"
AMBER = "#E8A23D"
RED = "#E03B41"

UI_FONT = "Microsoft YaHei UI"
MONO = "Consolas"

_STATUS_COLOR = {updater.OK: (GREEN, "✓"), updater.WARN: (AMBER, "!"),
                 updater.FAIL: (RED, "✕")}


@dataclass
class Host:
    """Everything the update UI borrows from the launcher."""
    root: tk.Tk
    icon: str
    repo_dir: str
    launcher_dir: str
    stop_backend: Callable[[], int]
    start_backend: Callable[[], object]
    wait_ready: Callable[[float], bool]
    authenticated_url: Callable[[float], str]
    backend_running: Callable[[], bool]
    open_url: Callable[[str], bool]
    set_busy: Callable[[bool], None]
    on_close: Callable[[], None]


class UpdateWindow:
    """One window per launcher. Reopening raises the existing one."""

    def __init__(self, host: Host) -> None:
        self.host = host
        self.win = tk.Toplevel(host.root)
        self.win.title("DSH 检查更新")
        self.win.configure(bg=BG)
        self.win.geometry("880x660")
        self.win.minsize(760, 560)
        try:
            self.win.iconbitmap(host.icon)
        except tk.TclError:
            pass
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        self.releases: list[updater.Release] = []
        self.current = updater.installed_version(host.repo_dir)
        self.channel = "stable"
        self.selected: updater.Release | None = None
        self.report: updater.Report | None = None
        self.worker: updater.UpdateWorker | None = None
        self.cancel = threading.Event()
        self._events: queue.Queue[dict] = queue.Queue()
        self._pf_events: queue.Queue[tuple] = queue.Queue()
        self._fetch_events: queue.Queue[tuple] = queue.Queue()
        self._run_log: tk.Text | None = None
        self._bar: ttk.Progressbar | None = None
        self._bar_mode = ""
        self._status_var = tk.StringVar(value="")
        self._head_var = tk.StringVar(value="正在获取官方版本列表…")
        self._busy = False

        self._build()
        self._show_list()
        self._refresh()
        self._poll_fetch()

    # ---- chrome -----------------------------------------------------------
    def _build(self) -> None:
        head = tk.Frame(self.win, bg=BG, padx=20, pady=14)
        head.pack(fill="x")
        tk.Label(head, text="检查更新", bg=BG, fg=TEXT,
                 font=(UI_FONT, 14, "bold")).pack(side="left")
        tk.Label(head, text="DeepSeek Harness 官方发布", bg=BG, fg=SUBTEXT,
                 font=(UI_FONT, 9)).pack(side="left", padx=(10, 0), pady=(4, 0))
        self.current_label = tk.Label(head, text="", bg=BG, fg=SUBTEXT,
                                      font=(MONO, 9))
        self.current_label.pack(side="right", pady=(4, 0))
        self._set_current_label()

        tk.Label(self.win, textvariable=self._head_var, bg=BG, fg=SUBTEXT,
                 font=(UI_FONT, 9), anchor="w", justify="left",
                 wraplength=820).pack(fill="x", padx=20)
        tk.Frame(self.win, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(10, 0))

        self.body = tk.Frame(self.win, bg=BG, padx=20, pady=12)
        self.body.pack(fill="both", expand=True)
        self.page: tk.Frame | None = None

    def _set_current_label(self) -> None:
        text = "当前版本 %s" % ("v" + self.current if self.current else "未知")
        self.current_label.config(text=text)

    def _new_page(self, name: str) -> tk.Frame:
        if self.page is not None:
            self.page.destroy()
        # Every widget below dies with the page, and the background pollers
        # outlive it. They check _page_name (and _bar / _run_log, which are
        # nulled here) before touching anything, so a page switch mid-check
        # cannot poke a destroyed widget.
        self._page_name = name
        self._run_log = None
        self._bar = None
        self._bar_mode = ""
        self.page = tk.Frame(self.body, bg=BG)
        self.page.pack(fill="both", expand=True)
        return self.page

    @staticmethod
    def _alive(widget) -> bool:
        try:
            return widget is not None and bool(widget.winfo_exists())
        except tk.TclError:
            return False

    def _button(self, parent, text, command, *, primary=False, width=12, state="normal"):
        bg, fg, active = ((ACCENT, "#FFFFFF", "#5B7BFF") if primary
                          else (CARD, TEXT, BORDER))
        return tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                         activebackground=active, activeforeground=fg, relief="flat",
                         width=width, cursor="hand2", state=state,
                         font=(UI_FONT, 9), disabledforeground="#5A6478")

    # ---- page: release list ------------------------------------------------
    def _show_list(self) -> None:
        page = self._new_page("list")

        tabs = tk.Frame(page, bg=BG)
        tabs.pack(fill="x", pady=(0, 8))
        self._tab_buttons: dict[str, tk.Button] = {}
        for key, label in (("stable", "正式版"), ("preview", "测试版 (含 alpha / rc)")):
            b = tk.Button(tabs, text=label, relief="flat", cursor="hand2",
                          font=(UI_FONT, 9), padx=12, pady=4,
                          command=lambda k=key: self._switch_channel(k))
            b.pack(side="left", padx=(0, 6))
            self._tab_buttons[key] = b
        self.count_label = tk.Label(tabs, text="", bg=BG, fg=SUBTEXT, font=(UI_FONT, 9))
        self.count_label.pack(side="right")
        self._paint_tabs()

        split = tk.Frame(page, bg=BG)
        split.pack(fill="both", expand=True)

        left = tk.Frame(split, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        left.pack(side="left", fill="y")
        self.listbox = tk.Listbox(
            left, width=30, bg=CARD, fg=TEXT, selectbackground=ACCENT,
            selectforeground="#FFFFFF", activestyle="none", bd=0,
            highlightthickness=0, font=(MONO, 10), exportselection=False)
        lsb = ttk.Scrollbar(left, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=lsb.set)
        lsb.pack(side="right", fill="y")
        self.listbox.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        right = tk.Frame(split, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.detail_head = tk.Label(right, text="请选择左侧的一个版本", bg=CARD, fg=TEXT,
                                    font=(UI_FONT, 10, "bold"), anchor="w")
        self.detail_head.pack(fill="x", padx=12, pady=(10, 0))
        self.detail_sub = tk.Label(right, text="", bg=CARD, fg=SUBTEXT,
                                   font=(UI_FONT, 9), anchor="w")
        self.detail_sub.pack(fill="x", padx=12, pady=(2, 8))
        wrap = tk.Frame(right, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=(12, 4), pady=(0, 10))
        self.detail = tk.Text(wrap, bg=CARD, fg="#C3CCDC", relief="flat", wrap="word",
                              font=(UI_FONT, 10), bd=0, highlightthickness=0,
                              padx=2, spacing1=1, spacing3=3, state="disabled")
        dsb = ttk.Scrollbar(wrap, orient="vertical", command=self.detail.yview)
        self.detail.configure(yscrollcommand=dsb.set)
        dsb.pack(side="right", fill="y")
        self.detail.pack(side="left", fill="both", expand=True)
        self._configure_changelog_tags()

        foot = tk.Frame(page, bg=BG)
        foot.pack(fill="x", pady=(12, 0))
        self.refresh_btn = self._button(foot, "重新获取版本列表", self._refresh, width=16)
        self.refresh_btn.pack(side="left")
        self.update_btn = self._button(foot, "更新到此版本", self._show_preflight,
                                       primary=True, width=16, state="disabled")
        self.update_btn.pack(side="right")
        self._fill_list()

    def _configure_changelog_tags(self) -> None:
        t = self.detail
        t.tag_configure("h1", font=(UI_FONT, 14, "bold"), foreground=TEXT,
                        spacing1=8, spacing3=6)
        t.tag_configure("h2", font=(UI_FONT, 11, "bold"), foreground=TEXT,
                        spacing1=8, spacing3=4)
        t.tag_configure("h3", font=(UI_FONT, 10, "bold"), foreground="#CFD8E8",
                        spacing1=6, spacing3=3)
        t.tag_configure("body", font=(UI_FONT, 10))
        # lmargin2 clears the "• " the renderer writes into the text, so a
        # wrapped bullet lines up under its own text and not under the dot.
        t.tag_configure("bullet", font=(UI_FONT, 10), lmargin1=14, lmargin2=30)
        t.tag_configure("quote", font=(UI_FONT, 10), foreground=SUBTEXT,
                        lmargin1=14, lmargin2=14)
        t.tag_configure("code", font=(MONO, 9), foreground="#9FE8B5",
                        background="#0B0E13", lmargin1=14, lmargin2=14)
        t.tag_configure("rule", foreground=BORDER)
        t.tag_configure("bold", font=(UI_FONT, 10, "bold"))
        t.tag_configure("inlinecode", font=(MONO, 9), foreground="#9FE8B5")
        t.tag_configure("linkstyle", foreground=ACCENT, underline=True)

    def _switch_channel(self, key: str) -> None:
        self.channel = key
        self._paint_tabs()
        self._fill_list()

    def _paint_tabs(self) -> None:
        for key, b in self._tab_buttons.items():
            if key == self.channel:
                b.config(bg=ACCENT, fg="#FFFFFF", activebackground="#5B7BFF")
            else:
                b.config(bg=CARD, fg=SUBTEXT, activebackground=BORDER)

    def _visible(self) -> list[updater.Release]:
        want_stable = self.channel == "stable"
        return [r for r in self.releases if r.stable == want_stable]

    def _fill_list(self) -> None:
        if self.listbox is None:
            return
        self.listbox.delete(0, "end")
        items = self._visible()
        self._visible_refs = items
        for r in items:
            mark = "●" if r.version == self.current else " "
            self.listbox.insert("end", "%s v%-18s %s" % (mark, r.version, r.published[5:]))
        if not items:
            self.count_label.config(text="共 0 个版本")
            self.listbox.insert("end", "")
            self.listbox.insert("end", "  上游暂无该类型的发布")
            self.detail_head.config(text="上游暂无正式版" if self.channel == "stable"
                                    else "上游暂无测试版")
            self.detail_sub.config(text="")
            self._set_detail("该分类下没有任何官方发布。\n\n"
                             "DeepSeek Harness 目前发布的都是 alpha / rc 预览版，"
                             "正式版要等上游发布 vX.Y.Z。")
            self.selected = None
            self.update_btn.config(state="disabled")
            return
        self.count_label.config(text="共 %d 个版本" % len(items))
        # preselect the newest, or the version that is installed
        index = next((i for i, r in enumerate(items) if r.version == self.current), 0)
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self.listbox.see(index)
        self._pick(items[index])

    def _on_select(self, _ev=None) -> None:
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self._visible_refs):
            return
        self._pick(self._visible_refs[sel[0]])

    def _pick(self, release: updater.Release) -> None:
        self.selected = release
        tag = "测试版" if not release.stable else "正式版"
        self.detail_head.config(text="v%s" % release.version)
        extra = "・当前已安装" if release.version == self.current else ""
        self.detail_sub.config(text="%s ・ %s%s" % (tag, release.published, extra))
        body = (release.body or "").strip()
        self._set_detail(body or "（该版本没有填写更新说明）")
        same = release.version == self.current
        self.update_btn.config(state="disabled" if same else "normal")

    def _set_detail(self, source: str) -> None:
        updater.insert_markdown(self.detail, source, on_link=self._open_link)

    def _open_link(self, url: str) -> None:
        # Release notes carry in-page anchors like "#cn-v0.1.6-alpha.1"; only
        # real web links are worth handing to the shell.
        if url.startswith(("http://", "https://")):
            self.host.open_url(url)

    # ---- page: preflight ---------------------------------------------------
    def _show_preflight(self) -> None:
        page = self._new_page("preflight")
        tk.Label(page, text="更新前环境检查", bg=BG, fg=TEXT,
                 font=(UI_FONT, 12, "bold")).pack(anchor="w")
        self._pf_status = tk.StringVar(value="正在检查网络连接与运行环境…")
        tk.Label(page, textvariable=self._pf_status, bg=BG, fg=SUBTEXT,
                 font=(UI_FONT, 9), anchor="w", justify="left",
                 wraplength=820).pack(fill="x", pady=(4, 10))

        card = tk.Frame(page, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True)
        self._pf_rows = tk.Frame(card, bg=CARD)
        self._pf_rows.pack(fill="both", expand=True, padx=14, pady=12)
        self._pf_count = 0

        foot = tk.Frame(page, bg=BG)
        foot.pack(fill="x", pady=(12, 0))
        self._button(foot, "返回版本列表", self._show_list, width=14).pack(side="left")
        self._pf_go = self._button(foot, "开始更新", self._confirm_update,
                                   primary=True, width=14, state="disabled")
        self._pf_go.pack(side="right")
        self._pf_retry = self._button(foot, "重新检查", lambda: self._show_preflight(),
                                      width=12)
        self._pf_retry.pack(side="right", padx=(0, 8))

        threading.Thread(target=self._run_preflight, daemon=True).start()
        self.win.after(120, self._poll_preflight)

    def _run_preflight(self) -> None:
        try:
            report = updater.preflight(
                self.host.repo_dir, self.host.launcher_dir,
                release=self.selected,
                backend_running=bool(self.host.backend_running()),
                timeout_note="约 5~20 分钟（取决于网速；依赖已缓存时更快）",
                report=lambda c: self._pf_events.put(("check", c)))
            self._pf_events.put(("done", report))
        except Exception as exc:  # noqa: BLE001
            self._pf_events.put(("error", exc))

    def _pf_row(self, check: updater.Check) -> None:
        color, mark = _STATUS_COLOR.get(check.status, (SUBTEXT, "·"))
        r = self._pf_count
        self._pf_count += 1
        tk.Label(self._pf_rows, text=mark, bg=CARD, fg=color,
                 font=(UI_FONT, 11, "bold")).grid(row=r, column=0, sticky="w")
        tk.Label(self._pf_rows, text=check.label, bg=CARD, fg=TEXT, anchor="w",
                 font=(UI_FONT, 10)).grid(row=r, column=1, sticky="w", padx=(8, 12))
        tk.Label(self._pf_rows, text=check.detail, bg=CARD, fg=color, anchor="w",
                 font=(UI_FONT, 9), wraplength=420, justify="left").grid(
                     row=r, column=2, sticky="w")
        if check.hint:
            self._pf_count += 1
            tk.Label(self._pf_rows, text="└ " + check.hint, bg=CARD, fg=SUBTEXT,
                     anchor="w", font=(UI_FONT, 8), wraplength=520, justify="left").grid(
                         row=self._pf_count, column=1, columnspan=2, sticky="w", padx=(8, 0))
        self._pf_status.set("已检查 %d 项…" % self._pf_count)

    def _poll_preflight(self) -> None:
        if self._page_name != "preflight":
            return                      # the user navigated away; stop polling
        try:
            while True:
                kind, payload = self._pf_events.get_nowait()
                if kind == "check":
                    self._pf_row(payload)
                elif kind == "done":
                    self.report = payload
                    self._pf_status.set(updater.summarize(payload))
                    self._pf_retry.config(state="normal")
                    if payload.ok:
                        self._pf_go.config(state="normal")
                    else:
                        blockers = "、".join(c.label for c in payload.blockers)
                        self._pf_status.set("发现 %d 项问题，需要先解决：%s"
                                            % (len(payload.blockers), blockers))
                    return
                else:
                    self._pf_status.set("环境检查出错：%s" % payload)
                    self._pf_retry.config(state="normal")
                    return
        except queue.Empty:
            pass
        self.win.after(120, self._poll_preflight)

    # ---- page: running -----------------------------------------------------
    def _confirm_update(self) -> None:
        if self.selected is None or self.report is None:
            return
        if not self.report.ok:
            return
        r = self.selected
        proxy_note = ("\n· 将走系统代理 %s" % self.report.proxy) if self.report.proxy else ""
        if not messagebox.askyesno(
                "确认更新",
                "将把 DeepSeek Harness 从 v%s 更新到 v%s。\n\n"
                "· 更新期间后端的下载与重建大约需要 5~20 分钟%s\n"
                "· 后端会先被停止，更新完再点启动器的「启动」\n"
                "· 中途失败会自动还原到 v%s，不会留下装坏的环境\n\n"
                "现在开始吗？" % (self.current or "未知", r.version, proxy_note,
                                  self.current or "当前版本"),
                parent=self.win):
            return
        self._start_worker()

    def _start_worker(self) -> None:
        assert self.selected is not None
        page = self._new_page("run")
        tk.Label(page, text="正在更新", bg=BG, fg=TEXT,
                 font=(UI_FONT, 12, "bold")).pack(anchor="w")
        tk.Label(page, text="v%s → v%s" % (self.current or "未知", self.selected.version),
                 bg=BG, fg=SUBTEXT, font=(MONO, 9)).pack(anchor="w", pady=(2, 8))
        tk.Label(page, textvariable=self._status_var, bg=BG, fg=TEXT, anchor="w",
                 font=(UI_FONT, 10), justify="left", wraplength=820).pack(fill="x",
                                                                          pady=(0, 8))
        self._bar = ttk.Progressbar(page, maximum=100, value=0)
        self._bar.pack(fill="x")
        self._bar_mode = "determinate"

        wrap = tk.Frame(page, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        wrap.pack(fill="both", expand=True, pady=(12, 0))
        self._run_log = tk.Text(wrap, bg=CARD, fg="#B7C2D4", relief="flat",
                                font=(MONO, 8), wrap="none", state="disabled",
                                highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self._run_log.yview)
        self._run_log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._run_log.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)

        foot = tk.Frame(page, bg=BG)
        foot.pack(fill="x", pady=(12, 0))
        self._cancel_btn = self._button(foot, "取消更新", self._cancel_click, width=12)
        self._cancel_btn.pack(side="right")

        self._set_busy(True)
        self.cancel.clear()
        self._status_var.set("正在准备…")
        self.worker = updater.UpdateWorker(
            repo_dir=self.host.repo_dir, launcher_dir=self.host.launcher_dir,
            release=self.selected, commit="",
            need_commit=lambda: updater.commit_for(self.selected.tag,
                                                   proxy=self.report.proxy
                                                   if self.report else None),
            events=self._events, cancel=self.cancel,
            proxy=self.report.proxy if self.report else None,
            stop_backend=self.host.stop_backend,
            start_backend=self.host.start_backend,
            wait_ready=self.host.wait_ready,
            authenticated_url=self.host.authenticated_url)
        self.worker.start()
        self.win.after(200, self._poll_events)
        self.win.after(400, self._poll_run_log)

    def _cancel_click(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            if messagebox.askyesno("取消更新", "确定要取消吗？\n\n"
                                   "已经下载/构建的部分会被丢弃，并还原到当前版本。",
                                   parent=self.win):
                self.cancel.set()
                self._cancel_btn.config(state="disabled", text="正在取消…")

    def _poll_events(self) -> None:
        if self._bar is None:
            return
        try:
            while True:
                ev = self._events.get_nowait()
                if ev["kind"] == "progress":
                    self._status_var.set(ev["text"])
                    want = "indeterminate" if ev.get("indeterminate") else "determinate"
                    self._set_bar_mode(want)
                    if want == "determinate":
                        self._bar["value"] = ev["pct"]
                elif ev["kind"] == "done":
                    self._finish(ev["ok"], ev["msg"], ev.get("rolled_back", False))
                    return
        except queue.Empty:
            pass
        self.win.after(150, self._poll_events)

    def _set_bar_mode(self, mode: str) -> None:
        if self._bar is None or mode == self._bar_mode:
            return
        self._bar_mode = mode
        if mode == "indeterminate":
            self._bar.config(mode="indeterminate")
            self._bar.start(14)
        else:
            self._bar.stop()
            self._bar.config(mode="determinate")

    def _poll_run_log(self) -> None:
        if self.worker is None or self._run_log is None or self._page_name != "run":
            return
        try:
            if os.path.exists(self.worker.log_path):
                with open(self.worker.log_path, encoding="utf-8", errors="replace") as f:
                    data = f.read()
                self._run_log.config(state="normal")
                self._run_log.delete("1.0", "end")
                self._run_log.insert("end", data)
                self._run_log.see("end")
                self._run_log.config(state="disabled")
        except OSError:
            pass
        if self.worker.is_alive() or self._bar_mode == "indeterminate":
            self.win.after(500, self._poll_run_log)

    # ---- page: result ------------------------------------------------------
    def _finish(self, ok: bool, msg: str, rolled_back: bool) -> None:
        self._set_busy(False)
        self.cancel.clear()
        if self._bar is not None:
            self._bar.stop()
        page = self._new_page("result")   # also drops _bar / _run_log
        tk.Label(page, text=("更新完成" if ok else "更新未完成"), bg=BG,
                 fg=(GREEN if ok else RED),
                 font=(UI_FONT, 15, "bold")).pack(anchor="w")
        tk.Label(page, text=msg, bg=BG, fg=TEXT, font=(UI_FONT, 10), anchor="w",
                 justify="left", wraplength=800).pack(fill="x", pady=(6, 10))

        lines: list[str] = []
        if ok:
            self.current = updater.installed_version(self.host.repo_dir)
            self._set_current_label()
            lines = [
                "· 现在装的是 v%s" % self.current,
                "· 后端已停止，点启动器里的「启动」再「打开」即可使用",
                "· 旧的版本备份已清理，安装日志见 launcher\\data\\update.log",
            ]
        elif rolled_back:
            lines = [
                "· 已经自动还原到 v%s，可以照常使用" % self.current,
                "· 失败原因见下面的日志（常见的是网络中断或磁盘空间不足）",
                "· 处理之后可以回到版本列表重试",
            ]
        else:
            lines = [
                "· 安装目录里可能留有 repo.old / repo.new，日志里写了处理办法",
                "· 完整日志：launcher\\data\\update.log",
            ]
        if lines:
            tk.Label(page, text="\n".join(lines), bg=BG, fg=SUBTEXT, font=(UI_FONT, 9),
                     anchor="w", justify="left", wraplength=800).pack(fill="x")

        if self.worker is not None and os.path.exists(self.worker.log_path):
            wrap = tk.Frame(page, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
            wrap.pack(fill="both", expand=True, pady=(12, 0))
            tail = tk.Text(wrap, bg=CARD, fg="#B7C2D4", relief="flat", font=(MONO, 8),
                           wrap="none", state="disabled", highlightthickness=0, bd=0)
            sb = ttk.Scrollbar(wrap, orient="vertical", command=tail.yview)
            tail.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            tail.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
            try:
                with open(self.worker.log_path, encoding="utf-8", errors="replace") as f:
                    data = f.read()
                tail.config(state="normal")
                tail.insert("end", data)
                tail.see("end")
                tail.config(state="disabled")
            except OSError:
                pass

        foot = tk.Frame(page, bg=BG)
        foot.pack(fill="x", pady=(12, 0))
        self._button(foot, "关闭", self._on_close, width=12).pack(side="left")
        if ok:
            self._button(foot, "启动后端", self._start_and_close, primary=True,
                         width=14).pack(side="right")
        else:
            self._button(foot, "返回版本列表", self._show_list, primary=True,
                         width=14).pack(side="right")

    def _start_and_close(self) -> None:
        try:
            self.host.start_backend()
        except Exception:
            pass
        self._on_close()

    # ---- misc --------------------------------------------------------------
    def _refresh(self) -> None:
        if self._busy:
            return
        self.refresh_btn.config(state="disabled")
        self._head_var.set("正在获取官方版本列表…")
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self) -> None:
        """Runs on a worker thread and only touches a queue.

        Calling `after()` from here would be a cross-thread tkinter call, which
        works by accident under mainloop() and not at all when the loop is
        driven by update(). The poller owns every widget touch.
        """
        try:
            self._fetch_events.put((updater.list_releases(), None))
        except Exception as exc:  # noqa: BLE001
            self._fetch_events.put((None, exc))

    def _poll_fetch(self) -> None:
        try:
            while True:
                releases, error = self._fetch_events.get_nowait()
                self._on_fetched(releases, error)
        except queue.Empty:
            pass
        self.win.after(120, self._poll_fetch)

    def _on_fetched(self, releases, error) -> None:
        # A fetch can outlive the page it was started from; only touch widgets
        # that are still there.
        if self._alive(getattr(self, "refresh_btn", None)):
            self.refresh_btn.config(state="normal")
        if error is not None:
            self._head_var.set("获取版本列表失败：%s" % error)
            return
        self.releases = releases
        self.current = updater.installed_version(self.host.repo_dir)
        self._set_current_label()
        # Upstream currently ships only previews, so opening on an empty 正式版
        # tab would read as "there is nothing to update". Land on whichever tab
        # actually has releases.
        if self.channel == "stable" and releases and not any(r.stable for r in releases):
            self.channel = "preview"
            self._paint_tabs()
        stable = sum(1 for r in releases if r.stable)
        newest = releases[0] if releases else None
        if not releases:
            self._head_var.set("上游没有任何发布。")
        else:
            self._head_var.set(
                "已获取 %d 个官方发布（正式版 %d 个，测试版 %d 个）。最新：%s（%s）%s"
                % (len(releases), stable, len(releases) - stable, newest.name,
                   newest.published,
                   "・已是最新版本" if newest.version == self.current else ""))
        if self._alive(getattr(self, "listbox", None)):
            self._fill_list()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        try:
            self.host.set_busy(busy)
        except Exception:
            pass

    def _on_close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            if not messagebox.askyesno(
                    "更新进行中", "更新还在进行。要取消它并还原到当前版本吗？",
                    parent=self.win):
                return
            self.cancel.set()
            return
        try:
            self.host.on_close()
        except Exception:
            pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass
