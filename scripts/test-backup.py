#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""备份护栏的自检 —— 被测的是 `scripts\\backup-dsh-registry.py`。

    python scripts\\test-backup.py

AW-15 把 AW-0 报告里那句「17 条断言全过」落成**这个真正的测试文件**（复查时仓库里
没有对应文件，那些断言此前不可复现）。锁住两件事：

  (a) **还原前按 manifest 校验**备份文件的字节数与 sha256 —— 把 `.reg` 篡改掉
      （语法仍合法）必须被拒绝、rc 非 0、不做任何改动。以前 `do_restore` 从不核对，
      篡改内容照样被 `reg import` 进去。
  (b) 还原前的 `*-prerestore` 快照**导出失败必须中止** —— 不在没有安全网的情况下
      还原（同族于 AW-1 修的「备份失败却静默继续」）。

数据安全（硬性规则 5）：
  * **全程只用一次性测试键** `HKCU\\Software\\DSHBackupSelfTest-*`，用完 `reg delete` 删掉；
  * **绝不碰真实的卸载键** `...\\Uninstall\\DeepSeekHarness`（本机现在也不存在，
    用户决定不恢复）；
  * **不运行 `uninstall.bat`**、**不对任何真实进程 taskkill**、不碰 `%USERPROFILE%\\.dsh`。
  这里只做 `reg add/query/export/import/delete`（都指向自建的一次性键）与临时目录里的
  文件复制。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "backup-dsh-registry.py")

_NO_WINDOW = 0x08000000

# 一次性测试键：绝不指向真实卸载键。
SCRATCH = r"HKCU\Software\DSHBackupSelfTest-%d-%d" % (os.getpid(), int(time.time()))

OK = True


def check(label: str, cond: bool, extra="") -> None:
    global OK
    print("%-6s %s%s" % ("PASS" if cond else "FAIL", label,
                         ("  <- " + str(extra)) if extra and not cond else ""))
    OK = OK and bool(cond)


def _sys(name: str) -> str:
    return os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", name)


def _reg(*args: str):
    """调 `reg.exe`（绝对路径，不经 PATH 解析）。调用方自己看返回码/输出。"""
    return subprocess.run([_sys("reg.exe"), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)


def _load():
    spec = importlib.util.spec_from_file_location("backup_dsh_registry", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _marker() -> str:
    """读一次性键里 Marker 的当前值（用来证明「还原到底动没动这个键」）。"""
    return _reg("query", SCRATCH, "/v", "Marker").stdout


def main() -> int:
    mod = _load()

    # ---- 纯函数 _verify_backup_file：先钉住它本身，再钉接线 ----------------
    work = tempfile.mkdtemp(prefix="dsh-backup-test-")
    try:
        sample = os.path.join(work, "sample.bin")
        with open(sample, "wb") as fh:
            fh.write(b"hello-backup")
        good = {"bytes": os.path.getsize(sample), "sha256": mod._sha256(sample)}
        ok, why = mod._verify_backup_file(sample, good)
        check("完整性：字节数与 sha256 都对 -> 放行", ok, why)
        bad_bytes = {"bytes": good["bytes"] + 1, "sha256": good["sha256"]}
        ok, why = mod._verify_backup_file(sample, bad_bytes)
        check("完整性：字节数不符 -> 拒绝", not ok and "字节数" in why, why)
        bad_sha = {"bytes": good["bytes"], "sha256": "0" * 64}
        ok, why = mod._verify_backup_file(sample, bad_sha)
        check("完整性：sha256 不符 -> 拒绝", not ok and "sha256" in why, why)
        ok, why = mod._verify_backup_file(os.path.join(work, "nope.bin"), good)
        check("完整性：文件缺失 -> 拒绝", not ok, why)
        empty = os.path.join(work, "empty.bin")
        open(empty, "wb").close()
        ok, why = mod._verify_backup_file(empty, {"bytes": 0, "sha256": ""})
        check("完整性：空文件 -> 拒绝", not ok, why)

        # ---- 准备：一次性测试键 + 安装目录（带 shortcuts.txt）------------
        made = _reg("add", SCRATCH, "/v", "Marker", "/t", "REG_SZ",
                    "/d", "ORIGINAL", "/f")
        check("测试键已建好（一次性键，不是真实卸载键）", made.returncode == 0,
              made.stderr or made.stdout)

        install_dir = os.path.join(work, "install")
        os.makedirs(install_dir, exist_ok=True)
        shortcuts = os.path.join(install_dir, mod.SHORTCUTS_FILE)
        with open(shortcuts, "w", encoding="utf-8") as fh:
            fh.write("C:\\Users\\x\\Desktop\\DSH.lnk\n")

        # ---- 正常备份 -----------------------------------------------------
        dest = os.path.join(work, "b1")
        manifest = mod.do_backup(dest, install_dir, SCRATCH)
        reg = manifest["registry"]
        check("备份：注册项已导出", reg.get("exported") is True, reg)
        check("备份：manifest 记了字节数与 64 位 sha256",
              isinstance(reg.get("bytes"), int) and len(reg.get("sha256") or "") == 64, reg)
        check("备份：shortcuts 也记了 sha256",
              len((manifest["shortcuts"].get("sha256") or "")) == 64, manifest["shortcuts"])
        check("备份：manifest.json 落盘",
              os.path.isfile(os.path.join(dest, mod.MANIFEST)))
        check("备份：正常备份的退出码为 0", mod.backup_exit_code(manifest) == 0)

        # ---- (a) 篡改 .reg 内容（语法仍合法）-> 还原必须被拒 --------------
        reg_path = os.path.join(dest, mod.REG_FILE)
        with open(reg_path, encoding="utf-16-le", errors="replace") as fh:
            text = fh.read()
        tampered = text.replace("ORIGINAL", "TAMPERED")
        if tampered == text:                      # 兜底：至少改掉字节数
            tampered = text + "\r\n"
        with open(reg_path, "w", encoding="utf-16-le") as fh:
            fh.write(tampered)
        check("篡改后 sha256 与 manifest 不符",
              mod._sha256(reg_path).lower() != reg["sha256"].lower())

        rc = mod.do_restore(dest, install_dir, True, os.path.join(work, "out1"))
        check("篡改备份 -> 还原被拒绝（rc 非 0）", rc != 0, "rc=%s" % rc)
        body = _marker()
        check("篡改备份 -> 真实键内容没被改动（仍是 ORIGINAL）",
              "ORIGINAL" in body and "TAMPERED" not in body, body.strip())

        # ---- 只改字节数（截断）-> 也必须被拒 -----------------------------
        dest2 = os.path.join(work, "b2")
        manifest2 = mod.do_backup(dest2, install_dir, SCRATCH)
        reg2_path = os.path.join(dest2, mod.REG_FILE)
        with open(reg2_path, "rb") as fh:
            raw = fh.read()
        with open(reg2_path, "wb") as fh:
            fh.write(raw[:-4])                    # 少 4 字节
        rc = mod.do_restore(dest2, install_dir, True, os.path.join(work, "out2"))
        check("字节数不符（截断）-> 还原被拒绝", rc != 0, "rc=%s" % rc)

        # ---- 篡改 shortcuts.txt -> 还原必须被拒 --------------------------
        dest3 = os.path.join(work, "b3")
        mod.do_backup(dest3, install_dir, SCRATCH)
        sc_path = os.path.join(dest3, mod.SHORTCUTS_FILE)
        with open(sc_path, "a", encoding="utf-8") as fh:
            fh.write("C:\\Users\\x\\Desktop\\Sneaky.lnk\n")
        rc = mod.do_restore(dest3, install_dir, True, os.path.join(work, "out3"))
        check("篡改 shortcuts.txt -> 还原被拒绝", rc != 0, "rc=%s" % rc)

        # ---- 缺 manifest -> 拒绝 -----------------------------------------
        rc = mod.do_restore(os.path.join(work, "not-a-backup"), install_dir, True,
                            os.path.join(work, "out4"))
        check("没有 manifest 的目录 -> 拒绝", rc != 0, "rc=%s" % rc)

        # ---- 正常还原（正对照：完整性校验不该把好备份也拦下）------------
        dest4 = os.path.join(work, "b4")
        mod.do_backup(dest4, install_dir, SCRATCH)
        _reg("add", SCRATCH, "/v", "Marker", "/t", "REG_SZ", "/d", "CHANGED", "/f")
        check("正对照：先把键改成 CHANGED", "CHANGED" in _marker())
        rc = mod.do_restore(dest4, install_dir, True, os.path.join(work, "out5"))
        check("正对照：完整备份 -> 还原成功（rc 0）", rc == 0, "rc=%s" % rc)
        check("正对照：键确实被还原回 ORIGINAL", "ORIGINAL" in _marker(), _marker())
        check("正对照：还原前拍了 *-prerestore 快照",
              any(n.endswith("-prerestore") for n in os.listdir(os.path.join(work, "out5"))))

        # ---- (b) 快照导出失败 -> 还原必须中止 ----------------------------
        dest5 = os.path.join(work, "b5")
        mod.do_backup(dest5, install_dir, SCRATCH)

        class _FakeReg:
            """冒充 reg.exe：query 成功、export 失败、import 只记账。不碰真实注册表。"""

            def __init__(self):
                self.imports = []

            def __call__(self, *args):
                class _P:
                    returncode = 0
                    stdout = ""
                    stderr = ""
                p = _P()
                verb = args[0]
                if verb == "query":
                    p.stdout = "HKEY_CURRENT_USER\\Software\\...\r\n    Marker    REG_SZ    ORIGINAL"
                elif verb == "export":
                    p.returncode = 1
                    p.stderr = "ERROR: Access is denied."
                elif verb == "import":
                    self.imports.append(args)
                return p

        fake = _FakeReg()
        saved = mod._reg
        mod._reg = fake
        try:
            rc = mod.do_restore(dest5, install_dir, True, os.path.join(work, "out6"))
        finally:
            mod._reg = saved
        check("快照导出失败 -> 还原被拒绝（rc 非 0）", rc != 0, "rc=%s" % rc)
        check("快照导出失败 -> 一次 import 都没发生", fake.imports == [], fake.imports)
    finally:
        # 清理：删掉一次性测试键与临时目录。
        _reg("delete", SCRATCH, "/f")
        import shutil
        shutil.rmtree(work, ignore_errors=True)

    left = _reg("query", SCRATCH).returncode
    check("收尾：一次性测试键已删除（不再存在）", left != 0, "键仍在")

    print("\n%s" % ("ALL OK" if OK else "FAILED"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
