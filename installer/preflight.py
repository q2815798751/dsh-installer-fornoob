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

OK, WARN, FAIL = "ok", "warn", "fail"

# The npm registry is the one host the install genuinely cannot do without:
# `pnpm install` pulls every dependency from it, and corepack fetches pnpm
# itself from the same place. Everything else is optional.
REGISTRY_URL = "https://registry.npmjs.org/pnpm"

# Measured on a complete install (repo + node_modules + build output); the
# requirement leaves room for the pnpm store, which lives on the same drive by
# default and roughly doubles the on-disk cost.
REQUIRED_FREE_GB = 8.0
# `build:lib:host` runs tsc with --max-old-space-size=4096.
REQUIRED_RAM_GB = 6.0
# Windows MAX_PATH is 260 unless the machine opts into long paths. pnpm nests
# deep enough that the two can collide.
PATH_BUDGET = 150

WEB_PORT = 3080
SINGLETON_PORT = 3199

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
        out = subprocess.run(["reg", "query", key, "/v", name],
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


def probe(url: str, proxy: str | None = None, timeout: float = 10.0) -> tuple[bool, str]:
    """Fetch `url`, optionally through `proxy`. Returns (reachable, detail).

    A real request rather than a TCP connect: it is the only way to catch a
    proxy or captive portal that accepts the connection and then blackholes
    it, which is exactly the failure that surfaces as a pnpm error later.
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
    opener = urllib.request.build_opener(*handlers)
    started = time.time()
    try:
        with opener.open(url, timeout=timeout) as resp:  # noqa: S310
            resp.read(64)
            elapsed = time.time() - started
            return True, "连通 (%.1fs)" % elapsed
    except urllib.error.HTTPError as exc:
        # Reached the server and it answered - that is a working route.
        return True, "连通 (HTTP %d)" % exc.code
    except Exception as exc:  # noqa: BLE001
        return False, _friendly_net_error(exc)


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
        c.hint = "依赖与构建产物约需 4~5 GB，另需同等空间给 pnpm 缓存。"
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
    if len(target) > PATH_BUDGET:
        c.status = WARN
        c.detail = "可写，但路径偏长 (%d 字符)" % len(target)
        c.hint = "路径过长可能在安装依赖时失败，建议换一个更短的目录。"
    return c


def _check_long_paths() -> Check:
    c = Check("long_paths", "长路径支持")
    value = _reg_query(r"HKLM\SYSTEM\CurrentControlSet\Control\FileSystem", "LongPathsEnabled")
    if value is None:
        c.status, c.detail = WARN, "未启用"
        c.hint = "pnpm 的依赖目录很深，偶尔会超出 Windows 260 字符上限。"
        return c
    if value.strip() in ("0", "0x0"):
        c.status, c.detail = WARN, "未启用"
        c.hint = "pnpm 的依赖目录很深，偶尔会超出 Windows 260 字符上限。"
        return c
    c.detail = "已启用"
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
        c.hint = "可能是旧版本的 DeepSeek Harness 还在运行；先运行安装目录里的 uninstall.bat 或重启电脑。"
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
def run(target: str, report=None, timeout: float = 10.0) -> Preflight:
    """Run every check against `target`.

    `report(check)` is called as each check settles so a UI can stream
    results; it must not raise.
    """
    result = Preflight()

    def add(check: Check) -> None:
        result.checks.append(check)
        if report is not None:
            try:
                report(check)
            except Exception:
                pass

    add(_check_platform())
    add(_check_disk(target))
    add(_check_target(target))
    add(_check_long_paths())
    add(_check_memory())

    direct, proxy_check, proxy = _check_network(timeout=timeout)
    add(direct)
    add(proxy_check)
    result.proxy = proxy

    add(_check_ports())
    add(_check_existing())
    add(_check_proxy_env())
    return result


def summary(result: Preflight) -> str:
    """One-line verdict for the wizard footer."""
    if result.ok:
        return "环境检查通过，可以开始安装。"
    return "发现 %d 项问题，需要先解决。" % len(result.blockers)
