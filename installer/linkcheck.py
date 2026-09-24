#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Can this machine create the directory links dsh needs — and if a run failed, why?

dsh creates its per-profile module fallbacks with `fs.symlinkSync(target, link,
"junction")` (dsh-app-boot `lib/index.js:426`). A junction is a reparse point,
**not** a symbolic link: it needs no SeCreateSymbolicLinkPrivilege, no elevation
and no Developer Mode, and it is what makes dsh installable on an ordinary
unelevated Windows account. Verified on Windows 10 19045 with the same portable
Node the installer ships: on an unelevated, non-Developer-Mode account
`symlinkSync(t, l, "junction")` succeeds while `"dir"` and `"file"` fail with
EPERM/errno -4048.

So the interesting question is never "is this machine elevated" — it is "can it
create a junction inside `%USERPROFILE%\\.dsh` pointing at the install volume".
A machine where even that fails has something else in the way (group policy,
security software hooking node.exe, an unusual volume, a redirected profile),
and no amount of "run as administrator" will change it.

Two pieces:

  probe(...)     runs one short JS snippet with the portable node and reports,
                 per cell, whether `junction` / `symlink-dir` can be created —
                 plus a `mklink /J` reference row made from Python.
  diagnose(...)  pure function: what the failed run wrote + what the probe found
                 -> the lines a support reader needs.

States are tri-valued: OK / FAIL / UNKNOWN. UNKNOWN means *our probe* did not
run (node missing, timeout, no output) and must never be reported as FAIL — the
difference between "this machine cannot create links" and "we could not test it"
is the whole point of the exercise.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time

OK = "ok"
FAIL = "fail"
UNKNOWN = "unknown"

_CREATE_NO_WINDOW = 0x08000000
_SENTINEL = "##DSH-LINKPROBE## "
_PRIMARY = "home_to_install"
_SCRATCH = ".dsh-linkprobe"
PROBE_TIMEOUT = 15.0


def _sys32(name: str) -> str:
    """Absolute path to a Windows system tool (see installer._SYS32)."""
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    return os.path.join(root, "System32", name)


# The whole probe, as a string — nothing is written to disk. A fresh .js in
# %TEMP% that is executed immediately is exactly the shape heuristic AV flags,
# and it would leave an artifact behind on a machine we are already suspicious of.
#
# Paths arrive through `dshprobe=...` argv entries rather than by position:
# process.argv indexing differs between `node -e` and a script file. The prefix
# deliberately has no leading dashes — node rejects anything that looks like an
# option here with "bad option", exit code 9. Output is a single
# sentinel-prefixed JSON line (parsed by the last occurrence, since node may
# print warnings of its own first).
_PROBE_JS = r"""
const fs = require('fs'), path = require('path');
const P = 'dshprobe=';
const cells = [];
for (const a of process.argv) {
  if (a.indexOf(P) !== 0) continue;
  const rest = a.slice(P.length), i = rest.indexOf(':');
  if (i < 0) continue;
  const kind = rest.slice(0, i), val = rest.slice(i + 1);
  if (kind === 'cell') cells.push({ name: val, link: '', target: '' });
  else if (!cells.length) continue;
  else if (kind === 'link') cells[cells.length - 1].link = val;
  else if (kind === 'target') cells[cells.length - 1].target = val;
}
function attempt(fn) {
  try { fn(); return { s: 'ok', errno: 0 }; }
  catch (e) { return { s: 'fail', errno: e.errno || 0, code: e.code || '' }; }
}
function drop(p) {
  try { fs.rmdirSync(p); return; } catch (e) {}
  try { fs.unlinkSync(p); } catch (e) {}
}
const out = { node: process.version.replace(/^v/, ''), cells: {} };
for (const c of cells) {
  const cell = {};
  const j = path.join(c.link, 'probe-' + c.name + '-junction');
  const d = path.join(c.link, 'probe-' + c.name + '-symdir');
  const a = attempt(() => fs.symlinkSync(c.target, j, 'junction'));
  cell.junction = a.s;
  if (a.errno) cell.junction_errno = a.errno;
  // A junction that reports success but does not resolve is not usable either.
  if (a.s === 'ok') {
    try { fs.readdirSync(j); }
    catch (e) { cell.junction = 'fail'; cell.junction_note = 'created-but-unreadable'; }
  }
  const b = attempt(() => fs.symlinkSync(c.target, d, 'dir'));
  cell.symlink_dir = b.s;
  if (b.errno) cell.symlink_dir_errno = b.errno;
  drop(j); drop(d);
  out.cells[c.name] = cell;
}
console.log('##DSH-LINKPROBE## ' + JSON.stringify(out));
"""


# --------------------------------------------------------------------------
# the probe
# --------------------------------------------------------------------------
def existing_ancestor(path: str) -> str:
    """Nearest directory that already exists, so a diagnostic never has to
    create the install directory (or anything else the user did not ask for)."""
    p = os.path.abspath(path)
    while not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            return p
        p = parent
    return p


def drive_of(path: str) -> str:
    """The volume a path sits on: `D:`, or `\\\\server\\share` for a UNC path."""
    p = os.path.abspath(path)
    if p.startswith("\\\\"):
        parts = [x for x in p.split("\\") if x]
        return "\\\\" + "\\".join(parts[:2]) if len(parts) >= 2 else "\\\\"
    return os.path.splitdrive(p)[0].upper()


def volume_facts(target: str, home: str | None = None) -> dict:
    """Which volumes are in play, and whether home looks redirected.

    A UNC `%USERPROFILE%` is the profile-redirection signature and needs no
    Win32 call — the string says it. Deliberately no filesystem-type query:
    it can contradict what the probe actually measured, and the probe is the
    better witness.
    """
    home = home or os.environ.get("USERPROFILE") or os.path.expanduser("~")
    tmp = os.environ.get("TEMP") or os.environ.get("TMP") or r"C:\Windows\Temp"
    install, home_drive, tmp_drive = (drive_of(target), drive_of(home), drive_of(tmp))
    return {"install": install, "home": home_drive, "tmp": tmp_drive,
            "same_as_home": install == home_drive,
            "home_is_unc": home_drive.startswith("\\\\")}


def cells_for(target: str, home: str | None = None) -> list[dict]:
    """Where to test: a 2x2 of link location against target location.

    Reading the matrix is what attributes a failure. Vary one axis and hold the
    other, and each cause gets its own signature:

      link in .dsh  ->  install volume   the link dsh actually makes (the judge)
      link in .dsh  ->  .dsh             link side fixed, target known local
      link in TEMP  ->  install volume   target side, link known local
      link in TEMP  ->  TEMP             machine-level control

    `tmp_to_install` reuses the primary cell's target *verbatim*, so the two
    differ by link location alone — otherwise a target difference would be
    confounded with the link difference and neither could be blamed.

    Order matters only for index 0: `probe` uses `cells[0]` for the mklink
    reference row and `probe_mklink_only` slices `[:1]`.
    """
    home = home or os.environ.get("USERPROFILE") or os.path.expanduser("~")
    dsh_home = os.path.join(home, ".dsh")
    tmp = os.environ.get("TEMP") or os.environ.get("TMP") or r"C:\Windows\Temp"
    scratch = os.path.join(existing_ancestor(target), _SCRATCH)
    install_src = scratch + "-src"
    return [
        {"name": _PRIMARY, "link": dsh_home, "target": install_src},
        {"name": "home_to_home", "link": dsh_home, "target": os.path.join(dsh_home, _SCRATCH + "-src")},
        {"name": "tmp_to_install", "link": os.path.join(tmp, _SCRATCH), "target": install_src},
        {"name": "tmp_to_tmp", "link": os.path.join(tmp, _SCRATCH), "target": os.path.join(tmp, _SCRATCH, "src")},
    ]


def _prepare(cells: list[dict]) -> None:
    for c in cells:
        os.makedirs(c["link"], exist_ok=True)
        os.makedirs(c["target"], exist_ok=True)


def _matching_scratch(name: str) -> bool:
    return name == _SCRATCH or name.startswith(_SCRATCH + "-") or name.startswith(_SCRATCH + ".")


def _cleanup(cells: list[dict]) -> None:
    """Drop links first — os.rmdir on a junction removes the reparse point, not
    the target — so a stray rmtree can never walk into the target through it."""
    for c in cells:
        for name in ("probe-%s-junction" % c["name"], "probe-%s-symdir" % c["name"],
                     "probe-%s-mklink" % c["name"]):
            p = os.path.join(c["link"], name)
            try:
                os.rmdir(p)
                continue
            except OSError:
                pass
            try:
                os.remove(p)
            except OSError:
                pass
        for d in (c["target"], c["link"]):
            # Never touch the user's real %USERPROFILE%\.dsh — only our scratch.
            if _matching_scratch(os.path.basename(d)):
                shutil.rmtree(d, ignore_errors=True)


def _kill(proc: subprocess.Popen) -> None:
    try:
        subprocess.run([_sys32("taskkill.exe"), "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, creationflags=_CREATE_NO_WINDOW)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass


def _run_node(node_exe: str, cells: list[dict], timeout: float,
              cancel=None) -> tuple[str, str, str]:
    """-> (status, reason, stdout); status is ran / unavailable / cancelled."""
    args = [node_exe, "-e", _PROBE_JS]
    for c in cells:
        args += ["dshprobe=cell:%s" % c["name"],
                 "dshprobe=link:%s" % c["link"],
                 "dshprobe=target:%s" % c["target"]]
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, shell=False,
                                creationflags=_CREATE_NO_WINDOW)
    except OSError as exc:
        return "unavailable", "spawn failed: %s" % exc, ""
    deadline = time.time() + timeout
    while True:
        try:
            out, _ = proc.communicate(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                _kill(proc)
                proc.communicate()
                return "cancelled", "cancelled", ""
            if time.time() > deadline:
                _kill(proc)
                proc.communicate()
                return "unavailable", "timed out after %.0fs" % timeout, ""
    text = (out or b"").decode("utf-8", "replace")
    if proc.returncode != 0:
        return "unavailable", "node exited %s" % proc.returncode, text
    return "ran", "", text


def _mklink_probe(cell: dict, timeout: float = 10.0) -> str:
    """Reference row: does cmd's `mklink /J` work where node's junction does not?

    Advisory only, and deliberately never FAIL. It is a shell command, so a path
    containing `&` can be mis-parsed by cmd; the link is verified functionally (a
    marker file has to be visible through it) and anything short of proof is
    UNKNOWN.
    """
    cmd = _sys32("cmd.exe")
    link = os.path.join(cell["link"], "probe-%s-mklink" % cell["name"])
    try:
        subprocess.run([cmd, "/c", "mklink", "/J", link, cell["target"]],
                       capture_output=True, timeout=timeout,
                       creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN
    marker = os.path.join(cell["target"], "mklink-marker")
    state = UNKNOWN
    try:
        with open(marker, "w", encoding="utf-8") as f:
            f.write("ok")
        state = OK if os.path.exists(os.path.join(link, "mklink-marker")) else UNKNOWN
    except OSError:
        pass
    try:
        os.remove(marker)
    except OSError:
        pass
    try:
        os.rmdir(link)
    except OSError:
        pass
    return state


def probe_mklink_only(target: str, home: str | None = None) -> str:
    """The one check that does not need node — for `--diag` on a machine with no
    runtime extracted. OS-level and advisory: it cannot see node's own path."""
    cells = cells_for(target, home)[:1]
    try:
        _prepare(cells)
    except OSError:
        return UNKNOWN
    try:
        return _mklink_probe(cells[0])
    finally:
        _cleanup(cells)


def probe(node_exe: str, target: str, *, home: str | None = None,
          timeout: float = PROBE_TIMEOUT, cancel=None) -> dict:
    """One-stop capability check. Never raises: failures come back as a status."""
    cells = cells_for(target, home)
    report: dict = {
        "status": "unavailable", "reason": "", "node": "", "cells": {},
        "home": cells[0]["link"], "mklink_j": UNKNOWN,
        "volumes": volume_facts(target, home),
    }
    if not node_exe or not os.path.exists(node_exe):
        report["reason"] = "portable node.exe not found"
        return report
    try:
        _prepare(cells)
    except OSError as exc:
        report["reason"] = "cannot create probe directories: %s" % exc
        return report
    try:
        status, reason, text = _run_node(node_exe, cells, timeout, cancel)
        report["status"], report["reason"] = status, reason
        if status != "ran":
            return report
        line = ""
        for candidate in text.splitlines():
            if candidate.startswith(_SENTINEL):
                line = candidate[len(_SENTINEL):]
        if not line:
            report["status"] = "unavailable"
            report["reason"] = "probe produced no result line"
            return report
        try:
            parsed = json.loads(line)
        except ValueError:
            report["status"] = "unavailable"
            report["reason"] = "probe result was not valid JSON"
            return report
        report["node"] = parsed.get("node", "")
        report["cells"] = parsed.get("cells", {})
        report["mklink_j"] = _mklink_probe(cells[0])
        return report
    finally:
        _cleanup(cells)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
def cell_state(report: dict, name: str, key: str = "junction") -> str:
    cell = (report.get("cells") or {}).get(name) or {}
    return cell.get(key) or UNKNOWN


def render(report: dict) -> str:
    """The one line worth grepping a year from now.

    The failure this whole module exists for reads:
      links: home_to_install-junction=FAIL(-4048) mklink-j=ok node=24.18.0 ...
    """
    if report.get("status") == "cancelled":
        return "links: probe cancelled"
    if report.get("status") != "ran":
        return "links: UNKNOWN (probe did not run: %s)" % (report.get("reason") or "?")

    def fmt(state: str, errno, note: str = "") -> str:
        detail = [str(x) for x in (errno,) if x] + ([note] if note else [])
        if state == OK:
            return "ok" + ("(%s)" % ", ".join(detail) if detail else "")
        return state.upper() + ("(%s)" % ", ".join(detail) if detail else "")

    bits = []
    for name, cell in (report.get("cells") or {}).items():
        bits.append("%s-junction=%s" % (name, fmt(cell.get("junction") or UNKNOWN,
                                                  cell.get("junction_errno", 0),
                                                  cell.get("junction_note") or "")))
        bits.append("%s-symlink-dir=%s" % (name, fmt(cell.get("symlink_dir") or UNKNOWN,
                                                    cell.get("symlink_dir_errno", 0))))
    bits.append("mklink-j=%s" % report.get("mklink_j", UNKNOWN))
    vol = report.get("volumes") or {}
    if vol:
        bits.append("vol=install:%s/home:%s/tmp:%s"
                    % (vol.get("install") or "?", vol.get("home") or "?", vol.get("tmp") or "?"))
    bits.append("node=%s" % (report.get("node") or "?"))
    return "links: " + " ".join(bits)


def link_matrix(report: dict) -> str:
    """The same findings for a human: link location against target location."""
    vol = report.get("volumes") or {}
    pairs = [("home_to_install", ".dsh→安装卷"), ("home_to_home", ".dsh→.dsh"),
             ("tmp_to_install", "TEMP→安装卷"), ("tmp_to_tmp", "TEMP→TEMP")]
    bits = ["%s=%s" % (label, cell_state(report, name))
            for name, label in pairs if cell_state(report, name) != UNKNOWN]
    if vol:
        bits.append("安装卷=%s home卷=%s TEMP卷=%s"
                    % (vol.get("install") or "?", vol.get("home") or "?", vol.get("tmp") or "?"))
    return "  ".join(bits)


# --------------------------------------------------------------------------
# attribution: which of the three causes, and what to do about it
# --------------------------------------------------------------------------
HOME_DISPLAY = r"%USERPROFILE%\.dsh"
# Deliberately does not mention DSH_HOME: this build resolves the harness home
# from USERPROFILE only, so pointing at a setting it cannot honour would send
# people down a road with no end.
HOME_RELOCATE_ADVICE = ("需要把这个用户目录放回本地盘 —— 取消 profile 重定向"
                        "（通常由域策略或 OneDrive 的「已知文件夹移动」造成）。")


def verdict(report: dict | None) -> tuple[str, str] | None:
    """(cause, one-line remedy) for a failed probe, or None when it is fine.

    The cells vary one axis at a time, so each cause has its own signature:

      H fail + T fail                     nothing can be created anywhere
      H fail + T ok                       the .dsh location is the problem
      H ok + T ok + X fail                the install volume/path is the problem
      H ok + T ok + X ok but P fail       each side alone works, together not
      anything else (a needed cell unknown)  report the matrix, claim nothing
    """
    if not report or report.get("status") != "ran":
        return None
    primary = cell_state(report, _PRIMARY)
    if primary == OK:
        return None
    home_cell = cell_state(report, "home_to_home")
    tmp_cell = cell_state(report, "tmp_to_tmp")
    install_cell = cell_state(report, "tmp_to_install")
    vol = report.get("volumes") or {}
    install_drive = vol.get("install") or "安装盘"

    if home_cell == FAIL and tmp_cell == FAIL:
        # Both link locations fail, so the install directory is not implicated:
        # dsh creates these links inside .dsh, wherever the install lives.
        # Sending anyone to "try another install directory" here would be
        # advice that cannot work.
        return ("machine",
                "这台机器在哪儿都建不了目录链接（`.dsh` 里和 TEMP 里都失败）——这不是「权限不够」，"
                "junction 本来就不需要权限，而是有东西在拦：组策略「本地安全策略 → 用户权限分配 → "
                "创建符号链接」是否被清空，或安全软件是否拦了 `runtime\\node.exe`。"
                "**用管理员身份运行解决不了这个问题**；先临时退出安全软件再试一次。")
    if home_cell == FAIL and tmp_cell == OK:
        where = ("`%USERPROFILE%` 是网络路径（profile 被重定向）"
                 if vol.get("home_is_unc") else
                 "`%USERPROFILE%` 这一侧的位置/卷不支持重解析点")
        return ("home",
                "机器本身能建链接（TEMP 里成功），问题只在 %s 这个位置：%s —— %s"
                % (HOME_DISPLAY, where, HOME_RELOCATE_ADVICE))
    if home_cell == OK and tmp_cell == OK and install_cell == FAIL:
        return ("install",
                "链接位置没问题，问题在**安装目录这一侧**：`%s` 这个卷或路径放不了重解析点"
                "（exFAT/FAT32 不支持，网络盘/映射盘也常常不行）。"
                "**换一个本地 NTFS 盘上的普通目录**（例如 `D:\\DSH`）再点「重新检查」。" % install_drive)
    if home_cell == OK and tmp_cell == OK and install_cell == OK:
        return ("combination",
                "`.dsh` 和安装目录**单独**都能建链接，组合起来不行 —— 多半与通往安装目录的这条路径"
                "有关（映射盘、挂载点、符号链接过的父目录）。先换一个别的盘上的普通目录试。")
    return ("inconclusive",
            "有几项没测出来，只能给出矩阵、不能断言原因。换一个本地 NTFS 盘上的普通目录再试一次；"
            "仍然失败就把 `install.log` 发给我们。")


def admin_suggestion(smoke_text: str | None, report: dict | None, *,
                     elevated: bool) -> str | None:
    """Whether "right-click → run as administrator" is worth suggesting.

    Only for failures that elevation can actually change. Saying it next to a
    junction failure would contradict the diagnosis printed three lines above it
    (junctions need no privilege), and suggesting it for a network or disk
    error is just noise. Already running elevated → nothing to suggest.
    """
    if elevated:
        return None
    report = report or {}
    text = smoke_text or ""
    low = text.lower()
    # A failed primary link cell means the verdict above already told the user
    # elevation does not apply (junctions need no privilege). Read the fact, not
    # the wording, so the two lines cannot contradict each other.
    if report.get("status") == "ran" and cell_state(report, _PRIMARY) == FAIL:
        return None
    if any(h in text for h in _NET_HINTS) or "ENOSPC" in text or "no space" in low:
        return None
    return ("也可以右键安装包 →「以管理员身份运行」再装一次"
            "（只在权限类失败上有效；上面已写明原因时按上面的来）。")


def blocking_message(report: dict) -> str | None:
    """Why the install cannot work on this machine — or None.

    Only the primary cell decides: it is the link dsh itself creates (and the
    one dsh will need at runtime). A fail in another cell is worth logging, not
    worth stopping for — a machine with an odd %TEMP% can still run dsh fine.
    UNKNOWN never blocks. The other cells choose the *wording*, never the
    decision.
    """
    if report.get("status") != "ran" or cell_state(report, _PRIMARY) != FAIL:
        return None
    found = verdict(report)
    cause, advice = found if found else ("inconclusive", "")
    head = ("预检的网络和磁盘都通过了，但链接这一步过不去"
            "（免特权的 junction 也不行，这一步本来不需要管理员权限）。\n")
    return head + advice


# --------------------------------------------------------------------------
# diagnosis (pure: no filesystem, no subprocess — unit-tested)
# --------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"(token=)[A-Za-z0-9._\-]+")
_MAX_LINES = 40
_MAX_CHARS = 240
_ERRNO_EPERM = "-4048"
_NET_HINTS = ("ETIMEDOUT", "ENOTFOUND", "EAI_AGAIN", "ECONNREFUSED", "ECONNRESET",
              "npm ERR!", "ERR_SOCKET_TIMEOUT", "UNABLE_TO_GET_ISSUER")


def redact(text: str) -> str:
    """dsh prints its one-time login URL; a log users send us must not carry it."""
    return _TOKEN_RE.sub(r"\1<redacted>", text or "")


def _excerpt(text: str, limit: int = 10) -> list[str]:
    lines = [l.rstrip() for l in (text or "").splitlines() if l.strip()]
    if len(lines) <= limit:
        return lines
    return lines[:limit] + ["…（以下省略 %d 行）" % (len(lines) - limit)]


def diagnose(smoke_text: str | None, report: dict | None, *, error: str = "",
             step: str = "", target: str = "", harness_version: str = "",
             smoke_exists: bool = False) -> list[str]:
    """Turn a failed run into lines a human can act on. First match wins."""
    report = report or {}
    text = smoke_text or ""
    low = text.lower()
    said: list[str] = []

    eperm_symlink = "EPERM" in text and "symlink" in low and _ERRNO_EPERM in text
    junction = cell_state(report, _PRIMARY)
    mklink = report.get("mklink_j") or UNKNOWN
    found = verdict(report)
    cause, advice = found if found else ("", "")

    if not text.strip():
        # _smoke_test deletes smoke.log on success, so an empty one means the
        # child produced nothing at all — that is not a link story. `error`
        # separates "it exited immediately" from "it hung for 120 seconds".
        hung = "令牌" in error or "120" in error
        said = [
            ("试运行 120 秒内没有任何输出（进程一直没起来）" if hung
             else "试运行进程没有任何输出就退出了")
            + ("（smoke.log 为空）" if smoke_exists else "（smoke.log 没生成）"),
            "最可能是安全软件直接结束了 node.exe，或进程根本没被启动起来。",
            "建议：把安装目录和 %USERPROFILE%\\.dsh 加入杀软白名单后重试；"
            "也可以先手动跑一次 runtime\\node.exe --version 看它起不起得来。",
        ]
    elif mklink == OK and junction == FAIL and cause != "machine":
        # Narrower than the next rule, so it comes first: it tells the
        # difference between "this machine cannot make reparse points at all"
        # and "something is watching node.exe specifically".
        said = [
            "cmd 的 mklink /J 能建、node 的 junction 建不了 —— 有东西专门拦 node.exe。",
            "建议：看安全软件/EDR 的日志，把 runtime\\node.exe 加白。",
        ]
    elif cause and junction == FAIL:
        # One source of truth for the link story: the same verdict the install
        # abort and the panel show, so the two can never disagree.
        said = [line for line in advice.split("\n") if line.strip()]
    elif eperm_symlink and junction == OK:
        said = [
            "EPERM(-4048) 出现在 symlink 上，但同一台机器在别处能建 junction —— 通用链接能力没问题，",
            "可疑的是出问题的这个位置：profile 被 OneDrive/已知文件夹重定向、%USERPROFILE%\\.dsh 落在",
            "网络或可移动卷上，或链接位置上已经有同名文件挡着。",
        ]
    elif "EPERM" in text or "EACCES" in text:
        said = [
            "失败是访问被拒（EPERM/EACCES），但不在 symlink 上 —— 更像杀软拦截，或 %USERPROFILE%\\.dsh 不可写。",
        ]
    elif any(h in text for h in _NET_HINTS):
        said = ["失败在网络上（与目录链接无关）。对照上面的预检网络/代理两行排查，改好后重试。"]
    elif "ENOSPC" in text or "no space" in low:
        said = ["磁盘空间不足，腾出空间后重试。"]
    elif "node.exe" in text and ("spawn" in low or "ENOENT" in text):
        said = ["找不到或起不来 node.exe：运行时可能被杀软隔离了，检查 runtime 目录。"]

    out: list[str] = []
    out.append("判断: " + (said[0] if said else "没有匹配到已知模式，下面是原始输出。"))
    out.extend("      " + v for v in said[1:])
    out.append("本机链接能力: " + render(report))
    if cause:
        out.append("链接形状: " + link_matrix(report))
    if step:
        out.append("失败步骤: %s" % step)
    if harness_version and harness_version != "unknown":
        out.append("已装好的内容: harness v%s -> %s（未删除；重跑会复用，不会重下 600 MB）"
                   % (harness_version, os.path.join(target or "", "harness")))
    if smoke_exists:
        out.append("smoke.log 含登录令牌，只发 install.log 就够了。")
    if text.strip():
        out.append("试运行的原始输出（前几行）:")
        out.extend("  " + l for l in _excerpt(text, 10 if verdict else 20))
    return [l[:_MAX_CHARS] for l in out[:_MAX_LINES]]
