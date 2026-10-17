# 自动作业单 · dsh-installer-fornoob

> 本文件是自动作业的**唯一状态来源**。每次被唤醒时，先读本文件，找到「当前进度」里
> 第一个未完成的条目，做完、验证、提交、推送、勾选，然后停止。不要顺手做下一项。

## 硬性规则

1. **分支**：所有工作只在 `autowork/2026-10-16` 分支上。**永远不要碰 `main`**，
   不要 `force push`，不要改远端设置，不要删远端分支，不要动 tag。
2. **一次一项**：每轮只推进一个条目。做完就停。
3. **每项必提交并推送**：`git add` → `git commit -m "[AW-<编号>] <做了什么>"` → `git push`。
   **不 push 等于没做。** 代理已配好（`.git/config` 的 `http.proxy` = Clash `127.0.0.1:7897`）。
   ⚠️ **别用 `git remote show origin` 判断网络好坏**——它不走代理配置会失败，
   但 `git push` / `git fetch` 是通的（已实测）。
4. **每项必验证**：
   - `AW-0` 建好聚合 runner 之前：手跑受影响的那几个自检脚本，并在条目里写清跑了哪些。
   - `AW-0` 之后：跑 **`python scripts\selfcheck.py`**（聚合 runner，零依赖）。
   - 用例数**只增不减**，以「当前进度」区最新一条记录的数量为准。
   - **新增回归测试后，要临时撤掉修复验证它确实会变红**，再装回去。
     ⚠️ 做「撤掉修复」验证时**必须先确认回退本身生效了**（`git diff` 确认改动没了），
     否则得到的是假阳性——比不验证更糟。
5. **🔴 数据安全红线（最重要）**：本机**真的装了 DSH**，安装在
   **`C:\Users\sechen\deepseek`**，卸载注册项**真实存在**
   （`HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSeekHarness`，
   `DisplayVersion 0.2.0-rc.2`）。该安装根目录里除了安装器创建的
   `runtime/` `harness/` `launcher/`，还有一个**你自己放进去的 `repo/`**（DSH 源码树，
   含 `.claude`/`.agents`，**没有 git 历史，删了不可恢复**）。
   - **绝对不要运行 `C:\Users\sechen\deepseek\uninstall.bat`**。
     它的 `:695-696` 会删光安装根下所有文件和所有子目录——**`repo/` 会被一起删掉**。
     这不是理论风险，是这台机器上已确认的真实暴露面。
   - **绝对不要运行 `launcher\test-security.py`**，直到 AW-1 修完。
     它的第 5 项检查会**真的跑一次卸载脚本**，而它依赖的 `restore_registry`
     在 `reg export` 失败时会静默不还原（`test-security.py:70,77`），
     **有概率删掉本机真实的卸载注册项**。AW-1 修完之后再跑，
     且每次跑之前先手动 `reg export` 备份那个键。
   - **绝对不要**手工 `reg delete` 任何真实注册项，**绝对不要**动
     `%USERPROFILE%\.dsh`（那是用户数据：settings/sessions/profiles/storages）。
   - 涉及卸载脚本的测试，**一律在 `tempfile.mkdtemp()` 里生成脚本并运行**，
     绝不指向真实安装目录。
   - **绝不运行 `python installer\installer.py --auto` 不带 `--dir`**：
     `installer.py:786` 的默认 `target="."`，会把 runtime/harness 解到当前目录（可能就是这个仓库）。
     要跑就用 `--auto --dir .\dist\test-install`。
     ⚠️ 注意 `--auto` 只是 `test_mode`（跳过注册表和快捷方式），
     **它仍会真的解压 Node、真的跑 `npm install`、真的写日志**——不是 dry-run。
   - 跑任何安装/卸载类验证前，先备份：`reg export` 那个卸载键 +
     把 `C:\Users\sechen\deepseek\shortcuts.txt` 复制一份。
6. **同一项连续失败两次**就标记 `BLOCKED` 并写清原因，跳到下一项，不要死磕。
7. **不确定就跳过**：改产品行为、改交互、改发版流程这类需要用户决策的，记到「待确认」区。
8. **队列空了就停**：不要自己编条目凑数。
9. **本机环境**：Python 3.14.7，纯标准库（tkinter/ctypes），**没有第三方依赖**——
   **不要引入新依赖或测试框架**。自检脚本是自研的 `check()` + 退出码风格，沿用即可。
   需要 node 的测试（`test-linkcheck.py`）用 `DSH_TEST_NODE` 指定；需要桌面的
   （`test-layout.py`）在无头/无桌面环境下**跳过并报告**，不要判为失败。
10. **注意两处常见误解（勘察已核实）**：
    - **`dsh-linkprobe.js` 不在仓库里**（仓库历史上从未有过任何 `.js`/`.bat` 文件）。
      仓库内的探针是 `installer\linkcheck.py:69-111` 里的**内嵌 JS 字符串**，
      用 `node -e` 执行（刻意不落盘，避免被启发式杀软盯上）；临时目录名才叫 `.dsh-linkprobe`。
      另外**仓库外**的家目录下确实有一个一次性探针
      `C:\Users\sechen\dsh-linkprobe.js`（2026-09-21 写的，4.8 KB），
      那是给「装不上的那台机器」用的手工排查工具，**不属于本仓库，不要动它**。
    - **`uninstall.bat` 不在仓库里**，是安装时由 `installer\installer.py:658-704`
      （`InstallWorker._write_uninstaller`）生成的。要改就改那段 Python，
      改仓库里某个 bat 是改不到的。
    - 「符号链接/提权理论」在代码里已是**结案状态**（`installer\installer.py:118-128`、
      `linkcheck.py:1-31`），**不要再把它当 backlog 项**。
11. **`launcher.pyw` 的 VERSION 是 1.5.9，但最新 tag 只有 v1.5.7**——发版流程已漂移，
    这是已知问题（见 AW-11），**不要在本作业里擅自发 tag 或改版本号**。

## 背景

把 npm 上的 `@deepseek-ai/dsh` 一键装到 Windows 的图形化安装器 + 常驻启动器。
Python 3 纯标准库 + PyInstaller onefile 打包；PowerShell 建快捷方式；
`uninstall.bat` 是**运行时生成**的。用户数据在 `%USERPROFILE%\.dsh`，安装器不碰它。

**勘察结论（2026-10-16 人工审计，非猜测）**：
- 仓库**已有 6 个自检脚本**（`launcher\test-updater.py` / `test-security.py` /
  `test-layout.py` / `test-github-probe.py`、`installer\test-linkcheck.py`、
  `launcher.pyw --selftest*`），每个自带 `check()` 断言和退出码——**但没有任何聚合入口，
  也没有 CI**，全靠人手逐个跑，所以实际上没人跑。
- 最严重的问题是**生成的卸载脚本会删光安装根下的一切**，而守卫只要求
  `launcher\DSHLauncher.exe` / `harness` / `runtime` **三者任一存在**即放行，
  而 `runtime` 是极常见的目录名。
- 第二严重的是**跑一次自检就可能删掉本机真实的卸载注册项**（见规则 5）。
- 好消息：卸载**不碰** `%USERPROFILE%\.dsh`，README 里「卸载不会删你的设置/密钥/会话」
  是**真的**；它删的注册表项是**它自己创建的那一个**，不碰 HKLM/PATH/文件关联。

**顺序是刻意排的**：先建聚合验证入口（AW-0），再修会毁数据的（AW-1/AW-2/AW-3），
再修安全策略不一致（AW-4/AW-5/AW-6），然后正确性（AW-7~AW-10），最后文档与供应链（AW-11~AW-14）。

## 当前进度

- [x] **AW-0 建聚合自检入口 + 备份护栏（可验证性）** —— 后面所有条目的前提，必须第一个做。
      两件事：
      (a) **`scripts\selfcheck.py`**：零依赖聚合 runner，依次调用现有的
      `installer\test-linkcheck.py`、`launcher\test-updater.py`、`launcher\test-security.py`、
      `launcher\test-github-probe.py`、`launcher\test-layout.py`，
      逐个捕获退出码与输出，最后打印汇总表并以**非零退出码**表示有失败。
      **必须支持跳过**：需要 node 的、需要桌面的、需要联网的在缺条件时标 `SKIP` 并说明原因，
      不要判失败（本机是无头/可能无桌面环境）。要能只跑指定的某一项（如 `--only updater`）。
      ⚠️ **`test-security.py` 在 AW-1 修完之前必须默认 SKIP**，
      理由写在脚本注释里（会动真实注册项）。修完 AW-1 后改成默认运行。
      (b) **`scripts\backup-dsh-registry.py`**（或 `.bat`）：把
      `HKCU\...\Uninstall\DeepSeekHarness` 和 `C:\Users\sechen\deepseek\shortcuts.txt`
      备份到一个带时间戳的目录，并支持 `--restore` 还原。这是规则 5 要求的护栏，
      必须在 AW-1/AW-2 动卸载逻辑之前就能用。
      顺手在 `README.md` 加一节说明这两个脚本。
      完成标准：`python scripts\selfcheck.py` 能跑完并给出汇总；
      故意改坏一处被测逻辑能让对应用例变红（验证测试真的有效）。
      验证后把「跑了几项、几项 SKIP」记到本条目末尾。

      **实际结果（2026-10-17，commit 72d09f1）**：`python scripts\selfcheck.py`
      跑完 **5 项：4 通过，0 失败，1 跳过**，退出码 0。通过的是 linkcheck(0.2s) /
      updater(7.7s) / github-probe(0.4s) / layout(13.0s)；**SKIP 的 1 项是
      security**（按设计默认跳过，理由写在脚本里：会真跑一次卸载脚本、动本机真实
      注册项，AW-1 修完前不放行）。
      跳过路径都实测过：把 node 从 PATH 里去掉并清空 `DSH_TEST_NODE` → linkcheck 标
      SKIP 并说明原因；打桩让 `import tkinter` 失败 → layout 标 SKIP；
      `--only security` 同样只 SKIP，要真跑必须再显式加 `--allow-security`。
      **「改坏被测逻辑」验证**：在 `installer\linkcheck.py:431` 前插一行
      `return None`（把 `verdict()` 改坏），先 `git diff` 确认改动确实在位，
      再跑 selfcheck → **linkcheck 14 条断言变红、退出码 1**；然后
      `git checkout -- installer\linkcheck.py` 回退，`git diff` 为空、
      且与改坏前的逐字节备份 `diff` 一致（确认回退本身生效，不是假阳性），
      重跑 selfcheck → 恢复全绿。
      **备份护栏**：`scripts\backup-dsh-registry.py` 对真实卸载键跑了一次
      `reg export`（只读，成功，950 字节、含键名）；「备份 → 改坏 → 还原」整条链路
      用一个一次性临时键（`HKCU\Software\DSHBackupSelfTestScratch`，验证完已删除）
      跑通，17 条断言全过，其中包含「空备份文件被拒」「没有 `--yes` 时不还原」
      两条负向用例。**真实卸载键 `reg query` 输出在验证前后逐字节一致，未被改动；
      `C:\Users\sechen\deepseek\repo` 完好。** 本条目全程没有运行
      `uninstall.bat`，也没有运行 `launcher\test-security.py`。
      ⚠️ 顺手修了两处验证中暴露的问题：`input()` 在 Windows 上 NUL 设备也被
      `isatty()` 判为 True，重定向到空设备时会抛 `EOFError`（已捕获并按「不还原」
      处理）；`mentions_key` 原先硬编码键名，`--reg-key` 下会误报。

- [x] **AW-1 修 `test-security.py` 的注册表还原静默失效（会删真实注册项，最高优先级）**
      问题：`launcher\test-security.py:62-70` 的 `snapshot_registry()` 在 `reg export` 失败时
      返回**空字符串**，而 `:73-80` 的 `restore_registry()` 里 `elif backup:` 对空串不成立
      → **静默什么都不做**。该文件 `:15-17` 的注释自己承认写这个测试时真的发生过。
      本机该键**真实存在**，所以跑一次自检就有概率删掉用户 DSH 的卸载入口。
      修法：把 `reg export` 失败**当成致命错误**——直接中止测试并明确报错，
      **绝不在备份不可靠的情况下继续跑卸载脚本**。同时：
      - `reg export` 后**校验备份文件确实存在且非空**，并校验能 `reg query` 到导出内容；
      - `restore_registry` 里 `reg import` 的返回码**必须检查**，失败要报错而不是静默；
      - 备份文件路径带时间戳，别固定用 `dsh-uninstall-backup.reg`（两次跑会互相覆盖）。
      新增用例：模拟 `reg export` 失败 → 断言**不执行卸载检查**且报错退出；
      模拟 `reg import` 失败 → 断言报错。**这些用例不能真的动注册表**，用打桩。
      修完把 `scripts\selfcheck.py` 里 `test-security.py` 的默认 SKIP 去掉。

      **实际结果（2026-10-17，commit f8d5c75）**：
      `launcher\test-security.py` 注册表护栏重写：
      - `snapshot_registry()`：`reg export` 失败不再返回空串，改抛 `RegistryBackupError`；
        导出后校验备份**存在且非空**、内容含键名（按 UTF-16-LE 读）；路径带时间戳+pid
        （`dsh-uninstall-backup-<stamp>-<pid>.reg`），两次跑不再互相覆盖。
      - `restore_registry()`：`reg import` 返回码**必查**，非 0 抛 `RegistryRestoreError`
        （并提示可用 `scripts\backup-dsh-registry.py --restore` 手工恢复）。
      - 新增 `run_with_registry_guard()`：先备份 → 跑卸载检查 → 还原；**备份拿不到就抛异常、
        绝不调用卸载检查**。`main()` 第 5 项改走它（原来裸调 `snapshot_registry`）。
      - 新增第 0 段自测（`_FakeReg` 打桩，**不碰真实注册项**）：0a 模拟 export 失败 →
        断言抛 `RegistryBackupError` 且卸载检查**没跑**；0b 模拟 import 失败 → 断言抛
        `RegistryRestoreError`。用例数 **17 → 21**。
      - `scripts\selfcheck.py`：`SECURITY_SKIP_REASON` 改 `None`，删掉 `--allow-security`
        开关与 `select()` 里的相应分支；README 去掉过时的「默认跳过/--allow-security」说明。
      **验证**：
      - `python scripts\selfcheck.py` → **5 项：5 通过，0 失败，0 跳过**，退出码 0
        （security 现在默认运行，2.4s，21 条断言全过；此前为 1 跳过）。
      - **撤掉修复验证**：字节备份留底 → 把 snapshot/restore 改回旧的静默行为（保留签名），
        `git diff --no-index` 确认**回退真的生效**（`raise` 与 import 返回码检查那几行没了）
        → 跑 `test-security.py`：**3 条新断言变红**（export 失败未报错 / export 失败仍跑了
        卸载检查 / import 失败未报错），退出码 1；再从字节备份还原、`git diff --no-index`
        为空（确认还原生效），重跑恢复全绿。
      **数据安全**：全程未运行 `C:\Users\sechen\deepseek\uninstall.bat`；卸载脚本只在
      `tempfile` 临时目录里生成并运行（守卫会拦下，不删东西）。真实卸载键在验证前后
      `reg export` **逐字节一致**（sha256 `945beecb…3ede`，与 `scripts\backups\` 的备份相同）；
      `C:\Users\sechen\deepseek\repo` 完好。

- [x] **AW-2 修卸载脚本的弱守卫与无差别删除（数据安全，最高优先级）**
      问题两处（生成的脚本，源在 `installer\installer.py`）：
      (a) `:673-679` 的守卫是 **OR** 语义：`launcher\DSHLauncher.exe`、`harness`、`runtime`
      **任一存在**就认定「这是 DSH 安装目录」并继续。`runtime` 是极常见的目录名——
      用户用「浏览」把安装目录指到一个已有 `runtime\` 的目录，守卫直接放行。
      (b) `:695-696` 接着**删光该目录下所有文件和所有子目录**，不只是 DSH 自己创建的那几个。
      本机的 `repo/`（DSH 源码树，无 git 历史）就是会被这样删掉的实例。
      修法：
      - 守卫改为**必须**存在安装标记——`harness\.dsh-installed.json`
        （`MARKER_NAME`，`installer.py:102` 已有）或安装器额外写一个根标记文件；
      再辅以「三者全部缺失就拒绝」作为兜底。**从 OR 改成 AND/标记制**是这一项的核心。
      - `:695-696` 改为**白名单删除**：只删安装器自己创建的
        `launcher` `harness` `runtime` `uninstall.bat` `shortcuts.txt` `install.log` `smoke.log`
        （以及安装器新加的标记文件）；遇到白名单外的条目**列出来并保留**，
        提示用户「这些不是安装器创建的，未删除」。
      - 老版本安装（没有标记文件）怎么办要**明确设计**：
        建议「无标记 + 三者不全 → 拒绝；无标记 + 三者全在 → 警告后按白名单删」，
        并把这个判断写成可单测的纯函数。
      新增用例（**必须在 tempfile 目录里造目录结构，绝不指向真实安装目录**）：
      目录里只有一个 `runtime\` → 断言守卫**拒绝**；目录里有 `harness\.dsh-installed.json`
      → 断言放行；目录里有 `repo\`（白名单外）→ 断言 `repo\` **被保留**、其余按白名单删除。

      **实际结果（2026-10-17，commit 5b5d1e6）**：
      - **守卫**：`installer.py` 新增纯函数 `uninstall_verdict(entries, marker_present)`
        （无文件系统访问，直接可单测），策略 =「有标记 `harness\.dsh-installed.json`
        → `proceed`；无标记但 `launcher`+`harness`+`runtime` 三者全在 → `proceed-legacy`
        （警告后放行）；否则 `reject`」。生成的 bat 里旧的 OR 守卫
        （`if not exist ... if not exist ...`）整段删除，换成
        `if exist "%~dp0harness\.dsh-installed.json" goto :guard_ok` + 三条 `goto :reject`
        + 老版本警告分支。
      - **删除改白名单**：`:695-696` 的「删光所有文件 + `for /d … rmdir /s` 删光所有子目录」
        换成只删 `UNINSTALL_DIRS`(`launcher`/`harness`/`runtime`) 与
        `UNINSTALL_FILES`(`shortcuts.txt`/`install.log`/`smoke.log`；`uninstall.bat` 结尾自删)，
        常量与纯函数共用同一份。白名单外的条目用 `dir /b /a | findstr /v /i /x "uninstall.bat"`
        列出来并置 `KEPT=1`，打印「LEFT IN PLACE」。
      - **根目录**：原来无条件 `start … rmdir /s /q "%DIR%"`（会把保留下来的条目一起删），
        改成 `if "%KEPT%"=="0"` 才删——有保留项时安装目录本身也留着。
        （它和 `:700` 自删的先后竞态仍归 AW-8，这里只保证「有保留项就不递归删根」。）
      - 顺带：`_write_uninstaller` 的 docstring 改成与实现一致（原说法「自删通过 detached
        进程完成」不实）；`_install()` 新增 `_warn_foreign_entries()`，装的时候就把
        「安装目录里已有的非 DSH 条目、卸载时会保留」写进 `install.log`（也让纯函数有个
        真实调用点）；README「5. 卸载」与自检说明同步改成白名单措辞。
      **验证**：
      - `python scripts\selfcheck.py` → **5 项：5 通过，0 失败，0 跳过**，退出码 0。
      - `launcher\test-security.py` 断言数 **21 → 43**（+22：纯函数 7 条、卸载脚本行为 14 条、
        第 5 项 reject 用例补 1 条）。
      - **撤掉修复验证**：字节备份留底 → 把 `uninstall_verdict` 改回 OR 语义、
        `_write_uninstaller` 的守卫与删除改回旧的（`grep` 确认新标记守卫与 `LEFT IN PLACE`
        计数为 0、旧 OR 守卫与 `dir /b /a-d` 为 1，即回退确实生效）→ 跑 `test-security.py`：
        **10 条变红**（纯函数 4 条 + 行为 6 条，含「只有一个 runtime\ → 拒绝」「repo\ 被保留」
        「老版本 repo\ 仍保留」「保留的条目被列出来」），退出码 1；再从字节备份还原、
        sha256 与备份逐字节一致（`bbc50726…`），重跑 selfcheck 恢复全绿。
        （附带发现：旧脚本结尾那条无条件的 `start … cmd /c rmdir` 会让调用方管道一直不关——
        实测 25s 不返回，`_run_bat` 靠 60s 超时兜住；这条归 AW-8。）
      **数据安全**：全程未运行 `C:\Users\sechen\deepseek\uninstall.bat`（它仍是 09-24 的旧版、
      1659 字节，未改动）；所有卸载脚本用例都在 `tempfile.mkdtemp()` 里造结构并生成脚本，
      且 `_isolated_env()` 把 `PATH`/`SystemRoot`/`USERPROFILE`/`APPDATA`/`OneDrive` 全部改道
      到临时目录，脚本里的 `taskkill`/`netstat`/`reg` 与快捷方式清理都成了空操作，外面还套着
      注册表备份/还原护栏。真实卸载键在验证前后 `reg export` **逐字节一致**
      （sha256 `945beecb…3ede`，与 `scripts\backups\` 的备份相同）；
      `C:\Users\sechen\deepseek\repo`（含 `.claude`/`.agents`）完好。
      ⚠️ **残留风险（重要）**：`uninstall.bat` 是**安装时生成**的，本机那份旧脚本**不会**自动
      变安全——`repo\` 的实际暴露面仍在，直到重装或手工重新生成。我没有写真实安装目录
      （规则 5 的红线，且那样会连带改 `install.log`），这一步留给用户决定。
      （另注：`diag-*.txt`、`harness.old\` 等安装器/更新器产生的条目不在白名单里，会被保留
      并列出——按条目给定的白名单严格执行，保留是安全的方向。）

- [x] **AW-16 对齐纯函数与 bat 的守卫判定 + 补 KEPT=0 覆盖（AW-2 复查实测，潜在陷阱）**
      > 编号后补，位置在此 = 排在 AW-2 之后、AW-3 之前。

      AW-2 的对抗性复查确认「修复够格」（43 条断言锁住、反向回退 11 红、
      白名单确实保住外来条目、测试隔离彻底到连 `taskkill`/`netstat`/`reg` 都成空操作）。
      但发现**一个真不一致**：
      - 纯函数 `uninstall_verdict`（`installer.py:145`）的老版本兜底只看**三个目录名**：
        `set(UNINSTALL_DIRS) <= names`；
      - 生成的 bat（`:751` 起）的老版本兜底**还多查一个文件**：
        `if not exist "%~dp0launcher\DSHLauncher.exe" goto :reject`。
      对同一个「只有三个同名目录、无标记」的输入，纯函数返回 `proceed-legacy`
      （会白名单删掉那三个），bat 却 `reject`（什么都不删）。
      而 docstring（`installer.py:121-122`、`:740`）声称
      「`_write_uninstaller()` bakes the same policy」——**这句不实**：
      **白名单常量是共用的（不会漂移），守卫逻辑却是两处各写一份、且已经漂移**。
      严重性：**低/潜在**。方向是安全的（bat 比纯函数更严，bat 的接受集 ⊆ 纯函数），
      且 `uninstall_verdict` 目前唯一调用点是 `_warn_foreign_entries()`（只打印一行日志），
      没有任何破坏性路径用它。但**将来若有人把 `uninstall_verdict` 接到真正的删除动作
      （比如写个 Python 卸载器），那个滥用场景就成立了**——复查实测过：
      一个跟 DSH 无关、恰好有 `launcher\`+`harness\`+`runtime\` 三个子目录的目录，
      纯函数会判 `proceed-legacy`。
      修法（二选一，写清理由）：让纯函数也查 `launcher\DSHLauncher.exe`，
      或把 bat 的额外 exe 要求写进文档并补测试。**改完 docstring 必须与实现一致。**
      另外补一条**测试覆盖空白**：`KEPT=0`（无保留项）时删除根目录那条路径**没有覆盖**——
      在测试的隔离环境里 `cmd` 被从 PATH 拿掉，`start … cmd /c rmdir` 变成空操作
      （这也正是 AW-8 记的管道挂起现象）。建议给 stub PATH 补上 `cmd.exe` 并补一条用例。

      **实际结果（2026-10-17，commit 0273a62）**：
      - **修法选「让纯函数也查那个 exe」**（二选一里的第一个）。理由：生成的 bat
        本来就更严、接受集 ⊆ 纯函数，把纯函数对齐到 bat 才能让 docstring 里那句
        「bakes the same policy」**变真**，并**根除**那个潜在滥用面（将来谁把
        `uninstall_verdict` 接到真正的删除动作，也删不掉东西）；另一个选项（只把
        bat 的额外要求写进文档 + 补测试）会让两处守卫继续各写一份、把陷阱留在原地。
      - `uninstall_verdict(entries, marker_present, launcher_exe_present=False)`：
        legacy 判定改成 `set(UNINSTALL_DIRS) <= names and launcher_exe_present`，
        与 bat 的 `if not exist "%~dp0launcher\DSHLauncher.exe" goto :reject` 一致。
        唯一调用点 `_warn_foreign_entries()` 改为传真实的 `launcher\DSHLauncher.exe`
        存在性。`uninstall_verdict` 的 docstring（`installer.py:117-165`）与
        `_write_uninstaller` 的 docstring（`:756-760`）都按实现重写，不再有
        「同一策略」的不实说法。
      - **KEPT=0 覆盖**：`_isolated_env()` 的 stub PATH 补上 `cmd.exe`
        （原来只有 `findstr.exe`），新增 `clean-install` 用例——装完只剩白名单条目，
        断言脚本跑到底、无保留项、且安装根目录被 `start /b cmd /c rmdir` 删掉
        （轮询等待，实测稳定）。`taskkill`/`netstat`/`reg` 仍不在 PATH 里，保持空操作。
      - **滥用场景固化**：纯函数层 + 生成的 bat 层各加用例——一个跟 DSH 无关、
        恰好有 `launcher\`+`harness\`+`runtime\` 三个子目录的目录，两层都断言拒绝、
        目录一根汗毛不动。
      **验证**：
      - `python scripts\selfcheck.py` → **5 项：5 通过，0 失败，0 跳过**，退出码 0。
      - `launcher\test-security.py` 断言数 **43 → 50**（+7：纯函数 3 条、滥用场景行为
        2 条、KEPT=0 行为 3 条；其中 1 条替换了旧的 legacy 断言）。
      - **撤掉修复验证**（两次，每次先 `git diff` 确认回退真的在位）：
        (a) 把 legacy 判定改回 `set(UNINSTALL_DIRS) <= names`（`git diff` 确认
        `and launcher_exe_present` 没了）→ 跑 `test-security.py`：**1 条变红**
        （「只有三个同名目录、没有 exe → 拒绝」），退出码 1；从字节备份还原、
        sha256 一致（`e6c92a34…`），重跑恢复全绿。
        (b) 把 stub PATH 里的 `cmd.exe` 去掉（`git diff` 确认那行没了）→ 跑
        `test-security.py`：**2 条变红**（「无保留项：脚本跑到底」「无保留项：安装
        根目录被删掉」），且这一版会撞上 AW-8 记的管道挂起、单跑超过 60s 被
        `_run_bat` 的超时兜住；从字节备份还原、sha256 一致（`fd5855b3…`），
        重跑 3 次全绿。
      **数据安全**：全程未运行 `C:\Users\sechen\deepseek\uninstall.bat`（仍是新版，
      未改动）；卸载脚本用例都在 `tempfile.mkdtemp()` 里造结构并生成脚本。真实卸载键
      在验证前后 `reg export` **逐字节一致**（sha256 `945beecb…3ede`，与
      `scripts\backups\` 的备份相同）；`C:\Users\sechen\deepseek` 仍是
      `harness launcher runtime install.log shortcuts.txt uninstall.bat`；
      `C:\Users\sechen\dsh-src` 完好。

- [x] **AW-3 拒绝盘根与系统目录作为安装目录（数据安全）**
      问题：`installer\installer.py:668-669` 把 `DIR=%~dp0` 去掉结尾反斜杠，
      盘根会退化成 `D:`；`:699` 的 `rmdir /s /q "\\?\D:"` 是非法路径；
      `:695-696` 会以盘根为目标。**当前没有任何「拒绝盘根/系统目录」的检查。**
      修法：安装时（`_begin` / `_browse` 附近）加校验，拒绝：
      盘根（如 `D:\`）、`%SystemRoot%`、`%ProgramFiles%`、`%USERPROFILE%` 本身、
      以及桌面/文档根这类「用户会往里放东西」的目录。拒绝时给出**可操作的提示**
      （建议装到 `C:\Users\<你>\DSH` 这样的专属子目录）。
      判断逻辑抽成**可单测的纯函数**（如 `is_unsafe_target(path)`）。
      新增用例：`D:\` / `C:\Windows` / `C:\Program Files` / `C:\Users\sechen` → 断言拒绝；
      `C:\Users\sechen\DSH` / `C:\Users\sechen\deepseek` → 断言允许。

      **实际结果（2026-10-17，commit 204b857）**：
      - **判定规则**（纯函数 `is_unsafe_target(path, env=None)`，无文件系统访问）：
        先 `_canonical_target()` 归一化（去空白/成对引号、`/`→`\`、剥掉 Win32
        `\\?\` / `\\.\` 字面前缀、`normpath` 折叠 `.`/`..`/重复分隔符/尾分隔符），
        然后**只拒绝下列目录「本身」**（大小写不敏感）：
        ① **盘根**——`splitdrive` 后剩余部分为空或只有一个分隔符（`D:\`、`C:`、
        以及卸载脚本自己用的 `\\?\D:\`；UNC 共享根同理）；
        ② `%SystemRoot%` / `%windir%`；
        ③ `%ProgramFiles%` / `%ProgramFiles(x86)%` / `%ProgramW6432%`；
        ④ `%USERPROFILE%` 本身；
        ⑤ **桌面/文档根**——`%USERPROFILE%\Desktop|Documents`、`%OneDrive%\
        Desktop|Documents`（含 OneDriveCommercial/Consumer 与
        `%USERPROFILE%\OneDrive\...` 变体）。
        **它们里面的子目录一律放行**（这正是要的安装位置）：`C:\Users\sechen\DSH`、
        以及本机真实安装目录 `C:\Users\sechen\deepseek` 都必须**允许**（已钉进用例）。
        `env` 可注入，便于在任意机器上得到同一结论；默认 `os.environ`。
      - **接线**：`_begin`（点「开始安装」时，在覆盖确认之前）与 `_browse`（选目录当场）
        各自 `os.path.abspath()` 后校验，命中即弹 `showerror` 并**不继续**；
        `_run_auto`（`--auto` CLI 路径）在 `preflight.run` 之前校验，命中打印
        `ERROR 安装目录不可用：…` 并返回**退出码 2**。拒绝文案由
        `unsafe_target_message()` 生成，含「请改成一个专门为 DSH 新建的子目录，
        例如 `C:\Users\<你的用户名>\DSH`」。
      - **用例**：`launcher\test-security.py` 新增 `_check_target_policy()`（第 4b 段，
        放在注册表护栏**之外**，永远会跑；纯函数不碰注册表）。断言数 **50 → 75（+25）**：
        15 条拒绝（`D:\`、`C:\`、`C:`、`\\?\D:\`、不存在的 `Z:\`、`C:\Windows`、
        带尾反斜杠、大小写变体、`C:\Program Files`、`C:\Program Files (x86)`、
        `C:\Users\sechen`、经 `..` 绕回 USERPROFILE、Desktop、Documents、
        OneDrive\Documents）+ 提示文案可操作 + 4 条允许（`…\DSH`、**`…\deepseek`**、
        `…\Documents\DSH`、未创建的路径）+ 用**真实 env** 钉住「USERPROFILE 本身被拒 /
        其下 DSH 子目录被允许 / SystemRoot 被拒」+ 空路径不算 unsafe。
      - **验证**：
        - `python scripts\selfcheck.py` → **5 项：5 通过，0 失败，0 跳过**，退出码 0
          （security 2.5s，75 条断言全过）。
        - **撤掉修复验证**（定点破坏，非超集回退）：字节备份留底（sha256
          `3458bbae…`）→ 只把 `is_unsafe_target` 的返回改成恒 `False`
          （`git diff` 确认 `+ return False  # AW-3 targeted break` 确实在位）→
          跑 `test-security.py`：**17 条变红**（15 条拒绝路径 + 真实 USERPROFILE +
          真实 SystemRoot；提示文案那条仍绿，因为它读的是 `_unsafe_target_kind`
          而非 `is_unsafe_target`），退出码 1 → 从字节备份还原、sha256 与备份
          **逐字节一致**、`grep "targeted break"` 无命中（确认还原本身生效，不是假阳性）
          → 重跑恢复全绿 75 条。
      - **数据安全**：全程未运行 `C:\Users\sechen\deepseek\uninstall.bat`（仍是
        3142 字节、2026-10-17 11:48 的版本，未改动）；本项只加校验、不跑安装也不跑卸载，
        新增用例全是纯函数单测（不造目录、不碰注册表）。真实卸载键在验证前后
        `reg export` **逐字节一致**（sha256 `945beecb…3ede`，与 `scripts\backups\`
        三份备份相同）；`C:\Users\sechen\deepseek` 仍是
        `harness launcher runtime install.log shortcuts.txt uninstall.bat`；
        `C:\Users\sechen\dsh-src`（原 `repo\`）完好。
      - **文档**：README「1. 安装」第 2 步补一句：盘根 / `C:\Windows` /
        `C:\Program Files` / 用户主目录本身 / 桌面文档目录会被当场拒绝并提示。

- [ ] **AW-4 修卸载按端口子串杀进程（安全策略不一致）**
      问题：`installer\installer.py:682` 用 `netstat -ano | findstr ":3080" | findstr LISTENING`
      再 `taskkill /F /PID`。`findstr ":3080"` 是**子串匹配**，`:30800`~`:30809`
      这些端口的监听进程都会被误杀；且**没有 `/IM node.exe` 之类的镜像名校验**。
      而 `launcher\launcher.pyw:406-420`（`stop_server`）**已经做了** `_is_node_process()` 过滤，
      commit `380b65b` 的说明明确写着「只杀 node.exe」——**这条加固没同步到生成的 uninstall.bat**，
      是本仓库里最明确的「应该对齐却没对齐」。
      另外它用 `taskkill /F /PID`（无 `/T`），与项目其它地方（`:644`、`launcher.pyw:423`）不一致。
      修法：对齐 `launcher.pyw` 的做法——先按镜像名校验确认是 node 进程，再杀；
      端口匹配改成**精确匹配**（`:3080` 后不能再跟数字）；补 `/T`。
      把「端口匹配」抽成可单测的纯函数，并复用 `launcher.pyw` 里已有的进程判定逻辑
      （如果那份逻辑能抽出来共用，就抽出来——**不要复制两份**）。
      新增用例：`:3080` / `:30801` / `:30800` / `:3080` 带别的格式 → 断言只有精确的 `:3080` 命中；
      非 node 进程 → 断言不杀。

- [ ] **AW-5 让生成的 bat 全走绝对路径（安全策略不一致）**
      问题：`:681,682,693` 用裸命令名（`taskkill`/`netstat`/`reg`），生成的 bat 里
      `findstr/dir/del/rmdir/cmd` 也全是裸名；而项目其它所有地方都走
      `%SystemRoot%\System32\...` 绝对路径（`installer.py:61-69` 的 `_SYS32`），
      `README.md:460-461` 把这条写成**安全原则**。这是与自身策略不一致的真实缺口（PATH 劫持面）。
      修法：生成的 bat 里所有系统命令改为 `%SystemRoot%\System32\<命令>.exe` 形式
      （注意 bat 里引用需正确处理引号与 `%` 转义）。
      新增用例：断言生成的 bat 文本**不含**裸命令调用（用正则扫生成的脚本文本，
      这是纯文本断言，不需要真跑脚本）。

- [ ] **AW-6 去掉通配删除与整目录递归删（数据安全）**
      问题两处：
      (a) `:685-686` 用 `del /q "%USERPROFILE%\Desktop\DSH*.lnk"` 通配删桌面快捷方式，
      会删掉任何用户自己起名叫 `DSH...` 的快捷方式；而 `:684` **已经有** `shortcuts.txt`
      精确清单（`installer.py:766-772` 写入），这两行**完全多余**。
      (b) `:691` `rmdir /s /q "...\Start Menu\Programs\DSH"` 递归删整个开始菜单文件夹，
      若用户在该文件夹里放过别的快捷方式，一并被删。
      修法：(a) 直接删掉这两行，只保留 `shortcuts.txt` 精确删除；
      (b) 改为只删 `shortcuts.txt` 里记录的项，然后**不带 `/s`** 的 `rmdir` 删空目录
      （删不掉说明里面有别的东西，那就留着）。
      新增用例：构造 `shortcuts.txt` + 一个同目录下**不在清单里**的 `DSH其他.lnk`
      → 断言后者被保留（在 tempfile 里做）。

- [ ] **AW-7 修 `shortcuts.txt` 的编码陷阱（正确性，会让成功安装被误判失败）**
      问题：`installer\installer.py:769-771` 用 `encoding="mbcs"` 写 `shortcuts.txt`，
      而 `except` **只捕获 `OSError`**。用户名/桌面路径含当前 ANSI 代码页之外的字符时，
      `UnicodeEncodeError`（`ValueError` 子类）会逃出去 →
      **在进度 97% 处把一次已经成功的安装判为失败**（连快捷方式都已经建好了）。
      修法：改 `encoding="utf-8"`，并同步处理 bat 侧的读取
      （`for /f` 读 UTF-8 需要配 `chcp 65001`，或者改用能容忍的方式）；
      至少也要把 `except` 扩成 `except (OSError, UnicodeError)` 兜底。
      **两种方案选哪个要写清理由**，并注意 bat 是 ASCII-only 的（`test.bat` 头部注释说
      cmd.exe 会搞坏非 ASCII 批处理）——生成脚本时别引入非 ASCII 字面量。
      新增用例：模拟写入时抛 `UnicodeEncodeError` → 断言被处理（不逃逸）；
      断言写出的文件编码是 UTF-8 且内容可被 `utf-8` 读回。

- [ ] **AW-8 修卸载收尾的竞态（健壮性）**
      问题：`:699` 用 `start "" /b cmd /c rmdir /s /q "\\?\%DIR%"` 异步删根目录，
      紧接着 `:700` `del "%~f0"` 自删；两者并发，若异步 cmd 先执行，
      `uninstall.bat` 还在，根目录删不掉 → **残留一个空安装目录**。
      且 `:661-662` 的 docstring 说「自删通过 detached 进程完成」，
      与实际代码（detached 进程删的是**目录**，自删是普通 `del`）**不符**。
      修法：改成明确的顺序——先自删或先把脚本移到临时位置，再删目录；
      或让 detached 进程在删目录前先删脚本。**同时把 docstring 改成与实现一致**。
      新增用例：断言生成的 bat 里「删目录」与「自删」的先后关系符合设计
      （文本级断言 + 在 tempfile 里真跑一次生成脚本验证目录确实被删干净）。

- [ ] **AW-9 修 `--dir` 缺值的崩溃与 `--auto` 的危险默认值（正确性）**
      问题两处：
      (a) `installer.py:787-788` 与 `:1189-1190` 用 `argv[argv.index("--dir") + 1]`
      取参数值，**没有边界检查**——`--dir` 后无值会 `IndexError`；
      在 windowed exe 里表现为**静默无反应**（用户完全不知道发生了什么）。
      (b) `:786` 的 `--auto` 默认 `target="."`，从仓库根误跑会把 `runtime`/`harness`
      解到仓库里。**本作业单的规则 5 已经把这条列为红线**，这里从代码上根除它。
      修法：(a) 加边界检查并给出**可读的错误信息**（windowed 模式下要有弹窗或写日志，
      不能静默）；(b) 把 `--auto` 的默认目标改成临时目录（或直接要求必须显式传 `--dir`）。
      ⚠️ 改默认值会影响 `README.md:337-373` 里的自检命令，**要同步更新文档**。
      新增用例：`--dir` 无值 → 断言返回可读错误而非 `IndexError`；
      不传 `--dir` → 断言不再落到当前目录。

- [ ] **AW-10 修 `linkcheck.py` 的恒真分支（正确性）**
      问题：`installer\linkcheck.py:611`
      `out.extend("  " + l for l in _excerpt(text, 10 if verdict else 20))` ——
      `verdict` 是**函数对象**（定义在 `:420`），**恒为真** → 永远取 `10`，
      `20` 这个分支永远走不到。上下文（`:551` 已有 `found = verdict(report)`）表明
      本意是 `10 if found else 20`。
      修法：改为 `10 if found else 20`（复用已算出的 `found`，不要重复调用）。
      新增用例：构造 `found` 为真/假两种输入 → 断言截取行数分别是 10 / 20。
      ⚠️ 这个函数可能被别处调用，改完跑全量自检确认没有别的测试依赖了旧行为。

- [ ] **AW-11 对齐 README/文档与实现（文档，注意区分「文档错了」还是「代码错了」）**
      五处不一致（**以代码为准**改文档，除非某处明显是代码退化）：
      (a) `README.md:474`（与 `:211`）声称 `--diag`「不创建安装目录」，
      但 `installer.py:1211` → `preflight.run(target)` → `preflight.py:712` →
      `_check_target`（`preflight.py:453-460`）会 `os.makedirs(target, exist_ok=True)`
      并写/删 `.dsh-write-test`。**实测行为与文档相反**，`installer.py:1184-1186` 的
      docstring 同样有问题。
      (b) `README.md:142` 把 `logo.png` 列为安装后的 `launcher\` 内容，
      但安装器（`installer.py:390-396`）只复制 `DSHLauncher.exe` 和 `icon.ico`。
      (c) `README.md:332` 写 `DSHSetup.exe`「约 36 MB」，实际 61,412,566 B ≈ **58.6 MiB**
      （`installer\build\DSHSetup.spec:5` 的注释也是 36 MB）。
      (d) `README.md:334` 要求「发布标签和 VERSION 保持一致」，但 `launcher.pyw:166` 是
      **1.5.9**、最新 tag 只有 **v1.5.7**。⚠️ **不要擅自发 tag 或改版本号**，
      只把文档改成如实描述，并在「待确认」区登记发版流程漂移。
      (e) `installer.py:661-662` 的 docstring 与实际自删机制不符（AW-8 会一并处理，
      如果 AW-8 已改就跳过这条）。
      验证方式：逐条对照 `file:line` 复核，在条目里列「文档旧值 → 新值」对照表。

- [ ] **AW-12 清理过时的提示文案（打磨）**
      问题：`installer\preflight.py:501` 的用户可见提示「构建前端时 Node 最多会申请 4 GB 内存」
      **已过时**——现在没有任何前端构建（`:515-523` 用 `npm install --ignore-scripts`
      装预编译包）。同文件 `:8,16,22,69,237` 与 `installer.py:85,253,858` 仍把 npm 写成 **pnpm**
      （注释级）；`preflight.py:63` 的 `REQUIRED_RAM_GB` 注释同样引用已不存在的 `build:lib:host runs tsc`。
      修法：把用户可见文案改成与现状一致（内存要求按实际重新评估，
      **不要凭感觉改数字**——要么实测要么保守表述）；注释里的 pnpm 全部改成 npm。
      另外 `:1123-1126` / `preflight.py:567` 的提示只说「覆盖」，
      未提示「卸载时会删除该目录下的非 DSH 文件」——**这一条很重要，要补上**
      （AW-2 修好白名单后，措辞按修复后的实际行为写）。
      验证方式：`grep -rn "pnpm" --include=*.py` 不再命中；
      提示文案改动的字符串级用例。

- [ ] **AW-13 给 Node 载荷加哈希校验（供应链）**
      问题：`scripts\build.ps1:37-43` 用 `Invoke-WebRequest` 下载
      `node-v24.18.0-win-x64.zip`，**没有任何哈希校验**（全文件 grep `sha|Get-FileHash` 无命中），
      而同一个仓库对面板自更新却**强制校验 sha256**（`updater.py:1301-1306`）；
      且已存在的 zip 会被**无条件复用**（`:41-43`）。这个 zip 会被**内嵌进最终 exe**。
      修法：在 `build.ps1` 里加 `Get-FileHash` 校验，哈希值作为常量写在脚本里
      （附上来源说明）；已存在的 zip 复用前也要校验，对不上就重新下载。
      **不要用「下载时算的哈希」当基准**（那等于没校验），要用**预先固定的期望值**。
      验证方式：本地能算出当前 `payload\node-v24.18.0-win-x64.zip` 的真实 SHA256
      并写进脚本；构造一个哈希不匹配的场景断言脚本会拒绝（可以只测校验函数，
      **不要真的重新下载 35 MB**）。

- [ ] **AW-14 加 CI（打磨）**
      问题：`.github/` 不存在，所有自检靠人手跑，实际上没人跑。
      修法：加 workflow，push 时在 **`windows-latest`** 上跑
      `python scripts\selfcheck.py`（AW-0 建的聚合入口）。
      ⚠️ 只跑**不需要网络、不需要桌面**的项：`test-updater.py`、`test-github-probe.py`
      这类离线自检可以跑；`test-layout.py` 需要桌面 → 跳过；
      `test-linkcheck.py` 需要 node → runner 自带 node 可跑，但**不要联网下载**。
      ⚠️ **绝对不要**把「会跑真实卸载脚本」的检查放进 CI——虽然 CI 里没有真实安装，
      但保持这个习惯，并且 `test-security.py` 的注册表护栏在 CI 里没有意义。
      验证方式：本地先跑通，push 后用 `git credential fill` 取 token 调 GitHub API
      查这次 workflow run 结果；**查不到就如实说「已推送但未能确认 CI 结果」**，
      不要假装绿了。

- [ ] **AW-15 补强备份护栏（AW-0 复查实测出的两处缺口，数据安全）**
      > 编号与位置都是后补的，**它排在 AW-14 之后**（AW-3~AW-14 都不动注册表，所以排最后没有风险）。
      它保护的是**动注册表**的那些条目（AW-1 / AW-2），它的洞等于安全网的洞。

      AW-0 的对抗性复查**实测**出 `scripts\backup-dsh-registry.py` 的两处真实缺口：
      **(a) 备份的完整性从未在还原时校验**。manifest 里记了字节数与 sha256，
      但 `do_restore` **从不按它校验**。实测：把 `.reg` 内容篡改（语法仍合法）、
      让实际 sha256 与 manifest 明显不符 → `--restore` **仍然 rc=0，并把篡改内容导进去了**。
      而脚本文件头和 `README.md` 都写着"还原时照着 manifest 核对"——**这是不实的**。
      修法：`do_restore` 在 `reg import` **之前**按 manifest 校验 sha256（和字节数），
      不符即中止、rc 非 0、不做任何改动。
      **(b) 还原前的 `*-prerestore` 快照失败被忽略**。`do_restore` 里
      `do_backup(snapshot, …)` 的**返回值没接**；快照导出失败时只打印一句"导出失败！"
      然后**照样继续 import**。这是"备份失败却静默继续"的同族（AW-1 修的正是这个族），
      只是发生在还原前快照而非主备份。修法：快照失败即中止，
      不要在没有安全网的情况下还原。
      新增用例（**用一次性测试键，绝不用真实卸载键**）：篡改备份内容 → 断言还原被拒绝；
      快照导出失败 → 断言还原被拒绝。
      ⚠️ **AW-0 报告里说的"17 条断言全过"在仓库里没有对应文件**（复查 `grep` 无 `test-backup`），
      所以那些断言目前**不可复现**。这次要把它们落成**真正的测试文件**，
      而不是又写一个一次性脚本。
      顺手修 `README.md` 里那句不实的说明（"非交互环境不加 `--yes` 就只打印计划不落盘"——
      实测快照无论有没有 `--yes` 都会先写盘）。

- [ ] **AW-17 关掉守卫判定的最后一道缝：大小写（AW-16 复查指出，低危）**

      AW-16 复查确认两层守卫的**接受集现在相同**（原先发散的输入两层都拒绝，
      docstring 也改成如实描述「两处靠人工保持同步，用例钉住共同判定」），
      但留了一道缝：bat 的 `if exist` 是**大小写不敏感**的，而纯函数 `uninstall_verdict` 的
      `set(UNINSTALL_DIRS) <= names` 是**大小写敏感**的。若安装目录里是 `Launcher\` / `Harness\`，
      bat 会放行、纯函数会 reject——「完全一致」在这点上不成立。
      安装器实际只建小写名，**现实里触发不了**，属低危。
      修法（很便宜）：纯函数比较前把名字 `lower()` 化。
      新增用例：`['Launcher','Harness','Runtime']` + `launcher_exe_present=True`
      → 断言与 bat 同样放行（当前会 reject）。

      > 同一次复查还提到两个**既有、非本次引入**的脆弱点：cmd 对裸命令会先搜**当前目录**
      > （若从含 `taskkill.exe` 的目录跑测试会被解析到）；`for /f` 管道仍经真实 `%COMSPEC%`。
      > 当前仓库根/运行目录都没有这些 exe，故无实际影响——**只在注释里记一笔即可**，
      > 不要为此改动测试架构。

## 待确认（不要擅自做，等用户拍板）

- **卸载要不要加交互确认？** AW-2 改成白名单删除后，遇到白名单外的内容会保留并提示。
  但「要不要先问用户一句再删」属于交互决策。
- **盘根/系统目录的黑名单范围**（AW-3）：**已按作业指示实现为「盘根 + SystemRoot +
  ProgramFiles 系列 + USERPROFILE 本身 + 桌面/文档根（含 OneDrive 变体）」**，
  且只拒这些目录本身、其下子目录放行（见 AW-3 实际结果）。如果觉得桌面/文档根
  拒得太宽（或还想加别的，如 `%ProgramData%`、`%PUBLIC%`），说一声即可收窄/扩大。
- **发版流程漂移怎么处理？** `launcher.pyw` VERSION = 1.5.9，最新 tag 只有 v1.5.7（AW-11）。
  是补发 tag 还是把 VERSION 降回去，属于你的发版决策。
- ~~**`repo/` 要不要移出安装目录？**~~ —— **2026-10-17 已解决，用户批准「两个都做」**：
  (1) 本机 `C:\Users\sechen\deepseek\uninstall.bat` 已用修好的生成器重新生成并就地替换
  （旧版留底 `autowork-backups\deepseek-uninstall-OLD-20261017-114837.bat.bak`）；
  (2) `repo/` 已移到 **`C:\Users\sechen\dsh-src`**（51 项，`.claude`/`.agents` 完好）。
  安装根现在只剩 `harness/ launcher/ runtime/ install.log shortcuts.txt uninstall.bat`。
  ⚠️ **但替换上去的那版仍带着 AW-6 的两条过宽删除**（`del "%USERPROFILE%\Desktop\DSH*.lnk"`
  通配删桌面、`rmdir /s /q …\Programs\DSH` 递归删整个开始菜单文件夹）。
  **AW-6 做完后应再重新生成一次并替换**，那才是最终形态。
- **`--auto` 默认目标改成什么？** AW-9 建议改成临时目录。如果你更想「强制必须传 `--dir`」，说一声。
- **要不要给仓库加 LICENSE？** 目前没有。

## 收尾

队列清空（全部 `[x]` 或 `BLOCKED`）后**停下来**，在文件末尾写一节「## 作业总结」：
逐条列出完成了什么、验证结果（跑了哪些自检）、`BLOCKED` 项及原因、待确认项，
并特别注明 **`HKCU\...\Uninstall\DeepSeekHarness` 有没有被动过、是否完好**
以及 **`C:\Users\sechen\deepseek\repo` 是否还在**。
然后向用户报告。**不要自己发明新条目继续做。**
