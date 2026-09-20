#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「检查更新」窗口 — launcher.pyw 的第四个按钮打开的那个。

单独一个模块而不是塞进 launcher.pyw：启动面板是 380x500 的无边框小窗，
更新要的是另一个尺寸的东西（版本列表 + 更新日志 + 进度 + 实时日志）。两者
只共享颜色和几个回调，用 Host 传进来，所以这里不 import launcher。

两个独立的更新，互不影响：

    dsh 本体   版本列表 → 选一个 → 环境检查 → npm 安装 → 换目录 → 试运行
    启动器     顶部有一条横幅，有新版就下载并就地替换自己，重启生效

四个页面，按顺序走：
    列表   版本列表（正式版 / 测试版）+ 该版本的更新说明 + 启动器横幅
    检查   更新前环境检查（网络 / 磁盘 / 目录 / 运行时 / 后端），逐项列出
    进行   下载 → 安装 → 校验 → 换目录 → 试运行，带进度条和滚动日志
    结果   成功 / 失败（失败会说明是否已回滚）
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
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
    install_dir: str
    launcher_dir: str
    exe_path: str                       # the running DSHLauncher.exe
    launcher_version: str
    resolve_harness: Callable[[], tuple[str, str]]
    stop_backend: Callable[[], int]
    start_backend: Callable[[], object]
    wait_ready: Callable[[float], bool]
    authenticated_url: Callable[[float], str]
    backend_running: Callable[[], bool]
    open_url: Callable[[str], bool]
    set_busy: Callable[[bool], None]
    on_close: Callable[[], None]
    restart_launcher: Callable[[], None]


class UpdateWindow:
    """One window per launcher. Reopening raises the existing one."""

    def __init__(self, host: Host) -> None:
        self.host = host
        self.win = tk.Toplevel(host.root)
        self.win.title("DSH 检查更新")
        self.win.configure(bg=BG)
        self.win.geometry("880x680")
        self.win.minsize(780, 580)
        try:
            self.win.iconbitmap(host.icon)
        except tk.TclError:
            pass
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        self.releases: list[updater.Release] = []
        self.dist_tags: dict[str, str] = {}
        self.current = ""
        self.channel = "stable"
        self.selected: updater.Release | None = None
        self.report: updater.Report | None = None
        self.worker: threading.Thread | None = None
        self.cancel = threading.Event()
        self.launcher_release: updater.LauncherRelease | None = None
        self._changelog: dict[str, str] = {}
        self._legacy_path = ""

        self._events: queue.Queue[dict] = queue.Queue()
        self._pf_events: queue.Queue[tuple] = queue.Queue()
        self._fetch_events: queue.Queue[tuple] = queue.Queue()
        self._cl_events: queue.Queue[tuple] = queue.Queue()
        self._run_log: tk.Text | None = None
        self._bar: ttk.Progressbar | None = None
        self._bar_mode = ""
        self._page_name = "list"
        self._status_var = tk.StringVar(value="")
        self._head_var = tk.StringVar(value="正在获取官方版本列表…")
        self._busy = False

        self._build()
        self._show_list()
        self._refresh()
        self._poll_all()

    # ---- chrome -----------------------------------------------------------
    def _build(self) -> None:
        head = tk.Frame(self.win, bg=BG, padx=20, pady=14)
        head.pack(fill="x")
        tk.Label(head, text="检查更新", bg=BG, fg=TEXT,
                 font=(UI_FONT, 14, "bold")).pack(side="left")
        tk.Label(head, text="DeepSeek Harness 官方发布", bg=BG, fg=SUBTEXT,
                 font=(UI_FONT, 9)).pack(side="left", padx=(10, 0), pady=(4, 0))
        self.current_label = tk.Label(head, text="", bg=BG, fg=SUBTEXT, font=(MONO, 9))
        self.current_label.pack(side="right", pady=(4, 0))
        self._set_current_label()

        tk.Label(self.win, textvariable=self._head_var, bg=BG, fg=SUBTEXT,
                 font=(UI_FONT, 9), anchor="w", justify="left",
                 wraplength=830).pack(fill="x", padx=20)
        tk.Frame(self.win, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(10, 0))

        self.body = tk.Frame(self.win, bg=BG, padx=20, pady=12)
        self.body.pack(fill="both", expand=True)
        self.page: tk.Frame | None = None

    def _harness(self) -> tuple[str, str]:
        return self.host.resolve_harness()

    def _set_current_label(self) -> None:
        harness_dir, mode = self._harness()
        self.current = updater.installed_version(harness_dir, mode) if harness_dir else ""
        text = "当前 dsh %s ・ 启动器 v%s" % (
            ("v" + self.current) if self.current else "未知", self.host.launcher_version)
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

        # launcher self-update banner, hidden until a newer exe is found
        self.banner = tk.Frame(page, bg="#1B2436", highlightbackground=ACCENT,
                               highlightthickness=1)
        self.banner_label = tk.Label(self.banner, text="", bg="#1B2436", fg=TEXT,
                                     font=(UI_FONT, 9), anchor="w", justify="left")
        self.banner_label.pack(side="left", padx=12, pady=8)
        self.banner_btn = tk.Button(self.banner, text="更新启动器", relief="flat",
                                    bg=ACCENT, fg="#FFFFFF", activebackground="#5B7BFF",
                                    font=(UI_FONT, 9), cursor="hand2", padx=10,
                                    command=self._start_launcher_update)
        self.banner_btn.pack(side="right", padx=10, pady=6)
        self._render_banner()

        tabs = tk.Frame(page, bg=BG)
        self._tabs_frame = tabs
        tabs.pack(fill="x", pady=(8, 8))
        self._tab_buttons: dict[str, tk.Button] = {}
        for key, label in (("stable", "正式版"), ("preview", "测试版 (alpha / rc)")):
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
        self.detail.bind("<Configure>", self._on_detail_configure)
        self._detail_font = tkfont.Font(family=UI_FONT, size=10)
        self._detail_source = ""
        self._detail_px = 0
        self._configure_changelog_tags()

        foot = tk.Frame(page, bg=BG)
        foot.pack(fill="x", pady=(12, 0))
        self.refresh_btn = self._button(foot, "重新获取版本列表", self._refresh, width=16)
        self.refresh_btn.pack(side="left")
        self.update_btn = self._button(foot, "更新到此版本", self._show_preflight,
                                       primary=True, width=16, state="disabled")
        self.update_btn.pack(side="right")
        self._fill_list()

    def _render_banner(self) -> None:
        if not self._alive(getattr(self, "banner", None)):
            return
        release = self.launcher_release
        if release is None:
            self.banner.pack_forget()
            return
        self.banner_label.config(
            text="启动器有新版本 v%s（当前 v%s，%s 发布）"
                 % (release.version, self.host.launcher_version, release.published))
        # Re-pack above the tabs: pack() appends, so it needs an anchor.
        self.banner.pack(fill="x", before=getattr(self, "_tabs_frame", None))

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
            mark = "●" if r.version == self.current else ("★" if r.recommended else " ")
            self.listbox.insert("end", "%s v%-16s %s" % (mark, r.version, r.published[5:]))
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
        # preselect the installed version, else whatever npm's `latest` points at
        index = next((i for i, r in enumerate(items) if r.version == self.current),
                     next((i for i, r in enumerate(items) if r.recommended), 0))
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
        tag = "正式版" if release.stable else "测试版"
        self.detail_head.config(text="v%s" % release.version)
        bits = [tag, release.published]
        if release.recommended:
            bits.append("★ 上游 latest 通道")
        if release.version == self.current:
            bits.append("当前已安装")
        self.detail_sub.config(text=" ・ ".join(b for b in bits if b))

        body = self._changelog.get(release.version)
        if body is None:
            self._set_detail("正在获取该版本的更新说明…")
            self._request_changelog(release.version)
        else:
            self._set_detail(body or "（官方没有填写该版本的更新说明）")
        same = release.version == self.current
        if self._alive(self.update_btn):
            self.update_btn.config(state="disabled" if same else "normal")

    def _set_detail(self, source: str) -> None:
        self._detail_source = source
        self._render_detail()

    def _detail_width(self) -> int:
        """Pixels available inside the changelog pane."""
        self.detail.update_idletasks()
        return max(0, self.detail.winfo_width() - 14)

    def _render_detail(self) -> None:
        """Lay the notes out ourselves.

        The pane runs with wrap="none" and gets explicit breaks from
        updater._wrap_line, because Tk's own word wrap cannot break Chinese
        prose — it only breaks at spaces, so a whole paragraph counts as one
        word and lands on its own line, stranding the bullet above it.
        """
        if not self._alive(self.detail):
            return
        width = self._detail_width()
        if width < 80:                      # not laid out yet; try again
            self.win.after(60, self._render_detail)
            return
        self._detail_px = width
        self.detail.configure(wrap="none")
        updater.insert_markdown(self.detail, self._detail_source,
                                on_link=self._open_link,
                                measure=self._detail_font.measure, width=width)

    def _on_detail_configure(self, event) -> None:
        if abs(event.width - self._detail_px) > 8 and self._detail_source:
            self._render_detail()

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
                 wraplength=830).pack(fill="x", pady=(4, 10))

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
        self._pf_retry = self._button(foot, "重新检查", self._show_preflight, width=12)
        self._pf_retry.pack(side="right", padx=(0, 8))

        threading.Thread(target=self._run_preflight, daemon=True).start()
        self.win.after(120, self._poll_preflight)

    def _run_preflight(self) -> None:
        try:
            harness_dir, mode = self._harness()
            report = updater.preflight(
                self.host.install_dir, harness_dir, mode,
                release=self.selected,
                backend_running=bool(self.host.backend_running()),
                timeout_note="约 1~3 分钟（从 npm 下载约 600 MB）",
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
                 font=(UI_FONT, 9), wraplength=430, justify="left").grid(
                     row=r, column=2, sticky="w")
        if check.hint:
            self._pf_count += 1
            tk.Label(self._pf_rows, text="└ " + check.hint, bg=CARD, fg=SUBTEXT,
                     anchor="w", font=(UI_FONT, 8), wraplength=530, justify="left").grid(
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
        if self.selected is None or self.report is None or not self.report.ok:
            return
        r = self.selected
        proxy_note = ("\n· 将走系统代理 %s" % self.report.proxy) if self.report.proxy else ""
        if not messagebox.askyesno(
                "确认更新",
                "将把 DeepSeek Harness 从 v%s 更新到 v%s。\n\n"
                "· 从 npm 安装官方预编译包，约 1~3 分钟%s\n"
                "· 后端会先被停止，更新完再点启动器的「启动」\n"
                "· 中途失败会自动还原到 v%s，不会留下装坏的环境\n"
                "· 你的设置、API Key 和会话在 ~/.dsh，更新不会碰\n\n"
                "现在开始吗？" % (self.current or "未知", r.version, proxy_note,
                                  self.current or "当前版本"),
                parent=self.win):
            return
        self._start_harness_update()

    def _start_harness_update(self) -> None:
        assert self.selected is not None
        harness_dir, mode = self._harness()
        self._show_run_page("正在更新 DeepSeek Harness",
                            "v%s → v%s" % (self.current or "未知", self.selected.version))
        self._set_busy(True)
        self.worker = updater.UpdateWorker(
            install_dir=self.host.install_dir,
            harness_dir=harness_dir,
            mode=mode,
            release=self.selected,
            events=self._events,
            cancel=self.cancel,
            launcher_dir=self.host.launcher_dir,
            proxy=self.report.proxy if self.report else None,
            stop_backend=self.host.stop_backend,
            start_backend=self.host.start_backend,
            wait_ready=self.host.wait_ready,
            authenticated_url=self.host.authenticated_url)
        self.worker.start()

    def _start_launcher_update(self) -> None:
        release = self.launcher_release
        if release is None:
            return
        if not messagebox.askyesno(
                "更新启动器",
                "将把启动器从 v%s 更新到 v%s。\n\n"
                "· 下载约 %.1f MB，几秒钟\n"
                "· 更新完后需要重启启动器，后端不受影响\n\n"
                "现在开始吗？" % (self.host.launcher_version, release.version,
                                  release.size / 1048576.0),
                parent=self.win):
            return
        self._show_run_page("正在更新启动器",
                            "v%s → v%s" % (self.host.launcher_version, release.version))
        self._set_busy(True)
        self.worker = updater.LauncherUpdateWorker(
            exe_path=self.host.exe_path, release=release, events=self._events,
            cancel=self.cancel, proxy=self.report.proxy if self.report else None)
        self.worker.start()

    def _show_run_page(self, title: str, subtitle: str) -> None:
        page = self._new_page("run")
        tk.Label(page, text=title, bg=BG, fg=TEXT,
                 font=(UI_FONT, 12, "bold")).pack(anchor="w")
        tk.Label(page, text=subtitle, bg=BG, fg=SUBTEXT,
                 font=(MONO, 9)).pack(anchor="w", pady=(2, 8))
        tk.Label(page, textvariable=self._status_var, bg=BG, fg=TEXT, anchor="w",
                 font=(UI_FONT, 10), justify="left", wraplength=830).pack(fill="x",
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
        self._cancel_btn = self._button(foot, "取消", self._cancel_click, width=12)
        self._cancel_btn.pack(side="right")

        self.cancel.clear()
        self._status_var.set("正在准备…")
        self.win.after(200, self._poll_events)
        self.win.after(400, self._poll_run_log)

    def _cancel_click(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            if messagebox.askyesno("取消", "确定要取消吗？\n\n"
                                   "已经下载/安装的部分会被丢弃，并还原到当前版本。",
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
                elif ev["kind"] == "legacy":
                    self._legacy_path = ev["path"]
                elif ev["kind"] == "done":
                    self._finish(ev["ok"], ev["msg"], ev.get("rolled_back", False),
                                 ev.get("restart", False))
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
        path = getattr(self.worker, "log_path", None)
        if path is None or self._run_log is None or self._page_name != "run":
            return
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8", errors="replace") as f:
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
    def _finish(self, ok: bool, msg: str, rolled_back: bool, restart: bool) -> None:
        self._set_busy(False)
        self.cancel.clear()
        if self._bar is not None:
            self._bar.stop()
        page = self._new_page("result")          # also drops _bar / _run_log
        tk.Label(page, text=("更新完成" if ok else "更新未完成"), bg=BG,
                 fg=(GREEN if ok else RED),
                 font=(UI_FONT, 15, "bold")).pack(anchor="w")
        tk.Label(page, text=msg, bg=BG, fg=TEXT, font=(UI_FONT, 10), anchor="w",
                 justify="left", wraplength=810).pack(fill="x", pady=(6, 10))

        if restart:
            lines = ["· 点下面的「重启启动器」让它生效（后端不受影响）"]
        elif ok:
            self._set_current_label()
            lines = [
                "· 现在装的是 dsh v%s" % self.current,
                "· 后端已停止，点启动器里的「启动」再「打开」即可使用",
                "· 你的设置、API Key 和会话在 ~/.dsh，没有被改动",
            ]
            if self._legacy_path:
                lines.append("· 旧的源码目录已经用不上了：%s" % self._legacy_path)
        elif rolled_back:
            lines = [
                "· 已经自动还原到 v%s，可以照常使用" % self.current,
                "· 失败原因见下面的日志（常见的是网络中断或磁盘空间不足）",
            ]
        else:
            lines = [
                "· 安装目录里可能留有 harness.old / harness.new，日志里写了处理办法",
                "· 完整日志：%s" % (getattr(self.worker, "log_path", "") or "launcher\\data\\update.log"),
            ]
        tk.Label(page, text="\n".join(lines), bg=BG, fg=SUBTEXT, font=(UI_FONT, 9),
                 anchor="w", justify="left", wraplength=810).pack(fill="x")

        log_path = getattr(self.worker, "log_path", "")
        if log_path and os.path.exists(log_path):
            wrap = tk.Frame(page, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
            wrap.pack(fill="both", expand=True, pady=(12, 0))
            tail = tk.Text(wrap, bg=CARD, fg="#B7C2D4", relief="flat", font=(MONO, 8),
                           wrap="none", state="disabled", highlightthickness=0, bd=0)
            sb = ttk.Scrollbar(wrap, orient="vertical", command=tail.yview)
            tail.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            tail.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
            try:
                with open(log_path, encoding="utf-8", errors="replace") as f:
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
        if restart:
            self._button(foot, "重启启动器", self._restart, primary=True,
                         width=14).pack(side="right")
        elif ok:
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

    def _restart(self) -> None:
        try:
            self.host.restart_launcher()
        except Exception:
            pass

    # ---- fetching ----------------------------------------------------------
    def _refresh(self) -> None:
        if self._busy:
            return
        if self._alive(getattr(self, "refresh_btn", None)):
            self.refresh_btn.config(state="disabled")
        self._head_var.set("正在获取官方版本列表…")
        threading.Thread(target=self._fetch, daemon=True).start()
        threading.Thread(target=self._fetch_launcher, daemon=True).start()

    def _fetch(self) -> None:
        """Runs on a worker thread and only touches a queue.

        Calling `after()` from here would be a cross-thread tkinter call, which
        works by accident under mainloop() and not at all when the loop is
        driven by update(). The poller owns every widget touch.
        """
        try:
            releases, tags = updater.list_versions()
            self._fetch_events.put((releases, tags, None))
        except Exception as exc:  # noqa: BLE001
            self._fetch_events.put((None, None, exc))

    def _fetch_launcher(self) -> None:
        try:
            self._cl_events.put(("launcher", updater.newer_launcher(
                self.host.launcher_version)))
        except Exception:  # noqa: BLE001
            self._cl_events.put(("launcher", None))

    def _request_changelog(self, version: str) -> None:
        if version in self._changelog:
            return
        self._changelog[version] = ""            # claim it so we fetch once
        threading.Thread(target=self._fetch_changelog, args=(version,),
                         daemon=True).start()

    def _fetch_changelog(self, version: str) -> None:
        try:
            body = updater.changelog_for(version)
        except Exception:  # noqa: BLE001
            body = ""
        self._cl_events.put(("changelog", (version, body)))

    def _poll_all(self) -> None:
        """One poller for every background queue. Owned by the main thread."""
        try:
            while True:
                releases, tags, error = self._fetch_events.get_nowait()
                self._on_fetched(releases, tags, error)
        except queue.Empty:
            pass
        try:
            while True:
                kind, payload = self._cl_events.get_nowait()
                if kind == "launcher":
                    self.launcher_release = payload
                    self._render_banner()
                elif kind == "changelog":
                    version, body = payload
                    self._changelog[version] = body
                    if self.selected is not None and self.selected.version == version:
                        self._set_detail(body or "（官方没有填写该版本的更新说明）")
        except queue.Empty:
            pass
        self.win.after(140, self._poll_all)

    def _on_fetched(self, releases, tags, error) -> None:
        # A fetch can outlive the page it was started from; only touch widgets
        # that are still there.
        if self._alive(getattr(self, "refresh_btn", None)):
            self.refresh_btn.config(state="normal")
        if error is not None:
            self._head_var.set("获取版本列表失败：%s" % error)
            return
        self.releases = releases or []
        self.dist_tags = tags or {}
        self._set_current_label()
        # Upstream currently points `latest` at an rc and publishes no plain
        # release, so opening on an empty 正式版 tab would read as "there is
        # nothing to update". Land on whichever tab actually has releases.
        if self.channel == "stable" and self.releases and not any(
                r.stable for r in self.releases):
            self.channel = "preview"
            self._paint_tabs()

        stable = sum(1 for r in self.releases if r.stable)
        latest = self.dist_tags.get("latest", "")
        if not self.releases:
            self._head_var.set("上游没有任何发布。")
        else:
            newest = self.releases[0]
            head = ("已获取 %d 个官方版本（正式版 %d 个，测试版 %d 个）。最新：v%s（%s）"
                    % (len(self.releases), stable, len(self.releases) - stable,
                       newest.version, newest.published))
            if latest:
                head += "　上游 latest 通道 → v%s" % latest
            self._head_var.set(head)
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
