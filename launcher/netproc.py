#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「谁在监听这个端口，它是不是我们的进程？」—— 面板与安装器共用的一份判定。

纯标准库、不碰文件系统、不启动任何进程，所以可以直接单测。

**为什么要共用**：面板 `launcher.pyw` 的 `stop_server()` 一直只杀 `node.exe`
（commit 380b65b 的加固，`_is_node_process()`），而安装器**生成的
`uninstall.bat` 从来没有同步这条加固**——它按端口找到 PID 就直接
`taskkill /F /PID`，连被杀的进程是什么都不问。同一个仓库里对「端口上的进程」
存在两套强度不同的策略，其中生成出来的那一套更弱。
两边的判定都收到这里：`launcher.pyw` 和 `installer.py` 都从这里取，
这样「改了一处忘了另一处」不会再发生（`test-security.py` 里有用例钉住）。

**端口为什么不能按子串匹配**：`netstat` 里 `:3080` 是 `:30801` 的前缀。
面板旧写法 `f":{port}" in line` 和生成的 bat 旧写法 `findstr ":3080"`
都会把监听 `30800`~`30809` 的进程一起选中，然后杀掉。
"""
from __future__ import annotations

#: 面板的「停止」按钮和卸载脚本只认这个镜像名。杀任何别的进程都不是本程序的事。
NODE_IMAGE = "node.exe"


def port_findstr_pattern(port: int) -> str:
    """`findstr /R` 用的模式：只匹配 `:<port>`，**后面不能再跟数字**。

    `:3080` 之后必须跟一个非数字字符才算命中，所以 `:30801` / `:30800`
    不会命中——这正是旧写法 `findstr ":3080"` 的漏洞。
    netstat 的本地地址列后面总有空白（后面还有对端地址列），所以
    「端口正好在行尾」这种情况不会出现，`[^0-9]` 不会漏掉真的监听者。
    """
    return ":%d[^0-9]" % int(port)


def listening_pid(line: str, port: int) -> int | None:
    """`netstat -ano` 的一行里，监听**恰好** `port` 的 PID；不是就返回 None。

    按列判断而不是子串：第 2 列（本地地址）必须以 `:<port>` 结尾，
    这样 `0.0.0.0:30801` 不会被当成 `0.0.0.0:3080`。
    只认 LISTENING 行，所以端口出现在**对端**地址列（比如一条连到远端 3080
    的 ESTABLISHED 连接）不会被误判成本机监听。
    """
    toks = line.split()
    if len(toks) < 5:
        return None
    if not toks[0].upper().startswith("TCP"):
        return None
    if "LISTENING" not in toks[3].upper():
        return None
    if not toks[1].endswith(":" + str(int(port))):
        return None
    try:
        return int(toks[-1])
    except ValueError:
        return None


def listening_pids(netstat_output: str, port: int) -> list[int]:
    """整份 `netstat -ano` 输出里监听 `port` 的 PID（去重、保持顺序）。"""
    pids: list[int] = []
    for line in netstat_output.splitlines():
        pid = listening_pid(line, port)
        if pid is not None and pid not in pids:
            pids.append(pid)
    return pids


def tasklist_args(pid: int) -> list[str]:
    """`tasklist` 参数：只列这一个 PID 的那一行，CSV 格式，无表头。

    生成的 bat 里那句 `tasklist /FI "PID eq %%p" /FO CSV /NH` 就是这一份查询
    （见 `tasklist_batch_fragment()`），两处不能再各写一遍。
    """
    return ["/FI", "PID eq %d" % int(pid), "/FO", "CSV", "/NH"]


def tasklist_batch_fragment(pid_expr: str, exe: str = "tasklist") -> str:
    """同一份查询写成批处理片段；`pid_expr` 是 `%%` 变量（如 `%%p`）。

    `exe` 是「怎么调 tasklist」那一段。生成的卸载脚本传
    `%SystemRoot%\\System32\\tasklist.exe`（绝对路径、不带引号，见
    `installer._bat_sys32`），与仓库「系统命令一律走绝对路径」的策略一致
    （AW-5）。面板不用这个片段——它走 `tasklist_args()` 起子进程——默认值
    保留裸名只是为了让纯函数单测读起来干净。
    """
    args = tasklist_args(0)
    args[1] = "PID eq " + pid_expr
    return exe + " " + " ".join(('"%s"' % a) if " " in a else a for a in args)


def is_node_image(tasklist_output: str) -> bool:
    """`tasklist` 的输出里镜像名是不是 node.exe（大小写不敏感）。

    这就是「只杀 node.exe」那条策略的判定本体：端口上的进程可能是任何东西，
    「端口被别人抢到了」不是杀它的理由，对启发式杀软来说也无异于恶意行为。
    """
    return NODE_IMAGE in tasklist_output.lower()
