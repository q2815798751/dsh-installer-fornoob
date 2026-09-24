#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pre-install environment checks for DSH Setup.

Runs before anything is written to the target directory: the wizard reports
what it found and the user decides whether to go ahead. The point is that a
failure here is cheap and legible, while the same failure twenty minutes into
`pnpm install` is neither.

Two levels:

  fatal  - the install cannot succeed; the wizard refuses to continue and
           offers a re-check. Keep this list short and provable.
  warn   - the install will probably work but something deserves attention.

The network probe is the interesting one. `pnpm` reads proxies from the
environment and from `.npmrc`, never from the Windows "Internet Options"
proxy that most Chinese users actually configure (Clash, v2ray, ...). A
machine whose only route out is that proxy therefore fails with what looks
like a random network error. So we probe the registry directly, and when the
direct route is unusable but the proxy works we hand the proxy back to the
installer to pass to pnpm.
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

def _SYS32(name: str) -> str:
    """Absolute path to a Windows system tool.

    Bare names resolve through PATH, so a directory earlier in PATH wins — a
    trivial way to make this program execute somebody else's taskkill.exe.
    Nothing here needs that risk; the path is always the same.
    """
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    return os.path.join(root, "System32", name)




OK, WARN, FAIL = "ok", "warn", "fail"

# The npm registry is the one host the install genuinely cannot do without:
# the whole harness is installed from it. Everything else is optional.
REGISTRY_URL = "https://registry.npmjs.org/@deepseek-ai%2Fdsh"

# Measured on a complete install of the published package: 486 packages, about
# 600 MB on disk. The requirement leaves room for npm's cache during the
# install, which lives on the same drive by default.
REQUIRED_FREE_GB = 2.5
# `build:lib:host` runs tsc with --max-old-space-size=4096.
REQUIRED_RAM_GB = 4.0
# Windows MAX_PATH is 260 unless the machine opts into long paths. Measured
# against a complete install: the deepest file in the dependency tree sits 215
# characters below the install root (an AWS SDK submodule's .d.ts), so the
# install directory's own length is what decides whether this collides.
# Node and pnpm use \\?\ prefixes internally and usually cope anyway, which is
# why this warns rather than blocks.
DEPENDENCY_PATH_TAIL = 215
MAX_PATH = 260

WEB_PORT = 3080
# The launcher's single-instance port (launcher.pyw). Not the installer's own
# 3199: preflight runs *before* the installer claims its singleton, so probing
# that one only ever reports on ourselves.
SINGLETON_PORT = 3099

_CREATE_NO_WINDOW = 0x08000000


@dataclass
class Check:
    """One reported finding."""
    key: str
    label: str
    status: str = OK
    detail: str = ""
    hint: str = ""

    @property
    def fatal(self) -> bool:
        return self.status == FAIL


@dataclass
class Preflight:
    """Everything the checks learned, plus what the installer needs from them."""
    checks: list[Check] = None          # type: ignore[assignment]
    proxy: str | None = None            # set when only the proxy route works

    def __post_init__(self) -> None:
        if self.checks is None:
            self.checks = []

    @property
    def blockers(self) -> list[Check]:
        return [c for c in self.checks if c.fatal]

    @property
    def ok(self) -> bool:
        return not self.blockers


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _free_gb(path: str) -> float:
    probe = path
    while probe and not os.path.isdir(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        return shutil.disk_usage(probe or os.path.abspath(os.sep)).free / 1073741824.0
    except OSError:
        return -1.0


def _total_ram_gb() -> float:
    try:
        class _MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return stat.ullTotalPhys / 1073741824.0
    except Exception:
        pass
    return -1.0


def _reg_query(key: str, name: str) -> str | None:
    try:
        out = subprocess.run([_SYS32("reg.exe"), "query", key, "/v", name],
                             capture_output=True, text=True,
                             creationflags=_CREATE_NO_WINDOW, timeout=15)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].lower() == name.lower():
            return parts[-1]
    return None


def dev_mode_enabled() -> bool:
    """AllowDevelopmentWithoutDevLicense.

    Context only, for the log header: it lets ordinary symlinks be created
    without elevation. dsh does not use symlinks — its profile fallbacks are
    junctions, which need neither — so this is never a reason an install fails.
    """
    value = _reg_query(r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock",
                       "AllowDevelopmentWithoutDevLicense")
    return value is not None and value.strip() not in ("0", "0x0")


def system_proxy() -> str | None:
    """The Windows Internet Options proxy, as `host:port`, when enabled."""
    key = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    if (_reg_query(key, "ProxyEnable") or "0") not in ("1", "0x1"):
        return None
    server = _reg_query(key, "ProxyServer")
    if not server:
        return None
    # "host:port", or a per-scheme list like "http=h:p;https=h:p".
    if "=" in server:
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


def port_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def _opener(proxy: str | None):
    """An opener for `proxy`, or an explicitly direct one.

    `ProxyHandler({})` is not the same as omitting it: it *disables* the
    environment proxies urllib would otherwise pick up, which is what makes
    "direct" mean direct. Same shape as launcher/updater.py's `_opener`.
    """
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": "http://" + proxy,
                                                     "https": "http://" + proxy}))
    else:
        handlers.append(urllib.request.ProxyHandler({}))       # force direct
    # The ssl context belongs on the handler: OpenerDirector.open() takes no
    # `context` argument (only the module-level urlopen does).
    handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    return urllib.request.build_opener(*handlers)


def probe(url: str, proxy: str | None = None, timeout: float = 10.0) -> tuple[bool, str]:
    """Fetch `url`, optionally through `proxy`. Returns (reachable, detail).

    A real request rather than a TCP connect: it is the only way to catch a
    proxy or captive portal that accepts the connection and then blackholes
    it, which is exactly the failure that surfaces as a pnpm error later.
    """
    opener = _opener(proxy)
    started = time.time()
    try:
        with opener.open(url, timeout=timeout) as resp:  # noqa: S310
            resp.read(64)
            elapsed = time.time() - started
            return True, "连通 (%.1fs)" % elapsed
    except urllib.error.HTTPError as exc:
        # Reached the server and it answered - that is a working route.
        # Timed too: a rate-limited GitHub used to report no latency at all.
        return True, "连通 (HTTP %d, %.1fs)" % (exc.code, time.time() - started)
    except Exception as exc:  # noqa: BLE001
        return False, _friendly_net_error(exc)


# ---- GitHub: how far away it is, and how fast it actually is ----------------
# The install itself never touches GitHub — dsh comes from npm. These rows exist
# because the *panel* self-updates from GitHub releases, so they are the early
# warning for "the launcher will never be able to update itself here". That is
# also why they must never FAIL: a firewall'd machine that installs fine from
# npm would be blocked by a red row it cannot do anything about.
GH_API_ROOT = "https://api.github.com"
GH_REPO = "q2815798751/dsh-installer-fornoob"
GH_ASSET = "DSHLauncher.exe"
GH_SAMPLES = 3
GH_SAMPLE_TIMEOUT = 4.0
GH_API_TIMEOUT = 5.0
GH_SPEED_LIMIT = 1024 * 1024
GH_SPEED_TIMEOUT = 5.0
# Tighter than the launcher's 8s: whoever runs DSHSetup cannot act on GitHub
# being slow (nothing here downloads from it), so this row must not cost much.
GH_SPEED_BUDGET = 5.0


def latency_probe(url: str, proxy: str | None = None, *, samples: int = GH_SAMPLES,
                  timeout: float = GH_SAMPLE_TIMEOUT) -> dict:
    """Time a few requests to `url`. Stops at the first failure.

    Three samples because one lies: measured against api.github.com on a working
    machine the totals were 0.72s, 2.71s, 0.83s. A dead route is not sampled
    three times either — that would buy 12 seconds of timeouts for nothing.
    """
    took: list[float] = []
    detail = ""
    route = "proxy" if proxy else "direct"
    for _ in range(max(1, samples)):
        opener = _opener(proxy)
        started = time.time()
        try:
            with opener.open(url, timeout=timeout) as resp:  # noqa: S310
                resp.read(1)
            took.append(time.time() - started)
        except urllib.error.HTTPError as exc:
            took.append(time.time() - started)
            if exc.code == 403 and str(exc.headers.get("X-RateLimit-Remaining")) == "0":
                return {"ok": True, "route": route, "limited": True, "samples": took,
                        "min": min(took), "detail": "接口限流（每小时 60 次已用完）"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "route": route, "samples": took, "min": None,
                    "detail": _friendly_net_error(exc)}
    best = min(took)
    shown = "/".join("%.2f" % x for x in took)
    return {"ok": True, "route": route, "samples": took, "min": best, "limited": False,
            "detail": "最快 %.1fs（%d 次 %s）" % (best, len(took), shown)}


def gh_asset_url(proxy: str | None = None, *, timeout: float = GH_API_TIMEOUT) -> dict | None:
    """The newest release's launcher asset, straight from the API.

    Returns None when there is nothing to download. The URL is taken verbatim —
    it 302s to whichever CDN GitHub is using this month, and a hardcoded host
    would happily report "fine" while the real download fails.
    """
    url = "%s/repos/%s/releases?per_page=5" % (GH_API_ROOT, GH_REPO)
    try:
        with _opener(proxy).open(url, timeout=timeout) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, list):
        return None
    for item in data:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        asset = next((a for a in (item.get("assets") or [])
                      if isinstance(a, dict) and a.get("name") == GH_ASSET), None)
        if asset is None:
            continue
        download = asset.get("browser_download_url") or ""
        if not download:
            continue
        digest = str(asset.get("digest") or "")
        return {"url": download, "size": int(asset.get("size") or 0),
                "digest": digest.split(":", 1)[1] if digest.startswith("sha256:") else digest,
                "tag": item.get("tag_name") or ""}
    return None


def speed_probe(asset: dict, proxy: str | None = None, *,
                limit: int = GH_SPEED_LIMIT, budget: float = GH_SPEED_BUDGET,
                timeout: float = GH_SPEED_TIMEOUT) -> dict:
    """Download up to `limit` bytes through the real asset URL and time it.

    Two caps, both enforced here: the byte count and a wall clock checked
    *inside* the read loop. A socket timeout only fires on a long gap, so a
    connection trickling at 1 KB/s would otherwise hold the page forever.

    A server that ignores Range and answers 200 is not a failure — the first
    megabyte is still a megabyte — so only `ranged` differs.
    """
    req = urllib.request.Request(asset["url"], headers={
        "User-Agent": "DSHSetup-preflight",
        # Without this a decompressing stream makes the byte count meaningless.
        "Accept-Encoding": "identity",
        "Range": "bytes=0-%d" % (limit - 1),
    })
    route = "proxy" if proxy else "direct"
    first = None
    got = 0
    ranged = False
    deadline = None
    try:
        with _opener(proxy).open(req, timeout=timeout) as resp:  # noqa: S310
            ranged = getattr(resp, "status", None) == 206
            while got < limit:
                chunk = resp.read(min(64 * 1024, limit - got))
                if not chunk:
                    break
                if first is None:
                    # The budget bounds the *body*, not the connection: a slow
                    # route can spend the whole allowance just getting here, and
                    # "too slow to answer" is a different report from "gave up
                    # reading". Connection setup is bounded by `timeout`.
                    first = time.time()
                    deadline = first + budget
                got += len(chunk)
                if time.time() > deadline:
                    break
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "route": route, "bytes": got, "seconds": 0.0,
                "mbps": 0.0, "ranged": ranged,
                "detail": _friendly_net_error(exc)}

    if not got or first is None:
        return {"ok": False, "route": route, "bytes": got, "seconds": 0.0,
                "mbps": 0.0, "ranged": ranged,
                "detail": "连上了但限时内没有数据"}
    seconds = max(time.time() - first, 1e-3)
    mbps = got / seconds / 1048576.0
    return {"ok": True, "route": route, "bytes": got, "seconds": seconds,
            "mbps": mbps, "ranged": ranged,
            "detail": "%.1f MB 用时 %.2fs（约 %.1f MB/s）" % (got / 1048576.0, seconds, mbps)}


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


# --------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------
def _check_platform() -> Check:
    c = Check("platform", "操作系统", )
    if not sys.platform.startswith("win"):
        c.status, c.detail = FAIL, "本安装包仅支持 Windows"
        return c
    try:
        ver = sys.getwindowsversion()
    except AttributeError:
        ver = None
    arch = platform.machine().lower()
    if ver is not None and (ver.major, ver.build) < (10, 0):
        c.status = FAIL
        c.detail = "需要 Windows 10 或更高版本 (当前 %d.%d)" % (ver.major, ver.minor)
        return c
    if arch not in ("amd64", "x86_64"):
        c.status = FAIL
        c.detail = "需要 64 位 Windows (当前 %s)" % (arch or "未知")
        return c
    name = "Windows %d %s" % (ver.build, arch) if ver is not None else arch
    c.detail = name
    return c


def _check_disk(target: str) -> Check:
    c = Check("disk", "磁盘空间")
    free = _free_gb(target)
    if free < 0:
        c.status, c.detail = WARN, "无法读取磁盘剩余空间"
        return c
    if free < REQUIRED_FREE_GB:
        c.status = FAIL
        c.detail = "剩余 %.1f GB，需要至少 %.0f GB" % (free, REQUIRED_FREE_GB)
        c.hint = "官方预编译包约 600 MB，另需一点空间给 npm 的缓存。"
        return c
    c.detail = "剩余 %.1f GB" % free
    return c


def _check_target(target: str) -> Check:
    c = Check("target", "安装目录可写")
    try:
        os.makedirs(target, exist_ok=True)
        probe_file = os.path.join(target, ".dsh-write-test")
        with open(probe_file, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe_file)
    except OSError as exc:
        c.status, c.detail = FAIL, "无法写入：%s" % exc
        c.hint = "请换一个目录，或先关闭占用该目录的程序。"
        return c
    c.detail = "可写"
    return c


def _check_long_paths(target: str) -> Check:
    """Report the deepest path this install will create, not just the setting.

    The registry flag alone says little — what matters is whether *this*
    target pushes the dependency tree past MAX_PATH, and the default install
    directory lands within a few characters of it.
    """
    c = Check("long_paths", "长路径支持")
    value = _reg_query(r"HKLM\SYSTEM\CurrentControlSet\Control\FileSystem", "LongPathsEnabled")
    enabled = value is not None and value.strip() not in ("0", "0x0")
    deepest = len(os.path.abspath(target)) + DEPENDENCY_PATH_TAIL
    if enabled:
        c.detail = "已启用（最长路径预计 %d 字符）" % deepest
        return c
    c.detail = "未启用（最长路径预计 %d 字符 / 上限 %d）" % (deepest, MAX_PATH)
    if deepest > MAX_PATH - 10:
        c.hint = ("安装目录再长一点就可能超出 Windows 路径上限，依赖会装不全。"
                  "建议换一个更短的目录，例如 D:\\DSH。")
    else:
        c.hint = "依赖目录很深，如果安装中途报「路径过长」，换一个更短的安装目录再试。"
    return c


def _check_memory() -> Check:
    c = Check("memory", "内存")
    total = _total_ram_gb()
    if total < 0:
        c.status, c.detail = WARN, "无法读取"
        return c
    if total < REQUIRED_RAM_GB:
        c.status = WARN
        c.detail = "共 %.1f GB，建议 %.0f GB 以上" % (total, REQUIRED_RAM_GB)
        c.hint = "构建前端时 Node 最多会申请 4 GB 内存，内存偏小会让安装变慢。"
        return c
    c.detail = "共 %.1f GB" % total
    return c


def _check_network(timeout: float = 10.0) -> tuple[Check, Check, str | None]:
    """Probe direct, then the system proxy if direct fails.

    Returns (direct_check, proxy_check_or_placeholder, proxy_to_use).
    """
    direct = Check("network", "网络连接 (npm 源)")
    direct_ok, direct_detail = probe(REGISTRY_URL, proxy=None, timeout=timeout)
    if direct_ok:
        direct.detail = direct_detail
        placeholder = Check("network_proxy", "代理", OK, "未使用")
        return direct, placeholder, None

    # Direct route is unusable. Before declaring the network broken, try the
    # proxy the user actually configured in Windows.
    proxy = system_proxy()
    proxy_check = Check("network_proxy", "系统代理")
    if not proxy:
        direct.status = FAIL
        direct.detail = direct_detail
        direct.hint = "请检查网线 / Wi-Fi、DNS，或先在浏览器里打开 https://registry.npmjs.org 确认能访问。"
        proxy_check.status, proxy_check.detail = WARN, "系统未配置代理"
        return direct, proxy_check, None

    proxy_ok, proxy_detail = probe(REGISTRY_URL, proxy=proxy, timeout=timeout)
    if proxy_ok:
        direct.status = WARN
        direct.detail = "直连失败 (%s)" % direct_detail
        proxy_check.detail = "%s %s" % (proxy, proxy_detail)
        proxy_check.hint = "安装时会自动走这个代理下载依赖。"
        return direct, proxy_check, proxy
    direct.status = FAIL
    direct.detail = direct_detail
    proxy_check.status = FAIL
    proxy_check.detail = "%s 也不通 (%s)" % (proxy, proxy_detail)
    direct.hint = "直连和代理都不通，请检查网络后再重试。"
    proxy_check.hint = "如果代理软件没开，请先打开它，然后点「重新检查」。"
    return direct, proxy_check, None


def _check_ports() -> Check:
    busy = [str(p) for p in (WEB_PORT, SINGLETON_PORT) if port_in_use(p)]
    c = Check("ports", "端口占用")
    if busy:
        c.status = WARN
        c.detail = "端口 %s 已被占用" % ", ".join(busy)
        c.hint = "可能是旧版本的 DSH 还在运行；先运行安装目录里的 uninstall.bat 或重启电脑。"
        return c
    c.detail = "空闲"
    return c


def _check_existing() -> Check:
    c = Check("existing", "已安装版本")
    version = _reg_query(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSeekHarness",
                         "DisplayVersion")
    if not version:
        c.detail = "未安装"
        return c
    c.status = WARN
    c.detail = "已安装 %s" % version
    c.hint = "继续安装会覆盖旧版本，你的 API Key 与会话记录不受影响。"
    return c


def _check_proxy_env() -> Check:
    c = Check("proxy_env", "代理环境变量")
    found = [k for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY")
             if os.environ.get(k)]
    if found:
        c.detail = "已设置 %s" % ", ".join(found)
        return c
    c.detail = "未设置"
    return c


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------
def _warn_only(check: Check) -> Check:
    """Clamp a diagnostic row to WARN.

    `Preflight.ok` is "no blockers" and the wizard has no override button, so a
    FAIL here would block an install that would have worked. GitHub is not
    needed to install dsh.
    """
    if check.status == FAIL:
        check.status = WARN
    return check


def _check_github(proxy_in: str | None = None, direct_dead: bool = False) -> tuple[Check, Check]:
    """Latency to api.github.com, and the real download speed of the panel asset.

    Neither row can fail the preflight (see `_warn_only`). The speed row is the
    one that matters: on a working machine here the API answered in 0.4s while a
    direct megabyte took 12.2s — latency alone would have called that machine
    healthy.
    """
    api_url = "%s/repos/deepseek-ai/deepseek-harness" % GH_API_ROOT
    api_hint = "不影响安装：dsh 本体从 npm 装，GitHub 只提供更新说明。"
    proxy = None if direct_dead else proxy_in
    if proxy is None:
        proxy = system_proxy()

    # --- latency. Direct first, then whatever proxy this machine has. ---
    api = {"ok": False, "route": "direct", "limited": False,
           "detail": "直连不通，没有可用的系统代理"}
    if not direct_dead:
        api = latency_probe(api_url)
    if not api["ok"] and proxy:
        through = latency_probe(api_url, proxy=proxy)
        if through["ok"]:
            prefix = "直连不通；代理" if not direct_dead else "代理"
            api = dict(through, route="proxy", detail=prefix + through["detail"])
        else:
            api = dict(through, detail="%s；代理也不通" % api["detail"])

    api_check = Check("github", "GitHub 连接 (api.github.com)")
    if api["ok"]:
        api_check.detail = api["detail"]
        if api.get("limited"):
            api_check.status = WARN
            api_check.hint = "等一会儿再点「重新检查」；这不是网络问题。"
        elif api["route"] == "proxy":
            api_check.status = WARN
    else:
        api_check.status, api_check.detail, api_check.hint = WARN, api["detail"], api_hint

    speed_check = Check("github_asset", "GitHub 下载速度 (面板更新用)")
    speed_hint = "不影响安装；只影响启动器以后能不能自更新。"
    if not api["ok"]:
        speed_check.status, speed_check.detail, speed_check.hint = (
            WARN, "GitHub 接口不通，跳过测速", speed_hint)
        return _warn_only(api_check), _warn_only(speed_check)

    # --- the asset route is its own question: the API being reachable says
    # nothing about the CDN the bytes come from (measured: API fine, CDN slow).
    asset = gh_asset_url(proxy if direct_dead else None)
    if asset is None:
        speed_check.status, speed_check.detail, speed_check.hint = (
            WARN, "没有找到可下载的发布资产，已跳过测速", speed_hint)
        return _warn_only(api_check), _warn_only(speed_check)

    # Measure the route the panel will actually take — `system_proxy()` when
    # this machine has one, because that is what the launcher falls back to —
    # and try the other route only when the first is poor. Preferring direct
    # cost 15-20s here and reported a failure on a machine that downloads fine
    # through its proxy; no read budget bounds a handshake.
    preferred = proxy or system_proxy()
    first = speed_probe(asset, proxy=preferred)
    best = first
    lead = "直连" if not preferred else "代理"
    if preferred and (not first["ok"] or first["mbps"] < 0.3):
        direct = speed_probe(asset)          # proxy=None is explicitly direct
        if direct["ok"] and (not first["ok"] or direct["mbps"] > first["mbps"] * 1.5):
            best = direct
            lead = "代理较慢，直连" if first["ok"] else "代理不通；直连"

    if not best["ok"]:
        reason = first.get("detail") or "未知"
        speed_check.status, speed_check.detail, speed_check.hint = (
            WARN, "测速失败：%s" % reason, speed_hint)
        return _warn_only(api_check), _warn_only(speed_check)

    speed_check.detail = lead + best["detail"]
    if best["route"] == "proxy":
        speed_check.detail += "（走 %s）" % preferred
        speed_check.status = WARN
        if lead == "代理":
            speed_check.hint = "更新面板时会自动走这个代理。"
    if not best["ranged"]:
        speed_check.detail += "（服务器未按区间返回，只取了前 1 MB）"
    if best["mbps"] < 0.3:
        speed_check.status = WARN
        speed_check.detail += "——面板约 12 MB，预计要 1 分钟以上"
        speed_check.hint = "不影响 dsh 本体的安装，只影响面板自更新。"
    return _warn_only(api_check), _warn_only(speed_check)


def run(target: str, report=None, timeout: float = 10.0, note=None) -> Preflight:
    """Run every check against `target`.

    `report(check)` is called as each check settles so a UI can stream results;
    it must not raise. `note(text)` is for the long checks — a row that takes
    seconds would otherwise leave the UI frozen on the last count.
    """
    result = Preflight()

    def add(check: Check) -> None:
        result.checks.append(check)
        if report is not None:
            try:
                report(check)
            except Exception:
                pass

    def say(text: str) -> None:
        if note is not None:
            try:
                note(text)
            except Exception:
                pass

    add(_check_platform())
    add(_check_disk(target))
    add(_check_target(target))
    add(_check_long_paths(target))
    add(_check_memory())

    direct, proxy_check, proxy = _check_network(timeout=timeout)
    add(direct)
    add(proxy_check)
    result.proxy = proxy

    say("正在测 GitHub 连接与下载速度（慢的话要十几秒）…")
    for check in _check_github(proxy, direct_dead=direct.status == FAIL):
        add(check)

    add(_check_ports())
    add(_check_existing())
    add(_check_proxy_env())
    return result


def summary(result: Preflight) -> str:
    """One-line verdict for the wizard footer."""
    if result.ok:
        return "环境检查通过，可以开始安装。"
    return "发现 %d 项问题，需要先解决。" % len(result.blockers)
