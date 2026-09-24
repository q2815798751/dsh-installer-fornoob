#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""updater.py 的回滚自检 —— 合成一个安装目录，一分钟内出结果。

    python launcher/test-updater.py

不联网、不下载：node.exe 用 python.exe 顶替，npm-cli.js 是一个直接造出目标
目录结构的 Python 脚本。测的是这个功能里最容易出错的部分——目录怎么换、
失败怎么退回去、两种布局怎么迁移。六种情况：

  1  npm → npm 正常更新     新版本落地、旧目录清理干净
  2  npm 安装失败           回滚，旧版本原样无损
  3  试运行失败             回滚
  4  下载/安装中取消        回滚
  5  源码布局 → npm 布局    迁移成功（installer 1.4 的老装机走这条）
  6  切换中途失败           回滚（harness 缺失、只剩 harness.old 那种半状态）

合成目录在 launcher/test/updater/（已 gitignore），通过后自动清掉，失败时留
下来给你看。退出码非 0 表示有断言没通过。
"""
from __future__ import annotations

import os
import queue
import shutil
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import updater  # noqa: E402

BASE = os.path.join(HERE, "test", "updater")     # launcher/test/ is gitignored
INSTALL = BASE
HARNESS = os.path.join(BASE, "harness")
LEGACY = os.path.join(BASE, "repo")
RUNTIME = os.path.join(BASE, "runtime")
LAUNCHER_DIR = os.path.join(BASE, "launcher")
NPM_CLI = os.path.join(RUNTIME, "node_modules", "npm", "bin", "npm-cli.js")

TARGET = updater.Release(version="0.1.6-alpha.2", published="2026-09-17")

# The real uninstall registry entry belongs to the user's machine, not a test.
updater.set_registered_version = lambda version: None


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------
_FAKE_NPM = r'''import json, os, sys
args = sys.argv[1:]
if "install" not in args:
    sys.exit(0)
pkg = [a for a in args if a.startswith("@deepseek-ai/dsh@")]
if not pkg:
    print("npm ERR! no package"); sys.exit(1)
version = pkg[0].split("@")[-1]
if os.environ.get("FAKE_NPM_FAIL"):
    print("npm ERR! code ELIFECYCLE")
    print("npm ERR! simulated install failure")
    sys.exit(1)
root = os.path.join("node_modules", "@deepseek-ai", "dsh")
os.makedirs(os.path.join(root, "lib"), exist_ok=True)
with open(os.path.join(root, "lib", "bin.js"), "w") as f:
    f.write("// stub bin for %s\n" % version)
with open(os.path.join(root, "package.json"), "w") as f:
    json.dump({"name": "@deepseek-ai/dsh", "version": version}, f)
print("added 486 packages in 1m")
'''


def fake_runtime() -> None:
    shutil.rmtree(RUNTIME, ignore_errors=True)
    os.makedirs(os.path.dirname(NPM_CLI), exist_ok=True)
    shutil.copy2(sys.executable, os.path.join(RUNTIME, "node.exe"))
    with open(NPM_CLI, "w", encoding="utf-8") as f:
        f.write(_FAKE_NPM)


def npm_layout(root: str, version: str) -> None:
    """Create a plausible npm-installed harness at `root`."""
    pkg = os.path.join(root, "node_modules", "@deepseek-ai", "dsh")
    os.makedirs(os.path.join(pkg, "lib"), exist_ok=True)
    with open(os.path.join(pkg, "lib", "bin.js"), "w") as f:
        f.write("// bin %s\n" % version)
    with open(os.path.join(pkg, "package.json"), "w") as f:
        f.write('{"name":"@deepseek-ai/dsh","version":"%s"}' % version)
    # a large-ish sibling so "is the rest intact" is a real question
    os.makedirs(os.path.join(root, "node_modules", "node-pty"), exist_ok=True)
    with open(os.path.join(root, "node_modules", "node-pty", "MARKER"), "w") as f:
        f.write("native module stays put")


def source_layout(root: str, version: str) -> None:
    """The pre-1.5 source checkout."""
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(os.path.join(root, "apps", "cli", "src"), exist_ok=True)
    os.makedirs(os.path.join(root, "node_modules"), exist_ok=True)
    with open(os.path.join(root, "apps", "cli", "src", "bin.ts"), "w") as f:
        f.write("// entry\n")
    with open(os.path.join(root, "package.json"), "w") as f:
        f.write('{"name":"@deepseek-ai/dsh-root","version":"%s"}' % version)
    with open(os.path.join(root, "node_modules", "MARKER"), "w") as f:
        f.write("old source deps")


def reset(npm: bool = True, version: str = "0.1.5-rc.2") -> None:
    shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(LAUNCHER_DIR, exist_ok=True)
    if npm:
        npm_layout(HARNESS, version)
    else:
        source_layout(LEGACY, version)
    fake_runtime()


def harness_version() -> str:
    mode = "npm" if os.path.exists(os.path.join(HARNESS, updater.NPM_ENTRY)) else "source"
    root = HARNESS if mode == "npm" else LEGACY
    return updater.installed_version(root, mode)


def drain(events, log) -> None:
    while True:
        try:
            ev = events.get_nowait()
        except queue.Empty:
            return
        if ev["kind"] == "progress":
            log.append("%3d%% %s%s" % (ev["pct"], ev["text"],
                                       " [indeterminate]" if ev.get("indeterminate") else ""))
        elif ev["kind"] == "legacy":
            log.append("LEGACY %s" % ev["path"])
        elif ev["kind"] == "done":
            log.append("DONE ok=%s rolled_back=%s smoke=%s msg=%s"
                       % (ev["ok"], ev.get("rolled_back"), ev.get("smoke"), ev["msg"]))


def run_worker(*, npm_fail: bool = False, smoke_fail: bool = False,
               mode: str = "npm") -> tuple[bool, list[str]]:
    events: "queue.Queue[dict]" = queue.Queue()
    cancel = threading.Event()
    if npm_fail:
        os.environ["FAKE_NPM_FAIL"] = "1"
    else:
        os.environ.pop("FAKE_NPM_FAIL", None)
    worker = updater.UpdateWorker(
        install_dir=INSTALL, harness_dir=HARNESS if mode == "npm" else LEGACY,
        mode=mode, release=TARGET, events=events, cancel=cancel,
        launcher_dir=LAUNCHER_DIR,
        stop_backend=lambda: 0,
        start_backend=lambda: object(),
        wait_ready=lambda t: not smoke_fail,
        authenticated_url=lambda t: ("http://127.0.0.1:3080/?token=x"
                                     if not smoke_fail else "http://127.0.0.1:3080"),
    )
    worker.start()
    log: list[str] = []
    while worker.is_alive():
        drain(events, log)
        time.sleep(0.05)
    drain(events, log)
    return bool(log and log[-1].startswith("DONE ok=True")), log


def check(label: str, cond: bool, extra: str = "") -> bool:
    print("%-6s %s%s" % ("PASS" if cond else "FAIL", label,
                         ("  <- " + extra) if extra and not cond else ""))
    return cond


# --------------------------------------------------------------------------
# launcher self-update (no network: a file:// asset of synthetic bytes)
# --------------------------------------------------------------------------
def _launcher_release(src: str, digest: str = "") -> updater.LauncherRelease:
    return updater.LauncherRelease(
        tag="v9.9.9", version="9.9.9",
        url="file:///" + src.replace("\\", "/"),
        size=os.path.getsize(src), digest=digest)


def _run_launcher_worker(src: str, *, digest: str = "", cancel=None) -> tuple:
    """-> (done event dict, exe_path, worker). Leaves the tree for inspection.

    `src` must already exist: the bytes have to stay the same across calls or a
    digest computed earlier will not match the file being served.
    """
    where = os.path.join(BASE, "launcher-update")
    shutil.rmtree(where, ignore_errors=True)
    os.makedirs(where, exist_ok=True)
    exe = os.path.join(where, "DSHLauncher.exe")
    with open(exe, "wb") as f:
        f.write(b"ORIGINAL")
    events: "queue.Queue[dict]" = queue.Queue()
    worker = updater.LauncherUpdateWorker(
        exe_path=exe, release=_launcher_release(src, digest),
        events=events, cancel=cancel or threading.Event(),
        log_path=os.path.join(where, "u.log"))
    worker.start()
    worker.join(timeout=60)
    done: dict = {}
    while True:
        try:
            ev = events.get_nowait()
            if ev["kind"] == "done":
                done = ev
        except queue.Empty:
            break
    return done, exe, worker


def launcher_section() -> bool:
    ok = True
    print("\n--- 7 启动器自更新 ---")
    payload = os.path.join(BASE, "payload.exe")
    with open(payload, "wb") as f:
        f.write(b"MZ" + os.urandom(2_000_000))
    tiny = os.path.join(BASE, "tiny.exe")
    with open(tiny, "wb") as f:
        f.write(b"MZ" + b"x" * 100)
    good = updater.sha256_file(payload)

    # (i) the honest path: download, verify, swap
    done, exe, w = _run_launcher_worker(payload, digest=good)
    ok &= check("成功时 ok 且要求重启", done.get("ok") is True
                and done.get("restart") is True, str(done))
    ok &= check("活文件就是新字节", updater.sha256_file(exe) == good)
    ok &= check("旧文件留在 .old",
                os.path.exists(w.backup)
                and open(w.backup, "rb").read() == b"ORIGINAL")
    ok &= check("暂存文件已清掉", not os.path.exists(w.staged))

    # (ii) nothing is left behind even when the swap cannot complete
    real_replace = updater.os.replace
    calls = {"n": 0}

    def flaky_replace(a, b):
        calls["n"] += 1
        if calls["n"] == 2:               # the staged -> live move
            raise OSError("测试用：模拟替换失败")
        return real_replace(a, b)

    updater.os.replace = flaky_replace
    try:
        done2, exe2, w2 = _run_launcher_worker(payload, digest=good)
    finally:
        updater.os.replace = real_replace
    ok &= check("替换失败时上报失败", done2.get("ok") is False, str(done2))
    ok &= check("替换失败时上报已还原", done2.get("rolled_back") is True, str(done2))
    ok &= check("还原后活文件是原来的字节",
                open(exe2, "rb").read() == b"ORIGINAL")

    # (iii) cancel arriving while hashing must not swap anything
    cancel = threading.Event()
    cancel.set()
    done3, exe3, w3 = _run_launcher_worker(payload, digest=good, cancel=cancel)
    ok &= check("取消时不动活文件",
                open(exe3, "rb").read() == b"ORIGINAL" and done3.get("ok") is False,
                str(done3))
    ok &= check("取消时不留下载物", not os.path.exists(w3.staged))

    # (iv) the size floor
    done4, exe4, w4 = _run_launcher_worker(tiny, digest="")
    ok &= check("过小的下载被拒", done4.get("ok") is False
                and "字节" in str(done4.get("msg")), str(done4))
    ok &= check("过小被拒后不留 .old", not os.path.exists(w4.backup))
    ok &= check("过小被拒后不留 .new", not os.path.exists(w4.staged))

    # (v) a release with no digest still swaps — the documented downgrade
    done5, exe5, w5 = _run_launcher_worker(payload, digest="")
    ok &= check("无校验值仍可更新（已在文档里说明）", done5.get("ok") is True, str(done5))

    os.remove(payload)
    os.remove(tiny)
    return ok


def main() -> int:
    ok = True
    os.environ.pop("FAKE_NPM_FAIL", None)

    # ---- 1. happy path ---------------------------------------------------
    print("== 1. npm -> npm 正常更新 ==")
    reset()
    ok &= check("starts on 0.1.5-rc.2", harness_version() == "0.1.5-rc.2", harness_version())
    good, log = run_worker()
    print("\n".join("   " + l for l in log[-9:]))
    ok &= check("worker reported success", good)
    ok &= check("harness is the new version", harness_version() == TARGET.version,
                harness_version())
    ok &= check("harness.old cleaned up", not os.path.exists(os.path.join(INSTALL, "harness.old")))
    ok &= check("harness.new cleaned up", not os.path.exists(os.path.join(INSTALL, "harness.new")))
    ok &= check("harness.txt written",
                open(os.path.join(LAUNCHER_DIR, "harness.txt"), encoding="utf-8").read() == HARNESS)
    ok &= check("version.json written",
                os.path.exists(os.path.join(LAUNCHER_DIR, "data", "version.json")))

    # ---- 2. npm install fails -> rollback --------------------------------
    print("\n== 2. npm 安装失败 -> 回滚 ==")
    reset()
    bad, log = run_worker(npm_fail=True)
    print("\n".join("   " + l for l in log[-6:]))
    ok &= check("worker reported failure", not bad)
    ok &= check("rolled back to 0.1.5-rc.2", harness_version() == "0.1.5-rc.2",
                harness_version())
    ok &= check("native module still there",
                os.path.exists(os.path.join(HARNESS, "node_modules", "node-pty", "MARKER")))
    ok &= check("no harness.old / harness.new left",
                not os.path.exists(os.path.join(INSTALL, "harness.old"))
                and not os.path.exists(os.path.join(INSTALL, "harness.new")))

    # ---- 3. smoke test fails -> rollback ---------------------------------
    print("\n== 3. 试运行失败 -> 回滚 ==")
    reset()
    os.environ.pop("FAKE_NPM_FAIL", None)
    bad, log = run_worker(smoke_fail=True)
    print("\n".join("   " + l for l in log[-5:]))
    ok &= check("worker reported failure", not bad)
    ok &= check("rolled back to 0.1.5-rc.2", harness_version() == "0.1.5-rc.2",
                harness_version())
    ok &= check("native module still there",
                os.path.exists(os.path.join(HARNESS, "node_modules", "node-pty", "MARKER")))

    # ---- 4. cancel mid-install -> rollback -------------------------------
    print("\n== 4. 安装中取消 -> 回滚 ==")
    reset()
    events: "queue.Queue[dict]" = queue.Queue()
    cancel = threading.Event()
    worker = updater.UpdateWorker(
        install_dir=INSTALL, harness_dir=HARNESS, mode="npm", release=TARGET,
        events=events, cancel=cancel, launcher_dir=LAUNCHER_DIR,
        stop_backend=lambda: 0)
    worker.start()
    time.sleep(0.4)
    cancel.set()
    log = []
    while worker.is_alive():
        drain(events, log)
        time.sleep(0.05)
    drain(events, log)
    print("\n".join("   " + l for l in log[-4:]))
    ok &= check("cancel stopped the worker", any("取消" in l for l in log))
    ok &= check("old version still in place", harness_version() == "0.1.5-rc.2",
                harness_version())

    # ---- 5. source layout -> npm layout ----------------------------------
    print("\n== 5. 源码布局 -> npm 布局（老装机迁移）==")
    reset(npm=False)
    ok &= check("starts on the source layout", harness_version() == "0.1.5-rc.2",
                harness_version())
    good, log = run_worker(mode="source")
    print("\n".join("   " + l for l in log[-7:]))
    ok &= check("worker reported success", good)
    ok &= check("npm layout installed", harness_version() == TARGET.version, harness_version())
    ok &= check("old source tree reported as removable", any("LEGACY" in l for l in log))
    ok &= check("source tree left alone (user deletes it)", os.path.isdir(LEGACY))

    # ---- 6. swap died between its two renames ----------------------------
    print("\n== 6. 切换中途失败后的恢复 ==")
    reset()
    w = updater.UpdateWorker(
        install_dir=INSTALL, harness_dir=HARNESS, mode="npm", release=TARGET,
        events=queue.Queue(), cancel=threading.Event(), launcher_dir=LAUNCHER_DIR)
    npm_layout(w.new_dir, TARGET.version)
    w._had_old = True
    os.replace(HARNESS, w.old_dir)           # harness -> harness.old, then "crash"
    ok &= check("rollback reports a usable install", w._rollback("测试") is True)
    ok &= check("harness restored", harness_version() == "0.1.5-rc.2", harness_version())
    ok &= check("no leftovers", not os.path.exists(w.old_dir)
                and not os.path.exists(w.new_dir))

    # 7 ---- launcher self-update: the swap, and every way it must not happen --
    ok &= launcher_section()

    print("\n%s" % ("ALL PASS" if ok else "SOME CHECKS FAILED"))
    if ok:
        shutil.rmtree(BASE, ignore_errors=True)      # keep the tree on failure
    else:
        print("合成目录留在 %s，可以逐个看" % BASE)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
