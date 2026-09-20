#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH 更新引擎 — 获取上游 deepseek-harness 的官方发布，并按需原地更新。

界面在 launcher.pyw 里；这个模块只做事实部分，纯标准库、可无界面调用：

    list_releases(proxy)        官方 release 列表，分成正式版 / 测试版
    commit_for(tag)             该 tag 的 commit SHA（构建时注入用）
    preflight(...)              更新前环境检查（网络 / 磁盘 / 目录 / 后端）
    UpdateWorker                下载 → 换目录 → pnpm install → pnpm build
                                → 冒烟测试；任何一步失败自动回滚

为什么更新这么"重"：上游只发源码 tarball，没有预编译产物（release 的 assets
是空的）。所以更新一个新版本 = 重新下一份源码 + 重建产物，和装一次的成本
是一个量级。node_modules 会从旧目录搬到新目录，省掉重新下载依赖的大头；
pnpm 的全局 store 也是复用的，所以 install 通常是"重新链接"而不是"重新下载"。

回滚策略：先把新源码解到 repo.new，把 node_modules 搬过去，再把 repo 改名成
repo.old、repo.new 改名成 repo。构建或冒烟测试失败就把 node_modules 搬回
repo.old 并复位。所以任何一步失败，用户的旧版本都还在原地能用。
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import ssl
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------
REPO_SLUG = "deepseek-ai/deepseek-harness"
API_ROOT = "https://api.github.com"
# codeload serves the tag tarball; same URL scripts\build.ps1 packs from, so a
# tree fetched here is known to be buildable by the same pipeline.
CODELOAD = "https://codeload.github.com/%s/tar.gz/refs/tags/%%s" % REPO_SLUG
NPM_REGISTRY_URL = "https://registry.npmjs.org/pnpm"

# GitHub's API rejects requests without a User-Agent.
USER_AGENT = "DSHLauncher-updater"

# New source + extracted copy + build output + the rollback copy of the old
# tree. node_modules is moved, never duplicated, and pnpm's global store is
# reused, so this is well under a second full install's footprint.
REQUIRED_FREE_GB = 5.0
# `pnpm build` runs tsc with --max-old-space-size=4096.
REQUIRED_RAM_GB = 6.0

# `-alpha.2`, `-rc.1`, `-beta.3` … anything with a stability suffix is a
# preview. Upstream currently publishes *only* previews, so the 正式版 list is
# legitimately empty until they cut a plain vX.Y.Z.
_PRERELEASE_RE = re.compile(r"-(alpha|beta|rc|pre|preview|dev|next|canary)", re.I)

_CREATE_NO_WINDOW = 0x08000000
_CHUNK = 256 * 1024

OK, WARN, FAIL = "ok", "warn", "fail"


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _opener(proxy: str | None):
    """urllib opener that either forces a direct route or uses `proxy`.

    Same shape as installer/preflight.py's probe(): the proxy has to be set on
    the handler (not passed to urlopen) because OpenerDirector.open() takes no
    `context` argument.
    """
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": "http://" + proxy,
                                                     "https": "http://" + proxy}))
    else:
        handlers.append(urllib.request.ProxyHandler({}))
    handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    return urllib.request.build_opener(*handlers)


def _friendly_net_error(exc: Exception) -> str:
    text = str(exc)
    reason = getattr(exc, "reason", None)
    if reason is not None:
        text = "%s: %s" % (type(reason).__name__, reason)
    for needle, message in (
        ("Name or service not known", "域名解析失败 (DNS)"),
        ("getaddrinfo", "域名解析失败 (DNS)"),
        ("CERTIFICATE", "TLS 证书校验失败"),
        ("timed out", "连接超时"),
        ("TimeoutError", "连接超时"),
        ("refused", "连接被拒绝"),
        ("unreachable", "网络不可达"),
    ):
        if needle.lower() in text.lower():
            return message
    return text[:110]


def probe(url: str, proxy: str | None = None, timeout: float = 12.0,
          method: str = "GET") -> tuple[bool, str]:
    """One real request. Returns (reachable, human detail).

    A TCP connect is not enough: a captive portal or a half-dead proxy accepts
    the connection and then blackholes it, which is exactly the failure that
    would otherwise surface twenty minutes into `pnpm install`.
    """
    req = urllib.request.Request(url, method=method,
                                 headers={"User-Agent": USER_AGENT,
                                          "Accept": "application/vnd.github+json"})
    started = time.time()
    try:
        with _opener(proxy).open(req, timeout=timeout) as resp:  # noqa: S310
            resp.read(64)
            return True, "连通 (%.1fs)" % (time.time() - started)
    except urllib.error.HTTPError as exc:
        # The server answered — including a 405 to our HEAD, or a 403 body —
        # which is all a reachability probe is asking.
        return True, "连通 (HTTP %d)" % exc.code
    except Exception as exc:  # noqa: BLE001
        return False, _friendly_net_error(exc)


def system_proxy() -> str | None:
    """The Windows Internet Options proxy as `host:port`, when enabled.

    pnpm/corepack read proxies from the environment only, never from this
    setting, so when the direct route is dead we have to hand it over
    explicitly.
    """
    key = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings"

    def query(name: str) -> str | None:
        try:
            out = subprocess.run(["reg", "query", key, "/v", name], capture_output=True,
                                 text=True, creationflags=_CREATE_NO_WINDOW, timeout=15)
        except Exception:
            return None
        if out.returncode != 0:
            return None
        for line in out.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0].lower() == name.lower():
                return parts[-1]
        return None

    if (query("ProxyEnable") or "0") not in ("1", "0x1"):
        return None
    server = query("ProxyServer")
    if not server:
        return None
    if "=" in server:                     # "http=h:p;https=h:p"
        for part in server.split(";"):
            if "=" in part:
                scheme, value = part.split("=", 1)
                if scheme.strip().lower() in ("https", "http") and value.strip():
                    server = value.strip()
                    break
    server = server.strip()
    if not server or ":" not in server:
        return None
    return server


def _free_gb(path: str) -> float:
    probe_path = path
    while probe_path and not os.path.isdir(probe_path):
        parent = os.path.dirname(probe_path)
        if parent == probe_path:
            break
        probe_path = parent
    try:
        return shutil.disk_usage(probe_path or os.path.abspath(os.sep)).free / 1073741824.0
    except OSError:
        return -1.0


def _total_ram_gb() -> float:
    try:
        import ctypes

        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return stat.ullTotalPhys / 1073741824.0
    except Exception:
        pass
    return -1.0


def _rmtree(path: str) -> None:
    """rmtree that survives Windows read-only attributes and deep paths."""
    if not os.path.exists(path):
        return
    try:
        shutil.rmtree(path)
        return
    except OSError:
        pass
    # Long node_modules paths defeat the classic API; the \\?\ prefix does not.
    try:
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", "\\\\?\\" + os.path.abspath(path)],
                       capture_output=True, creationflags=_CREATE_NO_WINDOW, timeout=900)
    except Exception:
        pass


def installed_version(repo_dir: str) -> str:
    """The harness version currently on disk, from its own package.json.

    package.json is the ground truth: it is what the build stamps into the
    client bundles, and it survives a copy/sync that a side-car file would not.
    """
    pkg = os.path.join(repo_dir, "package.json")
    try:
        with open(pkg, encoding="utf-8") as f:
            version = json.load(f).get("version")
        if isinstance(version, str) and version:
            return version
    except (OSError, ValueError):
        pass
    try:                                  # last resort: what the uninstaller shows
        out = subprocess.run(
            ["reg", "query", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSeekHarness",
             "/v", "DisplayVersion"],
            capture_output=True, text=True, creationflags=_CREATE_NO_WINDOW, timeout=15)
        for line in out.stdout.splitlines():
            if "DisplayVersion" in line:
                return line.split()[-1]
    except Exception:
        pass
    return ""


def set_registered_version(version: str) -> None:
    """Keep 「设置 → 应用」 in step with what is actually installed."""
    try:
        subprocess.run(
            ["reg", "add", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSeekHarness",
             "/f", "/v", "DisplayVersion", "/d", version],
            capture_output=True, creationflags=_CREATE_NO_WINDOW, timeout=20)
    except Exception:
        pass


def runtime_dir_for(repo_dir: str, launcher_dir: str) -> tuple[str, str]:
    """Locate the portable Node runtime. Returns (dir, node_exe).

    Kept in sync with launcher.pyw's _resolve_node(): the normal install has
    repo/ and runtime/ as siblings, but repo.txt can point the repo elsewhere,
    in which case runtime/ stays next to the launcher.
    """
    for d in (os.path.join(os.path.dirname(repo_dir), "runtime"),
              os.path.join(launcher_dir, "runtime"),
              os.path.join(os.path.dirname(launcher_dir), "runtime")):
        node = os.path.join(d, "node.exe")
        if os.path.exists(node):
            return d, node
    return "", "node"                    # dev checkout: hope for PATH


# --------------------------------------------------------------------------
# release list
# --------------------------------------------------------------------------
@dataclass
class Release:
    tag: str                 # dsh-v0.1.6-alpha.2
    name: str                # v0.1.6-alpha.2
    version: str             # 0.1.6-alpha.2
    published: str           # 2026-09-17 (local date, display only)
    prerelease: bool         # the flag GitHub carries
    body: str                # the release notes (markdown)
    tarball_url: str = ""

    @property
    def stable(self) -> bool:
        """正式版 = 既没被标 prerelease，版本号里也没有 alpha/beta/rc 后缀。

        Both signals are required because upstream marks every release as a
        prerelease today, including ones that read like plain versions.
        """
        return (not self.prerelease) and not _PRERELEASE_RE.search(self.version)

    @property
    def channel(self) -> str:
        return "stable" if self.stable else "preview"


def _version_of(tag: str) -> str:
    return re.sub(r"^dsh-?v?", "", tag or "").strip() or (tag or "")


def _get_json(url: str, proxy: str | None = None, timeout: float = 25.0):
    """GET a GitHub API URL and decode it. Raises RuntimeError with a readable
    Chinese message — a raw traceback is useless in this UI."""
    import json
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with _opener(proxy).open(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403 and exc.headers.get("X-RateLimit-Remaining") == "0":
            raise RuntimeError("GitHub 接口访问次数已用尽（未登录时每小时 60 次），"
                               "请等一会儿再试，或在路由器/代理上换个出口 IP。") from exc
        if exc.code == 404:
            raise RuntimeError("上游仓库或该版本不存在（HTTP 404）。") from exc
        raise RuntimeError("GitHub 接口返回 HTTP %d。" % exc.code) from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("无法访问 GitHub 接口：%s" % _friendly_net_error(exc)) from exc


def list_releases(proxy: str | None = None, per_page: int = 30) -> list[Release]:
    """Official releases, newest first.

    Drafts are dropped (they are not published yet), and the list is sorted by
    publication date rather than by version string — `0.1.5-rc.2` and
    `0.1.6-alpha.1` do not order the way a human would read them.
    """
    data = _get_json("%s/repos/%s/releases?per_page=%d" % (API_ROOT, REPO_SLUG, per_page),
                     proxy=proxy)
    if not isinstance(data, list):
        raise RuntimeError("GitHub 返回了预期之外的数据。")
    releases: list[Release] = []
    for item in data:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        tag = item.get("tag_name") or ""
        if not tag:
            continue
        releases.append(Release(
            tag=tag,
            name=(item.get("name") or tag).strip(),
            version=_version_of(tag),
            published=(item.get("published_at") or item.get("created_at") or "")[:10],
            prerelease=bool(item.get("prerelease")),
            body=item.get("body") or "",
            tarball_url=item.get("tarball_url") or "",
        ))
    releases.sort(key=lambda r: r.published, reverse=True)
    return releases


def commit_for(tag: str, proxy: str | None = None) -> str:
    """The commit a tag points at.

    `pnpm build` stamps DSH_CLIENT_COMMIT_HASH into the client bundles, and the
    payload has no .git for it to fall back on. `commits/{ref}` resolves both
    lightweight and annotated tags in one call.
    """
    data = _get_json("%s/repos/%s/commits/%s" % (API_ROOT, REPO_SLUG, tag), proxy=proxy)
    sha = (data or {}).get("sha") if isinstance(data, dict) else None
    if not sha:
        raise RuntimeError("无法解析 %s 的 commit SHA。" % tag)
    return sha


def tarball_url(release: Release) -> str:
    """The codeload URL for a tag.

    Preferred over the API's own tarball_url: codeload is the host
    scripts\\build.ps1 already packs from, it serves the bytes directly instead
    of a redirect, and it does not share the API's 60-requests-per-hour budget.
    """
    return CODELOAD % release.tag


# --------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------
@dataclass
class Check:
    key: str
    label: str
    status: str = OK
    detail: str = ""
    hint: str = ""

    @property
    def fatal(self) -> bool:
        return self.status == FAIL


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    proxy: str | None = None

    @property
    def blockers(self) -> list[Check]:
        return [c for c in self.checks if c.fatal]

    @property
    def ok(self) -> bool:
        return not self.blockers


def _check_network(proxy_in: str | None, release: Release | None) -> tuple[list[Check], str | None]:
    """Three hosts, one verdict.

    api.github.com is needed to list versions, codeload to fetch the source,
    and registry.npmjs.org for `pnpm install`. They are probed separately
    because they fail separately: an npm mirror or a corporate allowlist can
    leave GitHub reachable and the registry not.
    """
    checks: list[Check] = []
    used_proxy: str | None = None
    proxy_tried = False

    def run(key: str, label: str, url: str, method: str = "GET", optional: bool = False) -> None:
        nonlocal used_proxy, proxy_tried
        ok, detail = probe(url, proxy=used_proxy or proxy_in, timeout=12.0, method=method)
        if not ok and not used_proxy:
            # Direct route is dead — try the system proxy once, then re-probe.
            proxy_tried = True
            sysproxy = system_proxy()
            if sysproxy:
                ok2, detail2 = probe(url, proxy=sysproxy, timeout=12.0, method=method)
                if ok2:
                    used_proxy = sysproxy
                    checks.append(Check(key, label, WARN, "直连失败 (%s)" % detail,
                                        "已改用系统代理 %s" % sysproxy))
                    return
                detail = "%s；代理 %s 也不通" % (detail, sysproxy)
        c = Check(key, label)
        if ok:
            c.detail = detail
        elif optional:
            c.status, c.detail = WARN, detail
        else:
            c.status, c.detail = FAIL, detail
        checks.append(c)

    run("gh_api", "官方发布接口 (api.github.com)",
        "%s/repos/%s/releases?per_page=1" % (API_ROOT, REPO_SLUG))
    if release is not None:
        # HEAD, not GET: the body is the whole source tree.
        run("gh_codeload", "源码下载源 (codeload.github.com)",
            tarball_url(release), method="HEAD")
    run("npm", "依赖源 (registry.npmjs.org)", NPM_REGISTRY_URL)

    if used_proxy:
        checks.insert(0, Check("proxy", "系统代理", WARN, used_proxy,
                               "更新时会自动走这个代理下载源码与依赖。"))
    elif proxy_tried:
        checks.insert(0, Check("proxy", "系统代理", WARN, "直连与系统代理都不通",
                               "如果本机需要代理上网，请先打开代理软件再重试。"))
    else:
        checks.insert(0, Check("proxy", "系统代理", OK, "未使用（直连可用）"))
    return checks, used_proxy


def preflight(repo_dir: str, launcher_dir: str, release: Release | None = None,
              backend_running: bool = False, timeout_note: str = "",
              report: Callable[[Check], None] | None = None) -> Report:
    """Everything that must be true before the disk is touched.

    `release` is the version about to be installed, and is used for the
    codeload probe — that host serves the tarball for one specific tag.
    """
    result = Report()

    def add(c: Check) -> None:
        result.checks.append(c)
        if report is not None:
            try:
                report(c)
            except Exception:
                pass

    net_checks, proxy = _check_network(None, release)
    for c in net_checks:
        add(c)
    result.proxy = proxy

    # --- disk -------------------------------------------------------------
    c = Check("disk", "磁盘空间")
    free = _free_gb(repo_dir)
    if free < 0:
        c.status, c.detail = WARN, "无法读取磁盘剩余空间"
    elif free < REQUIRED_FREE_GB:
        c.status = FAIL
        c.detail = "剩余 %.1f GB，需要至少 %.0f GB" % (free, REQUIRED_FREE_GB)
        c.hint = "新版本源码、构建产物和旧版本备份都在同一个盘上。"
    else:
        c.detail = "剩余 %.1f GB" % free
    add(c)

    # --- writability ------------------------------------------------------
    c = Check("writable", "安装目录可写")
    parent = os.path.dirname(os.path.abspath(repo_dir)) or repo_dir
    try:
        os.makedirs(parent, exist_ok=True)
        probe_file = os.path.join(parent, ".dsh-update-write-test")
        with open(probe_file, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe_file)
        c.detail = os.path.abspath(parent)
    except OSError as exc:
        c.status, c.detail = FAIL, "无法写入：%s" % exc
        c.hint = "请换一个目录，或先关闭占用该目录的程序。"
    add(c)

    # --- runtime + repo ---------------------------------------------------
    c = Check("repo", "已安装的框架")
    if not os.path.exists(os.path.join(repo_dir, "package.json")):
        c.status, c.detail = FAIL, "找不到 %s" % os.path.join(repo_dir, "package.json")
        c.hint = "这台机器上似乎没有通过本安装包装过 DeepSeek Harness。"
    else:
        c.detail = "v%s" % installed_version(repo_dir)
    add(c)

    runtime_dir, node = runtime_dir_for(repo_dir, launcher_dir)
    c = Check("runtime", "内置 Node 运行时")
    corepack = os.path.join(runtime_dir, "node_modules", "corepack", "dist", "corepack.js")
    if runtime_dir and os.path.exists(corepack):
        c.detail = runtime_dir
    else:
        c.status, c.detail = FAIL, "找不到 %s" % (corepack or "runtime/node.exe")
        c.hint = "重新运行一次 DSHSetup.exe 可以修复内置运行时。"
    add(c)

    # --- memory -----------------------------------------------------------
    c = Check("memory", "内存")
    total = _total_ram_gb()
    if total < 0:
        c.status, c.detail = WARN, "无法读取"
    elif total < REQUIRED_RAM_GB:
        c.status = WARN
        c.detail = "共 %.1f GB，建议 %.0f GB 以上" % (total, REQUIRED_RAM_GB)
        c.hint = "构建前端时 Node 最多会申请 4 GB 内存，内存偏小会让更新变慢。"
    else:
        c.detail = "共 %.1f GB" % total
    add(c)

    # --- backend ----------------------------------------------------------
    c = Check("backend", "后端运行状态")
    if backend_running:
        c.status, c.detail = WARN, "正在运行"
        c.hint = "更新会自动先停掉后端，更新完再让你自己点「启动」。"
    else:
        c.detail = "未运行"
    add(c)

    if timeout_note:
        add(Check("estimate", "预计耗时", WARN, timeout_note,
                  "中途请勿关闭窗口；失败会自动回滚到当前版本。"))
    return result


def summarize(report: Report) -> str:
    if report.ok:
        return "环境检查通过，可以开始更新。"
    return "发现 %d 项问题，需要先解决。" % len(report.blockers)


# --------------------------------------------------------------------------
# update worker
# --------------------------------------------------------------------------
class UpdateCancelled(Exception):
    pass


class UpdateWorker(threading.Thread):
    """Download one release, rebuild the installed tree from it, roll back on
    any failure.

    Process control stays with the caller: `stop_backend` / `start_backend` /
    `wait_ready` / `authenticated_url` are launcher.pyw's, because it already
    owns pid.txt, web.log and the port probe. This module only knows how to
    fetch, unpack and build.
    """

    def __init__(self, *, repo_dir: str, launcher_dir: str, release: Release, commit: str,
                 events, cancel: threading.Event, proxy: str | None = None,
                 log_path: str | None = None, need_commit: Callable[[], str] | None = None,
                 stop_backend: Callable[[], int] | None = None,
                 start_backend: Callable[[], object] | None = None,
                 wait_ready: Callable[[float], bool] | None = None,
                 authenticated_url: Callable[[float], str] | None = None,
                 smoke_test: bool = True) -> None:
        super().__init__(daemon=True, name="dsh-updater")
        self.repo_dir = os.path.abspath(repo_dir)
        self.launcher_dir = os.path.abspath(launcher_dir)
        self.parent_dir = os.path.dirname(self.repo_dir)
        self.new_dir = os.path.join(self.parent_dir, "repo.new")
        self.old_dir = os.path.join(self.parent_dir, "repo.old")
        self.release = release
        self.commit = commit
        self.need_commit = need_commit
        self.events = events
        self.cancel = cancel
        self.proxy = proxy
        self.log_path = log_path or os.path.join(self.launcher_dir, "data", "update.log")
        self.stop_backend = stop_backend
        self.start_backend = start_backend
        self.wait_ready = wait_ready
        self.authenticated_url = authenticated_url
        self.smoke_test = smoke_test and all(
            (start_backend, wait_ready, authenticated_url))

        runtime_dir, self.node = runtime_dir_for(self.repo_dir, self.launcher_dir)
        self.runtime_dir = runtime_dir
        self._swapped = False          # repo/ currently holds the NEW tree
        self._deps_moved = False       # node_modules has been relocated
        # "passed" | "skipped" | "unavailable" — see _smoke_test().
        self.smoke = "unavailable"

    # ---- event plumbing ---------------------------------------------------
    def emit(self, kind: str, **kw) -> None:
        self.events.put({"kind": kind, **kw})

    def progress(self, pct: float, text: str, indeterminate: bool = False) -> None:
        self.emit("progress", pct=float(pct), text=text, indeterminate=indeterminate)

    def log(self, msg: str) -> None:
        line = time.strftime("[%H:%M:%S] ") + msg + "\n"
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise UpdateCancelled()

    def _rename(self, src: str, dst: str, tries: int = 6) -> None:
        """os.replace with a short retry.

        Windows refuses to rename a directory while any handle is open on it,
        and an antivirus scanner or the Search indexer is enough to hold one
        for a moment. Failing the whole update on that would be absurd, so
        back off briefly and try again before giving up.
        """
        for attempt in range(tries):
            try:
                os.replace(src, dst)
                return
            except OSError as exc:
                if attempt == tries - 1:
                    raise
                self.log("改名 %s 暂时不可用 (%s)，%.1fs 后重试"
                         % (os.path.basename(src), exc, 0.5 * (attempt + 1)))
                time.sleep(0.5 * (attempt + 1))

    # ---- entry ------------------------------------------------------------
    def run(self) -> None:
        try:
            self._update()
        except UpdateCancelled:
            self.log("更新已取消")
            rolled = self._rollback("用户取消")
            self.emit("done", ok=False,
                      msg="更新已取消，当前仍是 v%s。" % (installed_version(self.repo_dir)
                                                          or "之前的版本"),
                      rolled_back=rolled)
        except Exception as exc:  # noqa: BLE001
            self.log("!! 更新失败: %r" % (exc,))
            rolled = self._rollback(str(exc))
            self.emit("done", ok=False, msg="更新失败：%s" % exc, rolled_back=rolled)
        else:
            note = ("（试运行被跳过：端口上已有别的服务，请点一次「启动」确认）"
                    if self.smoke == "skipped" else "")
            self.emit("done", ok=True, msg="已更新到 v%s%s" % (self.release.version, note),
                      rolled_back=False, smoke=self.smoke)

    def _update(self) -> None:
        t0 = time.time()
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.write("== DSH 更新 %s -> %s (%s) ==\n" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    self.release.version, self.release.tag))
        except OSError:
            pass

        self.progress(1, "正在准备…")
        self.log("目标版本: %s (%s)" % (self.release.version, self.release.tag))
        self.log("安装目录: %s" % self.parent_dir)

        # The commit is needed for DSH_CLIENT_COMMIT_HASH; fetch it before the
        # download so a rate-limited API fails in seconds, not in ten minutes.
        if not self.commit and self.need_commit is not None:
            self.progress(2, "正在解析 %s 的 commit…" % self.release.tag)
            self.commit = self.need_commit()
        self.log("commit: %s" % (self.commit or "<未获取>"))

        self._stop_backend()
        self._prepare_dirs()
        self._download()
        self._extract()
        self._move_deps()
        self._swap_in()
        self._build()
        self._smoke_test()
        self._finalize(t0)

    # ---- steps ------------------------------------------------------------
    def _stop_backend(self) -> None:
        if self.stop_backend is None:
            return
        self.progress(4, "正在停止后端…")
        try:
            killed = self.stop_backend()
            self.log("已停止后端 (PID 数: %s)" % killed)
        except Exception as exc:  # noqa: BLE001
            self.log("停止后端时出错（继续）: %r" % (exc,))
        time.sleep(1.0)              # let the OS release file locks

    def _prepare_dirs(self) -> None:
        self.progress(6, "正在清理上一次的临时目录…")
        # A leftover repo.new means a previous run died before swapping; the
        # live repo/ is authoritative, so the leftover is disposable.
        for stale in (self.new_dir,):
            if os.path.exists(stale):
                self.log("清理残留目录 %s" % stale)
                _rmtree(stale)
        if os.path.exists(self.old_dir):
            # Only reachable if a previous rollback itself failed. Keep it and
            # work around it rather than destroying what may be the good copy.
            self.log("警告: %s 已存在，改名保留" % self.old_dir)
            self.old_dir = self.old_dir + ".%d" % int(time.time())
        os.makedirs(self.new_dir, exist_ok=True)

    def _download(self) -> None:
        url = tarball_url(self.release)
        dest = os.path.join(self.new_dir, "source.tar.gz")
        last: Exception | None = None
        for attempt in range(1, 4):
            self._check_cancel()
            try:
                self._download_once(url, dest)
                return
            except UpdateCancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                last = exc
                self.log("下载失败 (第 %d 次): %s" % (attempt, exc))
                if attempt < 3:
                    self.progress(8, "下载失败，%d 秒后重试 (%d/3)…" % (3 * attempt, attempt))
                    for _ in range(3 * attempt):
                        self._check_cancel()
                        time.sleep(1.0)
        raise RuntimeError("源码下载失败：%s" % last)

    def _download_once(self, url: str, dest: str) -> None:
        self.log("$ GET %s" % url)
        self.progress(8, "正在下载 v%s 源码…" % self.release.version)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        started = time.time()
        try:
            resp = _opener(self.proxy).open(req, timeout=60)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(_friendly_net_error(exc)) from exc
        with resp:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            try:
                with open(dest, "wb") as out:
                    while True:
                        self._check_cancel()
                        chunk = resp.read(_CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                        got += len(chunk)
                        if total:
                            frac = got / total
                            self.progress(8 + 26 * frac,
                                          "正在下载 v%s 源码… %.1f / %.1f MB" % (
                                              self.release.version, got / 1048576.0,
                                              total / 1048576.0))
                        else:
                            self.progress(20, "正在下载 v%s 源码… %.1f MB" % (
                                self.release.version, got / 1048576.0))
            except Exception:
                try:
                    os.remove(dest)
                except OSError:
                    pass
                raise
        if got == 0:
            raise RuntimeError("下载到 0 字节")
        self.log("下载完成: %.1f MB, 用时 %.1fs" % (got / 1048576.0, time.time() - started))
        self.progress(34, "源码下载完成 (%.1f MB)" % (got / 1048576.0))

    def _extract(self) -> None:
        self._check_cancel()
        tar_path = os.path.join(self.new_dir, "source.tar.gz")
        self.progress(35, "正在解压源码…")
        self.log("解压 %s -> %s" % (tar_path, self.new_dir))
        count = 0
        with tarfile.open(tar_path, "r:gz") as tf:
            members = tf.getmembers()
            total = len(members)
            for i, m in enumerate(members):
                self._check_cancel()
                if i % 500 == 0:
                    self.progress(35 + 10 * i / max(total, 1),
                                  "正在解压源码… (%d/%d)" % (i, total))
                if not (m.isfile() or m.isdir()):
                    continue                     # symlinks/links: not needed on Windows
                parts = m.name.split("/")
                if len(parts) < 2:               # the archive's single top folder
                    continue
                rel_parts = parts[1:]
                if any(p in ("", ".", "..") for p in rel_parts):
                    continue                     # traversal guard
                target = os.path.join(self.new_dir, *rel_parts)
                if m.isdir():
                    os.makedirs(target, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                src = tf.extractfile(m)
                if src is None:
                    continue
                with src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                count += 1
        if not os.path.exists(os.path.join(self.new_dir, "package.json")):
            raise RuntimeError("解压出来的源码里没有 package.json，压缩包可能不完整。")
        try:
            os.remove(tar_path)
        except OSError:
            pass
        self.log("解压完成: %d 个文件" % count)
        self.progress(45, "源码解压完成 (%d 个文件)" % count)

    def _move_deps(self) -> None:
        """Carry node_modules across so `pnpm install` relinks instead of
        re-downloading ~4 GB of packages. A rename inside one directory tree,
        so it costs nothing even at this size."""
        self._check_cancel()
        self.progress(46, "正在复用已下载的依赖…")
        for name in ("node_modules", ".pnpm-store"):
            src = os.path.join(self.repo_dir, name)
            if not os.path.exists(src):
                continue
            dst = os.path.join(self.new_dir, name)
            if os.path.exists(dst):
                continue
            try:
                self._rename(src, dst)
                self.log("已迁移 %s" % src)
                self._deps_moved = True
            except OSError:
                try:
                    shutil.move(src, dst)
                    self.log("已迁移 %s (move)" % src)
                    self._deps_moved = True
                except Exception as exc:  # noqa: BLE001
                    self.log("迁移 %s 失败（会重新下载依赖）: %r" % (name, exc))

    def _swap_in(self) -> None:
        self._check_cancel()
        self.progress(48, "正在切换目录…")
        self._rename(self.repo_dir, self.old_dir)
        try:
            self._rename(self.new_dir, self.repo_dir)
        except OSError:
            self._rename(self.old_dir, self.repo_dir)   # put it back, then fail
            raise
        self._swapped = True
        self.log("已切换: %s -> repo (旧版本保留在 %s)" % (self.new_dir, self.old_dir))

    # ---- pnpm -------------------------------------------------------------
    def _pnpm_env(self) -> dict:
        env = dict(os.environ)
        env["PATH"] = self.runtime_dir + os.pathsep + env.get("PATH", "")
        env["COREPACK_ENABLE_DOWNLOAD_PROMPT"] = "0"
        if self.proxy:
            url = "http://" + self.proxy
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                env[name] = url
            env["NO_PROXY"] = env["no_proxy"] = "localhost,127.0.0.1"
        return env

    def _corepack_js(self) -> str:
        return os.path.join(self.runtime_dir, "node_modules", "corepack", "dist", "corepack.js")

    def _run_streamed(self, cmd: list[str], cwd: str, env: dict) -> int:
        self.log("$ %s" % " ".join(cmd))
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        assert proc.stdout is not None
        tail: list[str] = []
        try:
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                self.log(line)
                if line.strip():
                    tail.append(line.strip())
                    del tail[:-3]
                    self.emit("log", msg=line.strip())     # live line for the UI
                if self.cancel.is_set():
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True, creationflags=_CREATE_NO_WINDOW)
                    raise UpdateCancelled()
        finally:
            proc.stdout.close()
        code = proc.wait()
        if code != 0 and tail:
            self.log("最后输出: %s" % " | ".join(tail))
        return code

    def _build(self) -> None:
        node, corepack = self.node, self._corepack_js()
        if not os.path.exists(corepack):
            raise RuntimeError("内置 Node 缺少 corepack：%s" % corepack)

        self.progress(50, "正在准备 pnpm…", indeterminate=True)
        shims = os.path.join(self.runtime_dir, "pnpm.cmd")
        if not os.path.exists(shims):
            code = self._run_streamed(
                [node, corepack, "enable", "--install-directory", self.runtime_dir],
                self.runtime_dir, self._pnpm_env())
            if code != 0:
                raise RuntimeError("corepack enable 失败 (exit %d)" % code)
        self._check_cancel()

        self.progress(55, "正在下载/链接依赖 (pnpm install)，通常 2~10 分钟…",
                      indeterminate=True)
        code = self._run_streamed([node, corepack, "pnpm", "install"],
                                  self.repo_dir, self._pnpm_env())
        if code != 0:
            raise RuntimeError("依赖安装失败 (exit %d)，详见 %s" % (code, self.log_path))
        self._check_cancel()

        self.progress(75, "正在构建 (pnpm build)，通常 3~10 分钟…", indeterminate=True)
        env = self._pnpm_env()
        env["DSH_CLIENT_COMMIT_HASH"] = self.commit or self.release.tag
        code = self._run_streamed([node, corepack, "pnpm", "build"], self.repo_dir, env)
        if code != 0:
            raise RuntimeError("构建失败 (exit %d)，详见 %s" % (code, self.log_path))

    # ---- smoke test -------------------------------------------------------
    def _smoke_test(self) -> None:
        """Start the freshly built server and wait for its tokenized URL.

        The build succeeding is not the same as the app running — a version
        that bumped its Node requirement, or a build step that silently
        produced nothing, only shows up here. Failing here rolls back, which is
        the whole point of paying for this check.

        The check is only worth anything if the URL comes from the server *we*
        started. `start_backend` returning nothing means something was already
        listening on the port, in which case the token in the log belongs to
        that other process — so report a skip rather than a pass.
        """
        if not self.smoke_test:
            self.log("跳过冒烟测试（无后端控制回调）")
            self.smoke = "unavailable"
            return
        self._check_cancel()
        self.progress(90, "正在试运行新版本…", indeterminate=True)
        try:
            started = self.start_backend()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("新版本启动失败：%s" % exc) from exc
        if not started:
            self.log("!! 端口上已有服务在监听，新的后端没有被启动，试运行无法进行")
            self.log("!! 这次更新没有验证新版本能否启动，请更新完点一次「启动」确认")
            self.smoke = "skipped"
            self.progress(96, "端口被占用，已跳过试运行")
            return
        if not self.wait_ready(90.0):
            try:
                self.stop_backend()
            except Exception:
                pass
            raise RuntimeError("新版本启动后 90 秒内没有监听端口，见 data/web.log")
        url = self.authenticated_url(40.0)
        self.log("试运行地址: %s" % url)
        if "token=" not in url:
            try:
                self.stop_backend()
            except Exception:
                pass
            raise RuntimeError("新版本没有输出登录令牌，网页会返回 401")
        try:
            self.stop_backend()
        except Exception:
            pass
        time.sleep(0.8)
        self.smoke = "passed"
        self.progress(96, "试运行通过")

    # ---- finish / rollback ------------------------------------------------
    def _finalize(self, t0: float) -> None:
        self.progress(97, "正在收尾…")
        _rmtree(self.old_dir)
        if os.path.exists(self.old_dir):
            # A file was still held open by something (a scanner, an editor).
            # It is dead weight, not breakage — say so instead of claiming a
            # clean sweep.
            self.log("旧版本备份没能删干净，可以手工删除 %s" % self.old_dir)
        else:
            self.log("已清理旧版本备份 %s" % self.old_dir)
        self._write_version_record()
        set_registered_version(self.release.version)
        self.progress(100, "完成，用时 %.1f 分钟" % ((time.time() - t0) / 60.0))
        self.log("更新完成，用时 %.1f 分钟" % ((time.time() - t0) / 60.0))

    def _write_version_record(self) -> None:
        path = os.path.join(self.launcher_dir, "data", "version.json")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"version": self.release.version, "tag": self.release.tag,
                           "commit": self.commit,
                           "installed_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                          f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def _restore_deps(self, from_root: str, to_root: str) -> None:
        """Move node_modules back to the tree that owns it."""
        os.makedirs(to_root, exist_ok=True)
        for name in ("node_modules", ".pnpm-store"):
            src = os.path.join(from_root, name)
            if not os.path.exists(src):
                continue
            dst = os.path.join(to_root, name)
            if os.path.exists(dst):
                _rmtree(dst)
            try:
                self._rename(src, dst)
                self.log("已迁回 %s" % name)
            except OSError as exc:
                self.log("迁回 %s 失败: %r" % (name, exc))

    def _rollback(self, reason: str) -> bool:
        """Put the previous tree back, best effort at every step.

        Returns True when the installed version ends up whole and usable —
        which includes the case where nothing had been moved yet. False only
        when the restore itself failed; then both trees are still on disk and
        the log says which is which.
        """
        self.log("开始回滚（原因: %s）" % reason)
        try:
            if not self._swapped:
                # repo/ should still be the old version. Two things can still
                # need undoing: node_modules may already have been moved into
                # the scratch tree, and a swap that failed halfway can have
                # left repo/ missing entirely.
                if (not os.path.exists(os.path.join(self.repo_dir, "package.json"))
                        and os.path.exists(os.path.join(self.old_dir, "package.json"))):
                    if os.path.exists(self.repo_dir):
                        _rmtree(self.repo_dir)
                    self._rename(self.old_dir, self.repo_dir)
                    self.log("已从 %s 恢复 repo" % self.old_dir)
                if self._deps_moved:
                    self._restore_deps(self.new_dir, self.repo_dir)
                _rmtree(self.new_dir)
                return True

            # node_modules currently lives inside the failed new tree; it
            # belongs to the old one, so move it back before discarding.
            if self._deps_moved:
                self._restore_deps(self.repo_dir, self.old_dir)
            _rmtree(self.repo_dir)
            self._rename(self.old_dir, self.repo_dir)
            self._swapped = False
            self.log("回滚完成，仍是 v%s" % installed_version(self.repo_dir))
            return True
        except Exception as exc:  # noqa: BLE001
            self.log("!! 回滚失败: %r" % (exc,))
            self.log("旧版本仍在 %s，新版本在 %s，可按需手工改名" % (self.old_dir, self.repo_dir))
            return False


# --------------------------------------------------------------------------
# markdown → tkinter text (no third-party renderer in a stdlib-only exe)
# --------------------------------------------------------------------------
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_RULE_RE = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")
# **bold**, `code`, [text](url), and bare URLs.
_INLINE_RE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]*\]\([^)\s]+\)|https?://\S+)")

# The harness release notes are GitHub-flavoured markdown with raw HTML mixed
# in — `<h3 id="cn-…">新增功能</h3>`, `<a href=…>`, `<br>`, `<details>`. Strip
# the markup so the pane reads as prose instead of showing the tags.
_HTML_HEADING_RE = re.compile(r"^\s*<h([1-6])[^>]*>\s*(.*?)\s*</h\1>\s*$", re.I)
_HTML_LINK_RE = re.compile(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_HTML_BR_RE = re.compile(r"<br\s*/?>", re.I)
_HTML_HR_RE = re.compile(r"^\s*<hr\s*/?>\s*$", re.I)
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def _clean_html(line: str) -> str:
    """Turn the raw HTML upstream mixes into its markdown into plain text."""
    line = _HTML_LINK_RE.sub(lambda m: "[%s](%s)" % (m.group(2).strip(), m.group(1)), line)
    line = _HTML_TAG_RE.sub("", line)
    return html.unescape(line).replace("\xa0", " ")


def render_markdown(source: str) -> list[tuple[str, str]]:
    """Flatten a release body into (tag, text) lines.

    Deliberately lossy: the goal is that a non-technical user can read what
    changed, not that the markdown round-trips. Tags are consumed by
    `insert_markdown()` below.
    """
    out: list[tuple[str, str]] = []
    in_code = False
    text = (source or "").replace("\r\n", "\n").replace("\r", "\n")
    for raw in text.split("\n"):
        # A <br> is a line break, so it splits before any other parsing.
        for piece in (_HTML_BR_RE.split(raw) if not in_code else [raw]):
            line = piece.rstrip()
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                out.append(("code", line))
                continue
            if _HTML_HR_RE.match(line) or _RULE_RE.match(line):
                out.append(("rule", ""))
                continue
            m = _HTML_HEADING_RE.match(line)
            if m:
                out.append(("h%d" % min(int(m.group(1)), 3), _clean_html(m.group(2)).strip()))
                continue
            line = _clean_html(line)
            if not line.strip():
                out.append(("gap", ""))
                continue
            m = _HEADING_RE.match(line)
            if m:
                out.append(("h%d" % min(len(m.group(1)), 3), m.group(2).strip()))
                continue
            m = _QUOTE_RE.match(line)
            if m:
                out.append(("quote", m.group(1).strip()))
                continue
            m = _BULLET_RE.match(line)
            if m:
                out.append(("bullet",
                            "  " * (len(m.group(1)) // 2) + "• " + m.group(2).strip()))
                continue
            m = _ORDERED_RE.match(line)
            if m:
                out.append(("bullet", "  " * (len(m.group(1)) // 2)
                            + "%s. %s" % (m.group(2), m.group(3).strip())))
                continue
            out.append(("body", line.strip()))
    # collapse runs of blank lines
    collapsed: list[tuple[str, str]] = []
    for kind, body in out:
        if kind == "gap" and (not collapsed or collapsed[-1][0] == "gap"):
            continue
        collapsed.append((kind, body))
    return collapsed


def insert_markdown(widget, source: str, on_link=None) -> list[tuple[str, str]]:
    """Render `source` into a tk.Text that already has the style tags.

    Returns the (label, url) of every link written, so the caller can wire
    clicks. Tags the caller must define: h1/h2/h3, code, inlinecode, bold,
    bullet, body, quote, rule.
    """
    links: list[tuple[str, str]] = []
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    for kind, text in render_markdown(source):
        if kind == "gap":
            widget.insert("end", "\n")
        elif kind == "rule":
            widget.insert("end", "─" * 42 + "\n", ("rule",))
        elif kind == "code":
            widget.insert("end", (text or " ") + "\n", ("code",))
        elif kind in ("h1", "h2", "h3"):
            widget.insert("end", text + "\n", (kind,))
        else:
            for chunk, url in _inline_pieces(text):
                if url is None:
                    widget.insert("end", chunk)
                    continue
                tag = "link%d" % len(links)
                links.append((chunk, url))
                start = widget.index("end-1c")
                widget.insert("end", chunk, ("linkstyle", tag))
                widget.tag_add(tag, start, "%s+%dc" % (start, len(chunk)))
                widget.tag_bind(tag, "<Button-1>", lambda _e, u=url: on_link and on_link(u))
                widget.tag_bind(tag, "<Enter>",
                                lambda _e: widget.configure(cursor="hand2"))
                widget.tag_bind(tag, "<Leave>", lambda _e: widget.configure(cursor=""))
            widget.insert("end", "\n", (kind,))
    widget.configure(state="disabled")
    return links


def _inline_pieces(text: str) -> list[tuple[str, str | None]]:
    """Split one line into (chunk, url) runs; url is None for plain text.

    Bold and code runs are flattened to their text: the caller styles the whole
    line, and matching the markdown's inline emphasis exactly is not worth the
    complexity in a changelog pane.
    """
    pieces: list[tuple[str, str | None]] = []
    for part in _INLINE_RE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            pieces.append((part[2:-2], None))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            pieces.append((part[1:-1], None))
        elif part.startswith("[") and "](" in part and part.endswith(")"):
            label, url = part[1:-1].split("](", 1)
            pieces.append((label or url, url))
        elif part.startswith(("http://", "https://")):
            pieces.append((part, part))
        else:
            pieces.append((part, None))
    return pieces
