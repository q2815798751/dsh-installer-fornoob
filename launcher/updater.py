#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH 更新引擎 — 从 npm 拿官方发布的 dsh，原地换掉，失败自动回滚。

界面在 update_ui.py 里；这个模块只做事实部分，纯标准库、可无界面调用：

    list_versions(proxy)        npm 上的全部版本 + 通道（latest / next / alpha）
    changelog_for(version)      该版本在 GitHub release 里的更新说明
    preflight(...)              更新前环境检查（网络 / 磁盘 / 目录 / 运行时 / 后端）
    UpdateWorker                npm 安装 → 换目录 → 试运行；任何一步失败自动回滚
    list_launcher_releases()    启动器自身的发布（用于启动器自更新）

**为什么走 npm 而不是源码**：上游只把预编译包发到 npm（`@deepseek-ai/dsh`，
官方 README 的安装方式就是 `npx @deepseek-ai/dsh web`），GitHub release 上一个
资产都没有。走 npm 之后更新只是「下一个约 600 MB 的包」，约一分钟，不需要源码
树、不需要 pnpm、不需要在用户机器上构建，也就彻底不需要任何编译器。

**启动器和 dsh 本体是分开的**：harness 装在 <install>\\harness（npm 前缀），
启动器在 <install>\\launcher，用户数据在 ~/.dsh。换 harness 碰不到启动器，
也碰不到用户的设置、密钥和会话。

**npm 11 的 install 脚本默认不跑，这里显式 --ignore-scripts 固定这个行为**：
上游的包都自带各平台的 prebuild，实测 node-pty / koffi 不跑脚本也能正常加载；
而 node-pty 的脚本是 `prebuild.js || node-gyp rebuild`，一旦触发回退就会要求
MSVC，把「不需要编译器」这条承诺毁掉。装完的冒烟测试是这条选择的兜底。
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

def _SYS32(name: str) -> str:
    """Absolute path to a Windows system tool.

    Bare names resolve through PATH, so a directory earlier in PATH wins — a
    trivial way to make this program execute somebody else's taskkill.exe.
    Nothing here needs that risk; the path is always the same.
    """
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    return os.path.join(root, "System32", name)




# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------
NPM_NAME = "@deepseek-ai/dsh"
NPM_REGISTRY = "https://registry.npmjs.org"
# The changelog lives in the GitHub release for the matching tag; npm metadata
# carries no release notes.
GH_SLUG = "deepseek-ai/deepseek-harness"
GH_TAG_PREFIX = "dsh-v"
API_ROOT = "https://api.github.com"

# The launcher's own releases, published here. Publicly readable, so the
# self-update needs no credentials on the user's machine.
LAUNCHER_SLUG = "q2815798751/dsh-installer-fornoob"
LAUNCHER_ASSET = "DSHLauncher.exe"

USER_AGENT = "DSHLauncher-updater"

# Measured on a full install of @deepseek-ai/dsh: 486 packages, 600 MB on disk.
# The margin covers the staging copy that exists during the swap.
REQUIRED_FREE_GB = 2.5
# `pnpm build` used to need 4 GB of RAM in the source layout. The npm layout
# ships prebuilt JS, so this is only a low-memory warning now.
REQUIRED_RAM_GB = 4.0

# Layout markers, kept in step with launcher.pyw.
NPM_ENTRY = os.path.join("node_modules", "@deepseek-ai", "dsh", "lib", "bin.js")
SOURCE_ENTRY = os.path.join("apps", "cli", "src", "bin.ts")

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
    would otherwise surface minutes into an npm install.
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
        # The server answered — including a 405 to our HEAD — which is all a
        # reachability probe is asking.
        return True, "连通 (HTTP %d)" % exc.code
    except Exception as exc:  # noqa: BLE001
        return False, _friendly_net_error(exc)


def system_proxy() -> str | None:
    """The Windows Internet Options proxy as `host:port`, when enabled.

    npm reads proxies from the environment only, never from this setting, so
    when the direct route is dead we have to hand it over explicitly.
    """
    key = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings"

    def query(name: str) -> str | None:
        try:
            out = subprocess.run([_SYS32("reg.exe"), "query", key, "/v", name], capture_output=True,
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
        subprocess.run([_SYS32("cmd.exe"), "/c", "rmdir", "/s", "/q", "\\\\?\\" + os.path.abspath(path)],
                       capture_output=True, creationflags=_CREATE_NO_WINDOW, timeout=900)
    except Exception:
        pass


# --------------------------------------------------------------------------
# the installed harness
# --------------------------------------------------------------------------
def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def installed_version(harness_dir: str, mode: str = "") -> str:
    """The harness version currently on disk.

    npm layout: the published package's own package.json. Source layout
    (installer ≤1.4): the checkout's root package.json. Both are the ground
    truth for what is actually installed.
    """
    if not mode:
        mode = "npm" if os.path.exists(os.path.join(harness_dir, NPM_ENTRY)) else "source"
    if mode == "npm":
        pkg = os.path.join(harness_dir, "node_modules", "@deepseek-ai", "dsh", "package.json")
    else:
        pkg = os.path.join(harness_dir, "package.json")
    version = _read_json(pkg).get("version")
    if isinstance(version, str) and version:
        return version
    try:                                  # last resort: what the uninstaller shows
        out = subprocess.run(
            [_SYS32("reg.exe"), "query", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSeekHarness",
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
            [_SYS32("reg.exe"), "add", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSeekHarness",
             "/f", "/v", "DisplayVersion", "/d", version],
            capture_output=True, creationflags=_CREATE_NO_WINDOW, timeout=20)
    except Exception:
        pass


def runtime_dir_for(install_dir: str, harness_dir: str = "",
                    launcher_dir: str = "") -> tuple[str, str]:
    """Locate the portable Node runtime. Returns (dir, node_exe).

    Kept in step with launcher.pyw's _resolve_node(). The runtime is normally a
    sibling of harness/, but a `harness.txt` override can point elsewhere, in
    which case runtime/ stays next to the launcher.
    """
    for d in (os.path.join(install_dir, "runtime"),
              os.path.join(launcher_dir, "runtime") if launcher_dir else "",
              os.path.join(os.path.dirname(harness_dir), "runtime") if harness_dir else ""):
        if not d:
            continue
        node = os.path.join(d, "node.exe")
        if os.path.exists(node):
            return d, node
    # No bundled runtime. Callers check for an empty dir and refuse, rather
    # than resolving the bare name `node` through PATH.
    return "", ""


def npm_cli_js(runtime_dir: str) -> str:
    """npm's entry script inside the portable runtime.

    Invoked as `node npm-cli.js …` rather than through a `npm.cmd` shim: the
    shims only exist after `corepack enable`, and this way there is exactly one
    way to run npm and no PATH dependency at all.
    """
    return os.path.join(runtime_dir, "node_modules", "npm", "bin", "npm-cli.js")


def legacy_repo_dir(install_dir: str) -> str:
    """The pre-1.5 source checkout, if this install still has one."""
    path = os.path.join(install_dir, "repo")
    return path if os.path.exists(os.path.join(path, SOURCE_ENTRY)) else ""


# --------------------------------------------------------------------------
# version list (npm registry)
# --------------------------------------------------------------------------
@dataclass
class Release:
    version: str                              # 0.1.6-alpha.2
    published: str = ""                       # 2026-09-17
    channels: list[str] = field(default_factory=list)   # npm dist-tags pointing here
    body: str = ""                            # changelog, filled on demand

    @property
    def tag(self) -> str:
        """The GitHub tag carrying this version's release notes."""
        return GH_TAG_PREFIX + self.version

    @property
    def stable(self) -> bool:
        """正式版 = 版本号里没有 alpha/beta/rc 这类后缀。

        Not derived from npm's `latest` tag: upstream points `latest` at an rc,
        so that tag answers "what do we install by default", not "what is
        finished".
        """
        return not _PRERELEASE_RE.search(self.version)

    @property
    def channel(self) -> str:
        return "stable" if self.stable else "preview"

    @property
    def recommended(self) -> bool:
        return "latest" in self.channels


def _version_key(version: str) -> tuple:
    """Sort key that puts 0.1.6-alpha.2 above 0.1.5-rc.2 and a plain release
    above every prerelease of the same numbers."""
    core, _, pre = version.partition("-")
    nums = []
    for part in core.split("."):
        try:
            nums.append(int(part))
        except ValueError:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    # No suffix sorts last (i.e. highest) for the same core version.
    return (tuple(nums), 0 if pre else 1, pre)


def _get_json(url: str, proxy: str | None = None, timeout: float = 25.0, accept: str = ""):
    """GET a JSON API and decode it. Raises RuntimeError with a readable
    Chinese message — a raw traceback is useless in this UI."""
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    try:
        with _opener(proxy).open(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError("接口返回 404：这个版本或仓库不存在。") from exc
        if exc.code == 403 and exc.headers.get("X-RateLimit-Remaining") == "0":
            raise RuntimeError("GitHub 接口访问次数已用尽（未登录时每小时 60 次），"
                               "请等一会儿再试，或换个出口 IP。") from exc
        raise RuntimeError("接口返回 HTTP %d。" % exc.code) from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("无法访问接口：%s" % _friendly_net_error(exc)) from exc


def list_versions(proxy: str | None = None) -> tuple[list[Release], dict]:
    """Every published version of `@deepseek-ai/dsh`, newest first.

    Returns (releases, dist_tags). The registry is the authority on what can
    actually be installed, and it publishes faster and more reliably than
    GitHub here.
    """
    doc = _get_json("%s/%s" % (NPM_REGISTRY, urllib.parse.quote(NPM_NAME, safe="")),
                    proxy=proxy)
    if not isinstance(doc, dict) or "versions" not in doc:
        raise RuntimeError("npm 源返回了预期之外的数据。")
    times = doc.get("time") or {}
    tags = {k: v for k, v in (doc.get("dist-tags") or {}).items() if isinstance(v, str)}
    by_version: dict[str, list[str]] = {}
    for name, version in tags.items():
        by_version.setdefault(version, []).append(name)

    releases = []
    for version in doc["versions"]:
        releases.append(Release(
            version=version,
            published=str(times.get(version, ""))[:10],
            channels=sorted(by_version.get(version, [])),
        ))
    releases.sort(key=lambda r: (_version_key(r.version), r.published), reverse=True)
    return releases, tags


def changelog_for(version: str, proxy: str | None = None) -> str:
    """The GitHub release body for `dsh-v<version>`.

    Best effort: npm carries no release notes, and a failed lookup should cost
    the user a paragraph, not the whole update.
    """
    try:
        doc = _get_json("%s/repos/%s/releases/tags/%s"
                        % (API_ROOT, GH_SLUG, GH_TAG_PREFIX + version), proxy=proxy)
    except RuntimeError:
        return ""
    return (doc or {}).get("body") or ""


def fetch_changelogs(releases: list[Release], proxy: str | None = None,
                     limit: int = 30) -> None:
    """Attach release notes to `releases` in place, newest first."""
    for release in releases[:limit]:
        if release.body is None:
            continue
        release.body = changelog_for(release.version, proxy=proxy)


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
    """The npm registry is the one host the update cannot do without.

    GitHub is probed separately as an optional check: it only supplies the
    release notes, so an unreachable GitHub must not block an update.
    """
    checks: list[Check] = []
    used_proxy: str | None = None
    proxy_tried = False

    def run(key: str, label: str, url: str, optional: bool = False) -> None:
        nonlocal used_proxy, proxy_tried
        ok, detail = probe(url, proxy=used_proxy or proxy_in, timeout=12.0)
        if not ok and not used_proxy:
            proxy_tried = True
            sysproxy = system_proxy()
            if sysproxy:
                ok2, detail2 = probe(url, proxy=sysproxy, timeout=12.0)
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
            c.status, c.detail, c.hint = WARN, detail, "只影响更新说明的显示，不影响更新。"
        else:
            c.status, c.detail = FAIL, detail
        checks.append(c)

    run("npm", "npm 源 (registry.npmjs.org)",
        "%s/%s" % (NPM_REGISTRY, urllib.parse.quote(NPM_NAME, safe="")))
    run("github", "更新说明来源 (api.github.com)", "%s/repos/%s" % (API_ROOT, GH_SLUG),
        optional=True)
    if release is not None:
        checks.append(Check("target", "目标版本", OK, "v%s%s" % (
            release.version,
            "（上游 latest 通道）" if release.recommended else "")))

    if used_proxy:
        checks.insert(0, Check("proxy", "系统代理", WARN, used_proxy,
                               "更新时会自动走这个代理下载依赖。"))
    elif proxy_tried:
        checks.insert(0, Check("proxy", "系统代理", WARN, "直连与系统代理都不通",
                               "如果本机需要代理上网，请先打开代理软件再重试。"))
    else:
        checks.insert(0, Check("proxy", "系统代理", OK, "未使用（直连可用）"))
    return checks, used_proxy


def preflight(install_dir: str, harness_dir: str, mode: str = "",
              release: Release | None = None, backend_running: bool = False,
              has_backend: bool = True, timeout_note: str = "",
              report: Callable[[Check], None] | None = None) -> Report:
    """Everything that must be true before the disk is touched."""
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
    free = _free_gb(install_dir)
    if free < 0:
        c.status, c.detail = WARN, "无法读取磁盘剩余空间"
    elif free < REQUIRED_FREE_GB:
        c.status = FAIL
        c.detail = "剩余 %.1f GB，需要至少 %.1f GB" % (free, REQUIRED_FREE_GB)
        c.hint = "新版和旧版会在切换的一瞬间同时存在。"
    else:
        c.detail = "剩余 %.1f GB" % free
    add(c)

    # --- writability ------------------------------------------------------
    c = Check("writable", "安装目录可写")
    try:
        os.makedirs(install_dir, exist_ok=True)
        probe_file = os.path.join(install_dir, ".dsh-update-write-test")
        with open(probe_file, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe_file)
        c.detail = install_dir
    except OSError as exc:
        c.status, c.detail = FAIL, "无法写入：%s" % exc
        c.hint = "请换一个目录，或先关闭占用该目录的程序。"
    add(c)

    # --- current harness --------------------------------------------------
    current = installed_version(harness_dir, mode)
    c = Check("harness", "已安装的 dsh")
    if mode == "missing" or not current:
        c.status = FAIL
        c.detail = "找不到已安装的 dsh（%s）" % harness_dir
        c.hint = "这台机器上似乎没有通过本安装包装过 dsh 本体。"
    else:
        c.detail = "v%s（%s 布局）" % (current, "npm" if mode == "npm" else "源码")
    add(c)

    # --- runtime + npm ----------------------------------------------------
    runtime_dir, node = runtime_dir_for(install_dir, harness_dir)
    npm = npm_cli_js(runtime_dir) if runtime_dir else ""
    c = Check("runtime", "内置 Node 运行时")
    if runtime_dir and os.path.exists(npm):
        c.detail = runtime_dir
    else:
        c.status, c.detail = FAIL, "找不到 %s" % (npm or "runtime/node.exe")
        c.hint = "重新运行一次 DSHSetup.exe 可以修复内置运行时。"
    add(c)

    # --- memory -----------------------------------------------------------
    c = Check("memory", "内存")
    total = _total_ram_gb()
    if total < 0:
        c.status, c.detail = WARN, "无法读取"
    elif total < REQUIRED_RAM_GB:
        c.status, c.detail = WARN, "共 %.1f GB，建议 %.0f GB 以上" % (total, REQUIRED_RAM_GB)
        c.hint = "内存偏小会让安装变慢。"
    else:
        c.detail = "共 %.1f GB" % total
    add(c)

    # --- backend ----------------------------------------------------------
    if has_backend:
        c = Check("backend", "后端运行状态")
        if backend_running:
            c.status, c.detail = WARN, "正在运行"
            c.hint = "更新会自动先停掉后端，更新完再让你自己点「启动」。"
        else:
            c.detail = "未运行"
        add(c)

    legacy = legacy_repo_dir(install_dir)
    if legacy and mode == "npm":
        add(Check("legacy", "旧版源码目录", WARN, os.path.basename(legacy),
                  "已经用不上了，可以删掉腾出空间。"))

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
    """Install one npm version, swap it in, roll back on any failure.

    Process control stays with the caller: `stop_backend` / `start_backend` /
    `wait_ready` / `authenticated_url` are launcher.pyw's, because it already
    owns pid.txt, web.log and the port probe. This module only knows how to
    fetch and install.
    """

    def __init__(self, *, install_dir: str, harness_dir: str, mode: str,
                 release: Release, events, cancel: threading.Event,
                 launcher_dir: str = "", proxy: str | None = None,
                 log_path: str | None = None,
                 stop_backend: Callable[[], int] | None = None,
                 start_backend: Callable[[], object] | None = None,
                 wait_ready: Callable[[float], bool] | None = None,
                 authenticated_url: Callable[[float], str] | None = None,
                 smoke_test: bool = True) -> None:
        super().__init__(daemon=True, name="dsh-updater")
        self.install_dir = os.path.abspath(install_dir)
        self.harness_dir = os.path.abspath(harness_dir)
        self.mode = mode
        self.release = release
        self.events = events
        self.cancel = cancel
        self.proxy = proxy
        self.launcher_dir = launcher_dir
        self.log_path = log_path or os.path.join(launcher_dir or self.install_dir,
                                                 "data", "update.log")
        self.stop_backend = stop_backend
        self.start_backend = start_backend
        self.wait_ready = wait_ready
        self.authenticated_url = authenticated_url
        self.smoke_test = smoke_test and all(
            (start_backend, wait_ready, authenticated_url))

        # The npm layout always lives at <install>\harness, whatever the current
        # layout is. `harness_dir` is where the harness lives *now* (which may
        # be the legacy <install>\repo); `target_dir` is where it is going.
        # Conflating the two would rename a fresh npm tree into repo\ and, on
        # rollback, delete a source tree the user still needs.
        self.target_dir = os.path.join(self.install_dir, "harness")
        self.new_dir = os.path.join(self.install_dir, "harness.new")
        self.old_dir = os.path.join(self.install_dir, "harness.old")
        self.runtime_dir, self.node = runtime_dir_for(self.install_dir, self.harness_dir,
                                                      launcher_dir)
        self._had_old = False          # a previous harness was moved aside
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
        for a moment. Failing the whole update on that would be absurd.
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
            current = installed_version(self.harness_dir, self.mode)
            self.emit("done", ok=False,
                      msg="更新已取消，当前仍是 v%s。" % (current or "之前的版本"),
                      rolled_back=rolled, smoke=self.smoke)
        except Exception as exc:  # noqa: BLE001
            self.log("!! 更新失败: %r" % (exc,))
            rolled = self._rollback(str(exc))
            self.emit("done", ok=False, msg="更新失败：%s" % exc, rolled_back=rolled,
                      smoke=self.smoke)
        else:
            note = ("（试运行被跳过：端口上已有别的服务，请点一次「启动」确认）"
                    if self.smoke == "skipped" else "")
            self.emit("done", ok=True,
                      msg="已更新到 v%s%s" % (self.release.version, note),
                      rolled_back=False, smoke=self.smoke)

    def _update(self) -> None:
        t0 = time.time()
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.write("== DSH 更新 %s -> %s (npm) ==\n" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"), self.release.version))
        except OSError:
            pass

        self.progress(2, "正在准备…")
        self.log("目标版本: %s" % self.release.version)
        self.log("安装目录: %s" % self.install_dir)
        self.log("当前布局: %s (%s)" % (self.mode, self.harness_dir))

        self._stop_backend()
        self._prepare_dirs()
        self._npm_install()
        self._verify_new()
        self._swap_in()
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
        # A leftover harness.new means a previous run died before swapping; the
        # live harness/ is authoritative, so the leftover is disposable.
        if os.path.exists(self.new_dir):
            self.log("清理残留目录 %s" % self.new_dir)
            _rmtree(self.new_dir)
        if os.path.exists(self.old_dir):
            # Only reachable if a previous rollback itself failed. Keep it and
            # work around it rather than destroying what may be the good copy.
            self.log("警告: %s 已存在，改名保留" % self.old_dir)
            self.old_dir = self.old_dir + ".%d" % int(time.time())
        os.makedirs(self.new_dir, exist_ok=True)

    def _npm_env(self) -> dict:
        env = dict(os.environ)
        env["PATH"] = self.runtime_dir + os.pathsep + env.get("PATH", "")
        # npm reads proxies from the environment and nowhere else.
        if self.proxy:
            url = "http://" + self.proxy
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                env[name] = url
            env["NO_PROXY"] = env["no_proxy"] = "localhost,127.0.0.1"
        return env

    def _npm_install(self) -> None:
        """Install the target version into the staging prefix."""
        npm = npm_cli_js(self.runtime_dir)
        if not os.path.exists(npm):
            raise RuntimeError("内置 Node 缺少 npm：%s" % npm)
        cmd = [
            self.node, npm, "install",
            "--no-audit", "--no-fund",
            # See the module docstring: upstream ships prebuilds, and running
            # install scripts would risk a node-gyp fallback that needs MSVC.
            "--ignore-scripts",
            "--loglevel=warn",
            "%s@%s" % (NPM_NAME, self.release.version),
        ]
        self.progress(10, "正在从 npm 下载 v%s（约 600 MB，通常 1~3 分钟）…"
                      % self.release.version, indeterminate=True)
        code = self._run_streamed(cmd, self.new_dir, self._npm_env())
        if code != 0:
            raise RuntimeError("npm 安装失败 (exit %d)，详见 %s" % (code, self.log_path))

    def _verify_new(self) -> None:
        self._check_cancel()
        self.progress(70, "正在校验…", indeterminate=True)
        entry = os.path.join(self.new_dir, NPM_ENTRY)
        if not os.path.exists(entry):
            raise RuntimeError("装完了但找不到 %s" % NPM_ENTRY)
        got = installed_version(self.new_dir, "npm")
        if got != self.release.version:
            raise RuntimeError("装出来的版本是 %s，期望 %s" % (got or "未知", self.release.version))
        self.log("校验通过: v%s -> %s" % (got, entry))

    def _swap_in(self) -> None:
        self._check_cancel()
        self.progress(76, "正在切换目录…")
        if os.path.exists(self.target_dir):
            self._rename(self.target_dir, self.old_dir)
            self._had_old = True
        try:
            self._rename(self.new_dir, self.target_dir)
        except OSError:
            if self._had_old:
                self._rename(self.old_dir, self.target_dir)    # put it back
                self._had_old = False
            raise
        # Point the launcher at the new layout. Written only after the rename
        # succeeded, so it can never name a directory that is not there.
        if self.launcher_dir:
            try:
                with open(os.path.join(self.launcher_dir, "harness.txt"), "w",
                          encoding="utf-8") as f:
                    f.write(self.target_dir)
            except OSError as exc:
                self.log("写 harness.txt 失败（继续）: %r" % (exc,))
        self.log("已切换: %s -> %s" % (self.new_dir, self.target_dir))

    # ---- process plumbing -------------------------------------------------
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
                    subprocess.run([_SYS32("taskkill.exe"), "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True, creationflags=_CREATE_NO_WINDOW)
                    raise UpdateCancelled()
        finally:
            proc.stdout.close()
        code = proc.wait()
        if code != 0 and tail:
            self.log("最后输出: %s" % " | ".join(tail))
        return code

    # ---- smoke test -------------------------------------------------------
    def _smoke_test(self) -> None:
        """Start the freshly installed harness and wait for its tokenized URL.

        Installing is not the same as running — a version that bumped its Node
        requirement, or a native module that only exists as a prebuild we chose
        not to run the scripts for, only shows up here. Failing here rolls
        back, which is the whole point of paying for this check.

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
        self.progress(86, "正在试运行新版本…", indeterminate=True)
        try:
            started = self.start_backend()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("新版本启动失败：%s" % exc) from exc
        if not started:
            self.log("!! 端口上已有服务在监听，新的后端没有被启动，试运行无法进行")
            self.log("!! 这次更新没有验证新版本能否启动，请更新完点一次「启动」确认")
            self.smoke = "skipped"
            self.progress(94, "端口被占用，已跳过试运行")
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
        self.progress(95, "试运行通过")

    # ---- finish / rollback ------------------------------------------------
    def _finalize(self, t0: float) -> None:
        self.progress(96, "正在收尾…")
        if self._had_old:
            _rmtree(self.old_dir)
            if os.path.exists(self.old_dir):
                # A file was still held open by something (a scanner, an
                # editor). Dead weight, not breakage — say so honestly.
                self.log("旧版本目录没能删干净，可以手工删除 %s" % self.old_dir)
            else:
                self.log("已清理旧版本目录 %s" % self.old_dir)
        self._write_version_record()
        set_registered_version(self.release.version)
        legacy = legacy_repo_dir(self.install_dir)
        if legacy and self.mode != "npm":
            # Deliberately not sized: measuring a 2 GB node_modules tree means
            # walking hundreds of thousands of files, which would stall the
            # last step of the update for minutes on the one machine that has
            # one. The path is the actionable part.
            self.log("旧的源码目录 %s 已经用不上了，可以删除腾出空间" % legacy)
            self.emit("legacy", path=legacy)
        self.progress(100, "完成，用时 %.1f 分钟" % ((time.time() - t0) / 60.0))
        self.log("更新完成，用时 %.1f 分钟" % ((time.time() - t0) / 60.0))

    def _write_version_record(self) -> None:
        path = os.path.join(self.launcher_dir or self.install_dir, "data", "version.json")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"version": self.release.version,
                           "layout": "npm",
                           "installed_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                          f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def _rollback(self, reason: str) -> bool:
        """Put the previous state back, best effort at every step.

        Returns True when the install ends up whole and usable — which includes
        the case where nothing had been moved yet. False only when the restore
        itself failed; then both directories are still on disk and the log says
        which is which.
        """
        self.log("开始回滚（原因: %s）" % reason)
        try:
            if not self._had_old:
                # Nothing was moved aside, so either the swap never happened or
                # this was a fresh npm install onto a source install. Drop the
                # staging tree either way (a no-op once it has been renamed
                # into place), and if the new tree did land, remove it — but
                # never touch the legacy repo\, which is still the user's.
                _rmtree(self.new_dir)
                if os.path.exists(os.path.join(self.target_dir, NPM_ENTRY)) \
                        and self.mode != "npm":
                    self.log("撤销新装的 npm 版本（这台机器原本是源码布局）")
                    _rmtree(self.target_dir)
                current = installed_version(self.harness_dir, self.mode)
                self.log("回滚完成，仍是 v%s" % (current or "之前的版本"))
                return True

            _rmtree(self.new_dir)
            _rmtree(self.target_dir)
            self._rename(self.old_dir, self.target_dir)
            self._had_old = False
            current = installed_version(self.harness_dir, self.mode)
            if not current and self.mode == "npm":
                current = installed_version(self.target_dir, "npm")
            self.log("回滚完成，仍是 v%s" % (current or "之前的版本"))
            return True
        except Exception as exc:  # noqa: BLE001
            self.log("!! 回滚失败: %r" % (exc,))
            self.log("旧版本仍在 %s，新版本在 %s，可按需手工改名"
                     % (self.old_dir, self.target_dir))
            return False


# --------------------------------------------------------------------------
# launcher self-update
# --------------------------------------------------------------------------
@dataclass
class LauncherRelease:
    tag: str            # v1.5.0
    version: str        # 1.5.0
    url: str            # DSHLauncher.exe download URL
    size: int = 0
    published: str = ""
    body: str = ""
    digest: str = ""    # sha256 of the asset, as GitHub reports it

    @property
    def key(self) -> tuple:
        # Launcher tags are plain X.Y.Z (v1.5.0), so the simple parser is the
        # right one here — _version_key sorts prereleases and would not compare
        # against it.
        return _parse_version(self.version)


def _parse_version(text: str) -> tuple:
    nums = []
    for part in re.sub(r"^v", "", text or "").split("."):
        digits = re.match(r"\d+", part)
        nums.append(int(digits.group()) if digits else 0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def list_launcher_releases(proxy: str | None = None, per_page: int = 20) -> list[LauncherRelease]:
    """Releases of this installer, newest first, that actually carry the exe.

    Fetched directly when that works, falling back to `proxy` only if it does
    not. This response carries the digests the download is checked against, so
    fetching it through a proxy would let that proxy vouch for its own bytes.
    A machine whose only route out is the proxy still gets the update; it just
    also gets the weaker guarantee, which the docstring of
    LauncherUpdateWorker spells out.
    """
    url = "%s/repos/%s/releases?per_page=%d" % (API_ROOT, LAUNCHER_SLUG, per_page)
    try:
        data = _get_json(url)
    except RuntimeError:
        if not proxy:
            raise
        data = _get_json(url, proxy=proxy)
    if not isinstance(data, list):
        raise RuntimeError("GitHub 返回了预期之外的数据。")
    out: list[LauncherRelease] = []
    for item in data:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        asset = next((a for a in (item.get("assets") or [])
                      if a.get("name") == LAUNCHER_ASSET), None)
        if asset is None:
            continue
        tag = item.get("tag_name") or ""
        digest = str(asset.get("digest") or "")
        if digest.startswith("sha256:"):
            digest = digest.split(":", 1)[1]
        out.append(LauncherRelease(
            tag=tag,
            version=re.sub(r"^v", "", tag),
            url=asset.get("browser_download_url") or "",
            size=int(asset.get("size") or 0),
            published=(item.get("published_at") or "")[:10],
            body=item.get("body") or "",
            digest=digest,
        ))
    out.sort(key=lambda r: r.key, reverse=True)
    return out


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def newer_launcher(running_version: str,
                   proxy: str | None = None) -> LauncherRelease | None:
    """The newest published launcher, if it is newer than `running_version`.

    Release tags and the launcher's VERSION track each other (v1.5.0 ships
    launcher 1.5.0), so a plain version compare is the whole check.
    """
    running = _parse_version(running_version)
    for release in list_launcher_releases(proxy=proxy):
        if release.url and release.key > running:
            return release
    return None


def download_file(url: str, dest: str, proxy: str | None = None,
                  on_progress: Callable[[float, int, int], None] | None = None,
                  cancel: threading.Event | None = None, tries: int = 3) -> int:
    """Stream a URL to `dest`. Returns bytes written; raises on failure."""
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            return _download_once(url, dest, proxy, on_progress, cancel)
        except UpdateCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < tries:
                time.sleep(2.0 * attempt)
    raise RuntimeError("下载失败：%s" % last)


def _download_once(url: str, dest: str, proxy, on_progress, cancel) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        resp = _opener(proxy).open(req, timeout=60)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(_friendly_net_error(exc)) from exc
    written = 0
    with resp:
        total = int(resp.headers.get("Content-Length") or 0)
        try:
            with open(dest, "wb") as out:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise UpdateCancelled()
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    written += len(chunk)
                    if on_progress is not None:
                        on_progress(written / total if total else 0.0, written, total)
        except Exception:
            try:
                os.remove(dest)
            except OSError:
                pass
            raise
    if written == 0:
        raise RuntimeError("下载到 0 字节")
    return written


class LauncherUpdateWorker(threading.Thread):
    """Swap in a newer DSHLauncher.exe.

    Windows will not let a running image be overwritten, but it does allow it
    to be *renamed* — so the dance is: download next to it, rename the running
    exe aside, move the new one into its place. The caller then restarts; the
    leftover `.old` is deleted on the next launcher start.

    Renaming the running exe is safe while it runs, and if any step fails the
    original is renamed straight back.
    """

    def __init__(self, *, exe_path: str, release: LauncherRelease, events,
                 cancel: threading.Event, proxy: str | None = None,
                 log_path: str | None = None) -> None:
        super().__init__(daemon=True, name="dsh-launcher-update")
        self.exe_path = os.path.abspath(exe_path)
        self.dir = os.path.dirname(self.exe_path)
        self.release = release
        self.events = events
        self.cancel = cancel
        self.proxy = proxy
        self.log_path = log_path or os.path.join(self.dir, "data", "update.log")
        self.staged = os.path.join(self.dir, "DSHLauncher.new.exe")
        self.backup = os.path.join(self.dir, "DSHLauncher.old.exe")

    def emit(self, kind: str, **kw) -> None:
        self.events.put({"kind": kind, **kw})

    def progress(self, pct: float, text: str, indeterminate: bool = False) -> None:
        self.emit("progress", pct=float(pct), text=text, indeterminate=indeterminate)

    def log(self, msg: str) -> None:
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(time.strftime("[%H:%M:%S] ") + msg + "\n")
        except OSError:
            pass

    def run(self) -> None:
        try:
            self._run()
        except UpdateCancelled:
            self.log("启动器更新已取消")
            self.emit("done", ok=False, msg="启动器更新已取消，启动器没有变化。",
                      restart=False)
        except Exception as exc:  # noqa: BLE001
            self.log("!! 启动器更新失败: %r" % (exc,))
            self.emit("done", ok=False, msg="启动器更新失败：%s" % exc, restart=False)
        else:
            self.emit("done", ok=True,
                      msg="启动器已更新到 v%s，需要重启生效。" % self.release.version,
                      restart=True)

    def _run(self) -> None:
        self.log("== 启动器更新 -> v%s ==" % self.release.version)
        self.progress(5, "正在下载启动器 v%s…" % self.release.version)
        try:
            os.remove(self.staged)
        except OSError:
            pass

        def on_progress(frac, got, total):
            self.progress(5 + 70 * frac, "正在下载启动器… %.1f / %.1f MB"
                          % (got / 1048576.0, total / 1048576.0))

        size = download_file(self.release.url, self.staged, proxy=self.proxy,
                             on_progress=on_progress, cancel=self.cancel)
        self.log("下载完成: %.1f MB" % (size / 1048576.0))
        if size < 1_000_000:
            raise RuntimeError("下载到的文件只有 %d 字节，不像是一个启动器" % size)

        # This is the one place the program replaces its own executable, so it
        # is worth checking the bytes are the ones the release declares before
        # that happens. The digest comes from the GitHub API — fetched directly
        # where that route exists, so a proxy cannot vouch for its own bytes.
        if self.release.digest:
            got = sha256_file(self.staged)
            if got != self.release.digest:
                try:
                    os.remove(self.staged)
                except OSError:
                    pass
                raise RuntimeError(
                    "下载下来的面板程序校验不通过（期望 %s…，实际 %s…），已丢弃。"
                    % (self.release.digest[:12], got[:12]))
            self.log("校验通过: sha256 %s" % got)
        else:
            self.log("!! 该发布没有提供校验值，跳过完整性校验")

        self.progress(80, "正在替换…")
        try:
            os.remove(self.backup)
        except OSError:
            pass
        os.replace(self.exe_path, self.backup)
        try:
            os.replace(self.staged, self.exe_path)
        except OSError:
            os.replace(self.backup, self.exe_path)      # put it back, then fail
            raise
        self.log("已替换 %s（旧文件留在 %s，下次启动时清理）"
                 % (self.exe_path, os.path.basename(self.backup)))
        self.progress(100, "完成")


def cleanup_launcher_backup(exe_path: str) -> None:
    """Delete the `.old` left by a previous self-update. Best effort."""
    backup = os.path.join(os.path.dirname(os.path.abspath(exe_path)),
                          "DSHLauncher.old.exe")
    for _ in range(5):
        try:
            os.remove(backup)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.4)          # the old process may still be exiting


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


def _wrap_line(text: str, measure, width: int) -> list[str]:
    """Break one logical line into display lines that fit `width` pixels.

    Tk's own word wrap breaks at spaces only, and Chinese prose has none — a
    whole paragraph is one unbreakable "word", so it lands on its own line and
    strands the bullet marker above it. (Zero-width spaces do not help: Tk
    ignores U+200B.) So the breaks are computed here, character by character,
    preferring the last space when one is close enough to be a real word
    boundary.
    """
    if width <= 0 or measure is None:
        return [text]
    out: list[str] = []
    cur = ""
    cur_w = 0
    for ch in text:
        w = measure(ch)
        if cur and cur_w + w > width:
            space = cur.rfind(" ")
            # Break anywhere for CJK, but never split a Latin word: when the
            # character that did not fit is ASCII, back up to the last space.
            if space >= 0 and (ord(ch) < 128 or not cur[space:].strip()):
                out.append(cur[:space])
                cur = cur[space + 1:]
            else:
                out.append(cur)
                cur = ""
            cur_w = measure(cur)
        cur += ch
        cur_w += w
    out.append(cur)
    return out


def _hanging_prefix(text: str) -> tuple[str, str]:
    """Split a bullet's leading indent from its content, and build the
    continuation indent that lines wrapped text up under the first word."""
    stripped = text.lstrip(" ")
    lead = len(text) - len(stripped)
    if stripped.startswith("• "):
        return text, " " * (lead + 2)
    return text, " " * lead


def insert_markdown(widget, source: str, on_link=None, measure=None,
                    width: int = 0) -> list[tuple[str, str]]:
    """Render `source` into a tk.Text that already has the style tags.

    Passing `measure` + `width` turns on explicit wrapping (see _wrap_line);
    without them Tk wraps on its own, which mishandles CJK prose.

    Returns the (label, url) of every link written, so the caller can wire
    clicks. Tags the caller must define: h1/h2/h3, code, inlinecode, bold,
    bullet, body, quote, rule.
    """
    links: list[tuple[str, str]] = []

    def emit_line(text: str, kind: str, continuation: str = "") -> None:
        pieces = _wrap_line(text, measure, width) if measure else [text]
        for i, piece in enumerate(pieces):
            if i:
                widget.insert("end", continuation, (kind,))
            # The kind tag goes on the text, not just the trailing newline:
            # indents live in lmargin1/lmargin2, which have to be attached to
            # the characters they indent.
            for chunk, url in _inline_pieces(piece):
                if url is None:
                    widget.insert("end", chunk, (kind,))
                    continue
                tag = "link%d" % len(links)
                links.append((chunk, url))
                start = widget.index("end-1c")
                widget.insert("end", chunk, (kind, "linkstyle", tag))
                widget.tag_add(tag, start, "%s+%dc" % (start, len(chunk)))
                widget.tag_bind(tag, "<Button-1>", lambda _e, u=url: on_link and on_link(u))
                widget.tag_bind(tag, "<Enter>",
                                lambda _e: widget.configure(cursor="hand2"))
                widget.tag_bind(tag, "<Leave>", lambda _e: widget.configure(cursor=""))
            widget.insert("end", "\n", (kind,))

    widget.configure(state="normal")
    widget.delete("1.0", "end")
    for kind, text in render_markdown(source):
        if kind == "gap":
            widget.insert("end", "\n")
        elif kind == "rule":
            widget.insert("end", "─" * 42 + "\n", ("rule",))
        elif kind == "code":
            emit_line(text or " ", "code")
        elif kind in ("h1", "h2", "h3"):
            emit_line(text, kind)
        else:
            head, cont = _hanging_prefix(text)
            emit_line(head, kind, cont)
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
