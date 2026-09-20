#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""updater.py 的回滚自检 —— 起一个合成安装目录，一分钟内出结果。

    python launcher/test-updater.py

真实下载一次官方源码（几百 KB），但 node.exe 用 python.exe 顶替、corepack.js
是一个直接返回 0 的 Python 脚本，所以 pnpm install / pnpm build 是瞬时"成功"
而不是二十分钟。这样测的是这个功能里最容易出错的部分：目录怎么换、失败怎么
退回去。六种情况：

  1  正常更新           新版本落地、node_modules 被复用、旧备份清理干净
  2  构建失败           回滚到旧版本，且旧目录原样无损
  3  试运行失败         回滚
  4  下载中取消         回滚
  5  依赖已迁移未切换   回滚（node_modules 必须搬回来，不能跟着临时目录删掉）
  6  切换中途失败       回滚（repo 缺失、只剩 repo.old 那种半状态）

合成目录在 launcher/test/updater/（已 gitignore），通过后自动清掉，失败时留下
来给你看。退出码非 0 表示有断言没通过。
"""
from __future__ import annotations

import os
import queue
import shutil
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LAUNCHER = HERE                      # this script lives in launcher/
sys.path.insert(0, LAUNCHER)

import updater  # noqa: E402

BASE = os.path.join(HERE, "test", "updater")     # launcher/test/ is gitignored
REPO = os.path.join(BASE, "repo")
RUNTIME = os.path.join(BASE, "runtime")
LAUNCHER_DIR = os.path.join(BASE, "launcher")

# Never touch the real uninstall registry entry from a test.
updater.set_registered_version = lambda version: None


def fake_runtime(work: bool) -> None:
    """node.exe = python.exe, corepack.js = a Python script that says yes."""
    shutil.rmtree(RUNTIME, ignore_errors=True)
    os.makedirs(os.path.join(RUNTIME, "node_modules", "corepack", "dist"), exist_ok=True)
    shutil.copy2(sys.executable, os.path.join(RUNTIME, "node.exe"))
    body = ('import sys\n'
            'print("corepack-shim", sys.argv[1:])\n'
            'sys.exit(%d)\n' % (0 if work else 1))
    with open(os.path.join(RUNTIME, "node_modules", "corepack", "dist", "corepack.js"),
              "w", encoding="utf-8") as f:
        f.write(body)


def fake_repo(version: str) -> None:
    shutil.rmtree(REPO, ignore_errors=True)
    os.makedirs(REPO)
    with open(os.path.join(REPO, "package.json"), "w", encoding="utf-8") as f:
        f.write('{"name":"root","version":"%s"}' % version)
    os.makedirs(os.path.join(REPO, "node_modules", ".pnpm"), exist_ok=True)
    with open(os.path.join(REPO, "node_modules", "MARKER"), "w") as f:
        f.write("old-deps-are-precious")
    os.makedirs(os.path.join(REPO, "stale-dir-from-old-version"), exist_ok=True)
    os.makedirs(os.path.join(REPO, "packages", "pkg"), exist_ok=True)
    with open(os.path.join(REPO, "packages", "pkg", "old.ts"), "w") as f:
        f.write("export const old = 1\n")


def drain(events, log):
    while True:
        try:
            ev = events.get_nowait()
        except queue.Empty:
            return
        if ev["kind"] == "progress":
            log.append("%3d%% %s%s" % (ev["pct"], ev["text"],
                                       " [indeterminate]" if ev.get("indeterminate") else ""))
        elif ev["kind"] == "done":
            log.append("DONE ok=%s rolled_back=%s msg=%s"
                       % (ev["ok"], ev.get("rolled_back"), ev["msg"]))


def run_worker(release, *, work: bool, smoke_fail: bool = False) -> tuple[bool, list[str]]:
    fake_runtime(work)
    events: "queue.Queue[dict]" = queue.Queue()
    cancel = threading.Event()
    w = updater.UpdateWorker(
        repo_dir=REPO, launcher_dir=LAUNCHER_DIR, release=release, commit="deadbeefcafe",
        events=events, cancel=cancel,
        stop_backend=lambda: 0,
        start_backend=lambda: object(),
        wait_ready=lambda t: not smoke_fail,
        authenticated_url=lambda t: ("http://127.0.0.1:3080/?token=x"
                                     if not smoke_fail else "http://127.0.0.1:3080"),
    )
    w.start()
    log: list[str] = []
    while w.is_alive():
        drain(events, log)
        time.sleep(0.05)
    drain(events, log)
    ok = log and log[-1].startswith("DONE ok=True")
    return bool(ok), log


def check(label: str, cond: bool, extra: str = "") -> bool:
    print("%-6s %s%s" % ("PASS" if cond else "FAIL", label,
                         ("  <- " + extra) if extra and not cond else ""))
    return cond


def main() -> int:
    ok = True
    fake_repo("0.1.5-rc.2")
    os.makedirs(LAUNCHER_DIR, exist_ok=True)

    releases = updater.list_releases()
    target = releases[0]
    print("target release: %s (%s)\n" % (target.tag, target.published))

    # ---- 1. happy path ---------------------------------------------------
    print("== 1. 正常更新 ==")
    ok &= check("installed_version before", updater.installed_version(REPO) == "0.1.5-rc.2",
                updater.installed_version(REPO))
    good, log = run_worker(target, work=True)
    print("\n".join("   " + line for line in log[-14:]))
    ok &= check("worker reported success", good)
    ok &= check("version on disk is the new one",
                updater.installed_version(REPO) == target.version,
                updater.installed_version(REPO))
    ok &= check("node_modules was carried over",
                os.path.exists(os.path.join(REPO, "node_modules", "MARKER")))
    ok &= check("old version backup removed",
                not os.path.exists(os.path.join(BASE, "repo.old")))
    ok &= check("no leftover repo.new",
                not os.path.exists(os.path.join(BASE, "repo.new")))
    ok &= check("stale dir from the old tree is gone",
                not os.path.exists(os.path.join(REPO, "stale-dir-from-old-version")))
    ok &= check("real source landed (apps/ present)",
                os.path.isdir(os.path.join(REPO, "apps")))
    ok &= check("fake packages/pkg/old.ts is gone",
                not os.path.exists(os.path.join(REPO, "packages", "pkg", "old.ts")))
    ok &= check("version.json written",
                os.path.exists(os.path.join(LAUNCHER_DIR, "data", "version.json")))
    ok &= check("update.log written",
                os.path.exists(os.path.join(LAUNCHER_DIR, "data", "update.log")))

    # ---- 2. build failure rolls back ------------------------------------
    print("\n== 2. 构建失败 -> 回滚 ==")
    fake_repo("0.1.5-rc.2")
    bad, log = run_worker(target, work=False)
    print("\n".join("   " + line for line in log[-10:]))
    ok &= check("worker reported failure", not bad)
    ok &= check("rolled back to the old version",
                updater.installed_version(REPO) == "0.1.5-rc.2",
                updater.installed_version(REPO))
    ok &= check("old tree intact (stale dir still there)",
                os.path.exists(os.path.join(REPO, "stale-dir-from-old-version")))
    ok &= check("node_modules came back",
                os.path.exists(os.path.join(REPO, "node_modules", "MARKER")))
    ok &= check("no repo.old / repo.new left behind",
                not os.path.exists(os.path.join(BASE, "repo.old"))
                and not os.path.exists(os.path.join(BASE, "repo.new")))

    # ---- 3. smoke-test failure rolls back --------------------------------
    print("\n== 3. 试运行失败 -> 回滚 ==")
    fake_repo("0.1.5-rc.2")
    bad, log = run_worker(target, work=True, smoke_fail=True)
    print("\n".join("   " + line for line in log[-6:]))
    ok &= check("worker reported failure", not bad)
    ok &= check("rolled back to the old version",
                updater.installed_version(REPO) == "0.1.5-rc.2",
                updater.installed_version(REPO))
    ok &= check("node_modules came back",
                os.path.exists(os.path.join(REPO, "node_modules", "MARKER")))

    # ---- 4. cancel mid-download rolls back -------------------------------
    print("\n== 4. 下载中取消 -> 回滚 ==")
    fake_repo("0.1.5-rc.2")
    fake_runtime(True)
    events: "queue.Queue[dict]" = queue.Queue()
    cancel = threading.Event()
    w = updater.UpdateWorker(
        repo_dir=REPO, launcher_dir=LAUNCHER_DIR, release=target, commit="deadbeefcafe",
        events=events, cancel=cancel, stop_backend=lambda: 0)
    w.start()
    time.sleep(1.2)
    cancel.set()
    log = []
    while w.is_alive():
        drain(events, log)
        time.sleep(0.05)
    drain(events, log)
    print("\n".join("   " + line for line in log[-5:]))
    ok &= check("cancel stopped the worker", any("取消" in l for l in log))
    ok &= check("cancel left the old version in place",
                updater.installed_version(REPO) == "0.1.5-rc.2",
                updater.installed_version(REPO))

    # ---- 5. deps already moved, swap never happened ----------------------
    print("\n== 5. 依赖已迁移但未切换时回滚 ==")
    fake_repo("0.1.5-rc.2")
    fake_runtime(True)
    w = updater.UpdateWorker(repo_dir=REPO, launcher_dir=LAUNCHER_DIR, release=target,
                             commit="x", events=queue.Queue(), cancel=threading.Event())
    os.makedirs(w.new_dir, exist_ok=True)
    os.replace(os.path.join(REPO, "node_modules"), os.path.join(w.new_dir, "node_modules"))
    w._deps_moved = True
    ok &= check("rollback reports a usable install", w._rollback("测试") is True)
    ok &= check("node_modules came back to repo",
                os.path.exists(os.path.join(REPO, "node_modules", "MARKER")))
    ok &= check("scratch tree removed", not os.path.exists(w.new_dir))
    ok &= check("version unchanged", updater.installed_version(REPO) == "0.1.5-rc.2")

    # ---- 6. swap died between its two renames ----------------------------
    print("\n== 6. 切换中途失败后的恢复 ==")
    fake_repo("0.1.5-rc.2")
    w = updater.UpdateWorker(repo_dir=REPO, launcher_dir=LAUNCHER_DIR, release=target,
                             commit="x", events=queue.Queue(), cancel=threading.Event())
    os.makedirs(w.new_dir, exist_ok=True)
    os.replace(os.path.join(REPO, "node_modules"), os.path.join(w.new_dir, "node_modules"))
    w._deps_moved = True
    os.replace(REPO, w.old_dir)              # repo -> repo.old, then "crash"
    ok &= check("rollback reports a usable install", w._rollback("测试") is True)
    ok &= check("repo restored", updater.installed_version(REPO) == "0.1.5-rc.2",
                updater.installed_version(REPO))
    ok &= check("node_modules restored",
                os.path.exists(os.path.join(REPO, "node_modules", "MARKER")))
    ok &= check("no leftovers", not os.path.exists(w.old_dir)
                and not os.path.exists(w.new_dir))

    print("\n%s" % ("ALL PASS" if ok else "SOME CHECKS FAILED"))
    if ok:
        shutil.rmtree(BASE, ignore_errors=True)      # keep the tree on failure
    else:
        print("合成目录留在 %s，可以逐个看" % BASE)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
