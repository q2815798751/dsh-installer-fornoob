#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for the GitHub latency/speed probes.

    python launcher\\test-github-probe.py

No network and no sockets: `_opener` is replaced with a fake, which is the same
seam the rest of the suite patches (`test-updater.py` patches os.replace,
`test-security.py` drives a file:/// asset). A fake gives what a local HTTP
server cannot — a controllable clock and failures that happen on the Nth call.

The important assertions here are the ones that keep a diagnostic row from
blocking an install: every failure mode must come back WARN, never FAIL.
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "installer"))

import updater  # noqa: E402


class FakeResponse:
    """Behaves like the object urllib hands back, with a scripted body."""

    def __init__(self, body: bytes, status: int = 200, headers: dict | None = None):
        self._body = io.BytesIO(body)
        self.status = status
        self.headers = headers or {}
        self.reads: list[int] = []

    def read(self, n: int = -1) -> bytes:
        self.reads.append(n)
        return self._body.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, responses=None, error=None, counter=None):
        self.responses = list(responses or [])
        self.error = error
        self.counter = counter if counter is not None else {"calls": 0}

    def open(self, req, timeout=None):
        self.counter["calls"] += 1
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("fake opener ran out of responses")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def _patch(module, opener, clock):
    """Point a module at a fake opener and a fake clock."""
    module._opener = lambda proxy: opener
    module.time = clock


class Clock:
    """time.time() that advances a fixed step on every call."""

    def __init__(self, step: float = 0.0, start: float = 1000.0):
        self.step, self.now = step, start

    def time(self) -> float:
        self.now += self.step
        return self.now


RELEASES = [
    {"tag_name": "v9.9.9", "draft": True,
     "assets": [{"name": "DSHLauncher.exe", "browser_download_url": "https://x/draft.exe"}]},
    {"tag_name": "v9.9.8", "draft": False,
     "assets": [{"name": "notes.txt", "browser_download_url": "https://x/notes.txt"}]},
    {"tag_name": "v9.9.7", "draft": False,
     "assets": [{"name": "DSHLauncher.exe", "size": 123, "digest": "sha256:abc",
                 "browser_download_url": "https://github.com/x/releases/download/v9.9.7/DSHLauncher.exe"}]},
]


def main() -> int:
    failures: list[str] = []

    def check(label: str, ok: bool, extra: str = "") -> None:
        print("%-4s %s%s" % ("ok" if ok else "FAIL", label,
                             ("  <- " + str(extra)) if extra and not ok else ""))
        if not ok:
            failures.append(label)

    real_opener, real_time = updater._opener, updater.time

    def restore():
        updater._opener, updater.time = real_opener, real_time

    def fake_open(body: bytes, status: int = 200, headers: dict | None = None):
        return FakeOpener([FakeResponse(body, status, headers)])

    try:
        # ---- gh_asset_url: which release, and the drafts/notes cases --------
        mod = updater
        counter = {"calls": 0}
        mod._opener = lambda p: FakeOpener([FakeResponse(json.dumps(RELEASES).encode())], counter=counter)
        asset = mod.gh_asset_url()
        check("资产解析：跳过 draft 与没有资产的发布",
              (asset or {}).get("tag") == "v9.9.7", asset)
        check("资产解析：URL 逐字取自 API（不硬编码 CDN）",
              (asset or {}).get("url", "").startswith("https://github.com/"), asset)
        check("资产解析：digest 去掉 sha256: 前缀",
              (asset or {}).get("digest") == "abc", asset)

        mod._opener = lambda p: FakeOpener([FakeResponse(b"[]")])
        check("没有发布时返回 None", mod.gh_asset_url() is None)
        mod._opener = lambda p: FakeOpener([FakeResponse(b"not json")])
        check("响应不是 JSON 时返回 None", mod.gh_asset_url() is None)
        mod._opener = lambda p: FakeOpener(error=OSError("boom"))
        check("接口不可达时返回 None", mod.gh_asset_url() is None)

        # ---- latency: min of N, and exactly one call on a dead route -------
        mod._opener = lambda p: FakeOpener([FakeResponse(b"x"), FakeResponse(b"x"),
                                           FakeResponse(b"x")])
        mod.time = Clock(step=0.0)          # frozen -> every sample reads 0.0
        out = mod.latency_probe("https://api.github.com/x", samples=3)
        check("延迟成功时报最小值", out["ok"] and out["min"] == 0.0, out)

        clock = Clock(step=1.0)
        mod.time = clock
        out = mod.latency_probe("https://api.github.com/x", samples=3)
        check("延迟采样次数正确", len(out["samples"]) == 3, out)
        check("延迟明细含次数与最小值", "3 次" in out["detail"] and "最快" in out["detail"],
              out["detail"])

        counter = {"calls": 0}
        mod._opener = lambda p: FakeOpener(error=OSError("timed out"), counter=counter)
        out = mod.latency_probe("https://api.github.com/x", samples=3)
        check("失败时立即停止（只调一次，不白等 3 个超时）",
              counter["calls"] == 1 and out["ok"] is False, counter)
        check("失败时给出人话原因", "连接超时" in out["detail"], out["detail"])

        # A 403 has to be raised, not returned: urllib turns 4xx into HTTPError,
        # and it is that object's headers the rate-limit check reads.
        limited = urllib.error.HTTPError("https://api.github.com/x", 403, "rate limited",
                                         {"X-RateLimit-Remaining": "0"}, None)
        mod._opener = lambda p: FakeOpener(error=limited)
        out = mod.latency_probe("https://api.github.com/x")
        check("限流被识别为限流而不是网络故障",
              out["ok"] and out.get("limited") and "限流" in out["detail"], out)

        # ---- speed: caps, Range, and the budget ---------------------------
        mod.time = Clock(step=0.1)
        mod._opener = lambda p: FakeOpener([FakeResponse(b"x" * (2 * 1024 * 1024), status=206)])
        out = mod.speed_probe({"url": "https://x/a.exe"}, limit=1 << 20)
        check("测速只读 limit 字节", out["ok"] and out["bytes"] == (1 << 20), out)
        check("206 被识别为按区间返回", out["ranged"] is True, out)

        mod.time = Clock(step=0.1)
        mod._opener = lambda p: FakeOpener([FakeResponse(b"x" * (2 * 1024 * 1024), status=200)])
        out = mod.speed_probe({"url": "https://x/a.exe"}, limit=1 << 20)
        check("服务器忽略 Range（200）也不算失败，仍只读 1MB",
              out["ok"] and out["ranged"] is False and out["bytes"] == (1 << 20), out)

        # A trickle must be stopped by the wall clock, not by a socket timeout.
        class Trickle(FakeResponse):
            def read(self, n=-1):
                updater.time.now += 1.0        # each chunk takes a second
                return super().read(min(n, 4096) if n > 0 else 4096)

        mod.time = Clock(step=0.0)
        mod._opener = lambda p: FakeOpener([Trickle(b"x" * (10 * 1024 * 1024), status=206)])
        out = mod.speed_probe({"url": "https://x/a.exe"}, limit=1 << 20, budget=3.0)
        check("涓流传输被墙钟预算截断（不靠 socket 超时）",
              out["ok"] and out["bytes"] < (1 << 20), out)
        restore()

        mod.time = Clock(step=0.5)
        mod._opener = lambda p: FakeOpener(error=OSError("timed out"))
        out = mod.speed_probe({"url": "https://x/a.exe"})
        check("测速失败时 ok=False 且有原因", not out["ok"] and "超时" in out["detail"], out)
        restore()

        # ---- the clamp: no failure mode of the asset row may be FAIL ------
        # This is the assertion that protects a firewall'd machine that
        # installs fine from npm: Preflight.ok is "no blockers".
        import preflight as pf
        real_pf_opener, real_pf_time = pf._opener, pf.time
        for label, opener in (
            ("接口不可达", FakeOpener(error=OSError("timed out"))),
            ("接口返回垃圾", FakeOpener([FakeResponse(b"junk")])),
            ("接口限流", FakeOpener([FakeResponse(b"{}", status=403,
                                                 headers={"X-RateLimit-Remaining": "0"})])),
            ("测速超时", FakeOpener([FakeResponse(json.dumps(RELEASES).encode()),
                                    FakeResponse(b"", status=206)])),
        ):
            pf._opener = lambda p, o=opener: o
            pf.time = Clock(step=0.05)
            api, speed = pf._check_github()
            check("失败形态【%s】下两行都只到 WARN" % label,
                  api.status != pf.FAIL and speed.status != pf.FAIL,
                  "%s / %s" % (api.status, speed.status))
        pf._opener, pf.time = real_pf_opener, real_pf_time
        restore()

        # The same clamp for the launcher's row.
        real_gac = updater._github_asset_check
        for label, opener in (
            ("接口不可达", FakeOpener(error=OSError("timed out"))),
            ("接口返回垃圾", FakeOpener([FakeResponse(b"junk")])),
        ):
            updater._opener = lambda p, o=opener: o
            updater.time = Clock(step=0.05)
            c = updater._github_asset_check(None, True)
            check("面板的下载行【%s】只到 WARN" % label, c.status != updater.FAIL, c.status)
        restore()

        # The asset URL is taken from the release listing, so a listing that
        # carries no digest must still produce a usable row.
        updater._opener = lambda p: FakeOpener([FakeResponse(json.dumps(
            [{"tag_name": "v1.0.0", "draft": False,
              "assets": [{"name": "DSHLauncher.exe", "size": 10,
                          "browser_download_url": "https://x/y.exe"}]}]).encode()),
            FakeResponse(b"x" * 4096, status=206)])
        updater.time = Clock(step=0.01)
        c = updater._github_asset_check(None, True)
        check("无摘要的发布仍能测速并给出数字", c.status in (updater.OK, updater.WARN)
              and "MB/s" in c.detail, c.detail)
    finally:
        restore()

    print("\n%s" % ("ALL OK" if not failures else "%d FAILED: %s" % (len(failures), failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
