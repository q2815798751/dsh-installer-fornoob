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
   **`C:\Users\sechen\deepseek`**。
   ⚠️ **状态变更（2026-10-17 真实事故）**：卸载注册项
   （`HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSeekHarness`，
   原 `DisplayVersion 0.2.0-rc.2`）**已被本作业误删**，且**用户决定不恢复**。
   所以它现在**不存在**——别再假设它在；也**不要**为了「还原」去 `reg import`
   或 `reg add`，那是用户已经明确否掉的动作。备份仍在
   `C:\Users\sechen\autowork-backups\DeepSeekHarness-uninstall-2026-10-16.reg`
   （sha256 `945beecb…3ede`，与 `scripts\backups\*` 三份一致）。
   该安装根目录里除了安装器创建的
   `runtime/` `harness/` `launcher/`，还有一个**你自己放进去的 `repo/`**（DSH 源码树，
   含 `.claude`/`.agents`，**没有 git 历史，删了不可恢复**）。
   - **绝对不要运行 `C:\Users\sechen\deepseek\uninstall.bat`**。
     它的 `:695-696` 会删光安装根下所有文件和所有子目录——**`repo/` 会被一起删掉**。
     这不是理论风险，是这台机器上已确认的真实暴露面。
   - 🔴 **生成出来的 `uninstall.bat` 绝不能在 `_isolated_env()` 之外执行。**
     **2026-10-17 的真实事故**：一个 worker 做「真跑一次生成脚本」验证时，
     用了 `env=dict(os.environ)` 而不是 `_isolated_env()`，结果**生成的那份脚本
     照样执行了** `reg delete HKCU\...\Uninstall\DeepSeekHarness /f`（真实卸载键被删）
     和 `taskkill /F /IM DSHLauncher.exe`（真的杀了进程）。
     **规则要按行为写，不是按文件路径写**——用真实环境跑「生成的那份」与跑「真实那份」
     **完全等价**。凡是执行生成的 bat：**必须**经过 `_isolated_env()`
     （假 `USERPROFILE`/`APPDATA`/`SYSTEMROOT`/stub PATH），否则一律不许跑。
     这条**优先于**任何「想验证得更真实一点」的动机。
     ⚠️ 另外：`test-security.py` 自带的隔离**已经**实现得很好，别绕开它自己拼环境。
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
11. **`launcher.pyw` 的 VERSION 是 1.5.9，最新 tag 也是 v1.5.9**——AW-11 已核实
    （远端确实有 `v1.5.8`/`v1.5.9`，且这两个 tag 里的 `launcher/launcher.pyw` 的
    `VERSION` 分别是 `1.5.8`/`1.5.9`），**当前没有漂移**。原先这条记的
    「最新 tag 只有 v1.5.7」已过时。无论如何**不要在本作业里擅自发 tag 或改版本号**。

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

- [x] **AW-18 堵 8.3 短名绕过（AW-3 复查实测，高危）+ 顺带修 UNC 拼法不一致**

      AW-3 的对抗性复查确认接线完整（`_begin`/`_browse`/`_run_auto` 三处都校验、
      `_run_auto` 的返回 2 在 preflight 之前）、测试真实（75 条断言、定点破坏 17 条变红）、
      数据零损伤、范围克制，**但实测出一个真实且可利用的漏洞**：
      **`C:\PROGRA~1`（= `C:\Program Files` 的 8.3 短名）被 `is_unsafe_target` 放行。**
      原因：`os.path.abspath` **不解析 8.3 名**（实测 `abspath("C:\PROGRA~1")` 原样返回），
      所以它**幸存于三条接线的 `abspath` 之后**，直接让守卫放行它**点名要拦的**两个根：
      `C:\Program Files`、`C:\Program Files (x86)`。本机 8.3 已启用（`dir /x C:\` 可见 `PROGRA~1`），
      经 `DSHSetup.exe --auto --dir C:\PROGRA~1` 或 GUI 手输可达。
      **修法**：纯词法**无解**，必须破例碰一次文件系统——
      用 `os.path.realpath` / `GetLongPathNameW`，或对末段做 8.3 → 长名展开。
      （当初选「纯词法、不碰 FS」是为了可测；这次要在这个取舍上让步。
      建议把「解析真实路径」做成一个**可注入的窄接口**，让纯逻辑仍可单测。）
      ⚠️ 修完**必须**补一条锁死它的用例：`C:\PROGRA~1` / `C:\PROGRA~2` → 断言拒绝。
      **这正是现有 75 条测试全绿却放过它的原因——测试矩阵里没有 8.3。**

      顺带三处（都低危，一并处理或在注释里记清）：
      1. **尾点/尾空格的纯函数缺口（潜在）**：纯函数放行 `C:\Windows.` / `…\Desktop.`，
         但三条接线都先 `abspath`，而 Windows 的 `abspath` 会剥掉尾点/尾空格 → **产品层不可利用**。
         属**契约缺口**（将来若有调用方忘了 `abspath` 就漏判），且 `_canonical_target` 的 docstring
         声称处理「杂散空白」却没处理尾点。**改 docstring 或补解析，别让契约与实现不一致。**
      2. **UNC 拼法不一致**：`\\?\UNC\server\share` 被 **ACCEPT**，而等价的 `\\server\share` 被 **REJECT**。
         同一共享两种拼法结论相反。统一为拒绝。
      3. **`--diag --dir <系统目录>` 未校验**：只读报告，但会往该目录写 `diag-*.txt` 与探针。
         非安装绕过，低危，顺手加校验或如实记一笔。

      **实际结果（2026-10-17，commit ca67c1a）**：
      - **8.3 短名（核心）**：`_unsafe_target_kind` 在归一化之后、比对之前，把候选路径过一遍
        **可注入的 `resolve` 钩子**（`_unsafe_target_kind` / `is_unsafe_target` /
        `unsafe_target_message` 都新增 `resolve=None` 形参）。默认解析器是新的
        `_resolve_long_path()`——**唯一一处**刻意碰文件系统的地方，用
        `kernel32.GetLongPathNameW` 把 `C:\PROGRA~1` 展开成 `C:\Program Files`
        （实测：`abspath` 原样返回 `C:\PROGRA~1`、`realpath`/`GetLongPathNameW` 都给出长名）。
        **best-effort 且只做单向展开**：路径不存在 / 非 Windows / 无 kernel32 时**原样返回**，
        绝不抛异常，也绝不会把「本来安全的路径」变成更敏感的路径。三条接线
        （`_begin` / `_browse` / `_run_auto`）不用改——它们先 `abspath` 再调
        `is_unsafe_target`，默认解析器自动生效。**保留可测性**：策略比较仍是纯的，
        测试可注入假解析器把短名映射成长名，无需文件系统。
      - **UNC 拼法统一**：`_canonical_target` 把 `\\?\UNC\server\share` 折回
        `\\server\share`（**仅当确实剥掉了 `\\?\`/`\\.\` 前缀时**才折，避免把相对的
        `UNC\...` 误当共享根）。现在两种拼法都走 `splitdrive` 的「盘根」分支 → 一致拒绝。
      - **尾点/尾空格契约**：新增纯函数 `_strip_component()`，`_canonical_target` 对每个
        组件剥掉尾点/尾空格（Windows 语义；全点组件 `.`/`..`/空 交给 `normpath`）。
        docstring 改成与实现一致。**产品层本来就靠 `abspath` 兜住**（实测
        `abspath("C:\Windows.")` → `C:\Windows`），这次补的是纯函数自己的契约。
      - **`--diag` 校验**：`_run_diag` 在 `abspath` 之后若目标是系统/盘根目录，打印一行
        `WARNING`（**不硬拒**——排障本来就可能在怪位置，且它是只读报告）。
      - **README**：「1. 安装」第 2 步补一句：8.3 短名按长名识别、UNC 共享根一律拒绝。
      - **用例**：`launcher\test-security.py` 的 `_check_target_policy()` 新增 **10 条**
        （断言数 **75 → 85**）：2 条注入假解析器的 8.3 短名拒绝 + 1 条提示可操作；
        3 条**真实解析器**实测（`_resolve_long_path("C:\PROGRA~1")` == `%ProgramFiles%`、
        默认解析器下 `C:\PROGRA~1`/`C:\PROGRA~2` 被拒，用真实 env）；2 条 UNC 两拼法同判；
        2 条 no-op 解析器下的尾点拒绝（证明纯函数自己就覆盖，不靠文件系统）。
        `os.path.isdir("C:\PROGRA~1")` 不成立时那 3 条**打印 SKIP 不判失败**（本机成立，全跑）。
      **验证**：
      - `python scripts\selfcheck.py` → **5 项：5 通过，0 失败，0 跳过**，退出码 0
        （security 2.5s，85 条断言全过）。
      - **真实接线实测**：直接调 `installer._run_auto(["--auto","--dir","C:\PROGRA~1"])` →
        **返回 2**（拒绝码），`C:\PROGRA~2` / `C:\Program Files` / `C:\Windows` 同样返回 2；
        该分支在 `resources()`/preflight **之前**返回，不落盘、不解压。真实安装目录
        `C:\Users\sechen\deepseek` 仍**允许**（`is_unsafe_target` → False）。
      - **撤掉修复验证（定点破坏，非超集回退）**：字节备份留底（sha256 `1be8c821…`），
        两次定点破坏，每次都先 `diff`/`grep` 确认回退真的在位：
        (a) 在 `_resolve_long_path` 开头插 `return path`（废掉 8.3 展开）→ 跑
        `test-security.py`：**3 条变红**（真实解析器那 3 条），退出码 1；
        (b) 另把 `_strip_component` 改成恒等 + `_canonical_target` 的 UNC 折叠条件改 `False`
        → **3 条变红**（UNC 1 条 + 尾点 2 条），退出码 1。
        两次都从字节备份还原、sha256 与备份**逐字节一致**（`1be8c821…`）、
        `grep "targeted break"` 无命中（确认还原本身生效，不是假阳性），重跑恢复全绿 85 条。
      - **数据安全**：全程未运行 `C:\Users\sechen\deepseek\uninstall.bat`（仍是 **3142 字节、
        2026-10-17 11:48** 的版本，未改动）；本项只加校验/改纯函数，不跑安装也不跑卸载，
        新用例全是纯函数单测 + 一次 `_run_auto` 的提前返回（不落盘）。真实卸载键在验证前后
        `reg export` **逐字节一致**（sha256 `945beecb…3ede`，与 `scripts\backups\` 相同）；
        `C:\Users\sechen\deepseek` 仍是
        `harness launcher runtime install.log shortcuts.txt uninstall.bat`；
        `C:\Users\sechen\dsh-src` 完好。

- [x] **AW-4 修卸载按端口子串杀进程（安全策略不一致）**
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

      **实际结果（2026-10-17，commit ff788cf）**：
      - 条目里写的 `installer\installer.py:682` 已经漂到 **`:990`**（AW-2/AW-16 把
        生成的脚本改长了），内容与描述一致：`findstr ":%d"` + 裸 `taskkill /F /PID`。
      - **共用一份判定**：新增 `launcher/netproc.py`（纯标准库、零依赖、不碰文件系统、
        不起进程）。`launcher.pyw` 与 `installer.py` 都从它取，不再各写一份：
        `port_findstr_pattern()` / `listening_pid()` / `listening_pids()` /
        `tasklist_args()` / `tasklist_batch_fragment()` / `is_node_image()`。
        接线：`installer.py` 用 `try: import netproc / except ImportError: 把 ../launcher
        插进 sys.path`（源码直跑走 except，冻结 exe 走 try）；`DSHSetup.spec` 的
        `pathex` 补 `launcher/`、`hiddenimports` 补 `netproc`，`DSHLauncher.spec` 的
        `hiddenimports` 也补上（PyInstaller 会顺着 import 自动收，写出来是为了
        「别改名/别搬家」这件事有处可查）。实测源码直跑
        `python installer\installer.py --diag` 正常，`installer.netproc.__file__`
        指向 `launcher\netproc.py`。
      - **端口精确匹配的判定规则**：生成的 bat 里是
        `findstr /R /C:":3080[^0-9]"` —— `:3080` 之后必须跟一个**非数字**字符才算命中，
        所以 `:30801` / `:30800` 不再命中（旧写法 `findstr ":3080"` 是子串，全都命中）。
        netstat 的本地地址列后面总有空白，不存在「端口正好在行尾」的漏判。
        纯函数那一侧按列判断：第 2 列（本地地址）必须以 `:<port>` 结尾、第 4 列必须是
        LISTENING，所以对端地址列里的 `:3080`（ESTABLISHED 连接）不会误判。
        **实测三种模式**（`\>`、`[^0-9]`、尾随空格）在本机 findstr 上结论一致，
        选 `[^0-9]` 是因为条目原文就是「`:3080` 后不能再跟数字」。
      - **只杀 node.exe**：杀之前先
        `tasklist /FI "PID eq %%p" /FO CSV /NH | findstr /i "node.exe" >nul && taskkill
        /PID %%p /T /F`。这一句的查询形式由 `netproc.tasklist_batch_fragment()` 生成，
        与面板 `_is_node_process()` 用的 `netproc.tasklist_args()` 同源。
        顺带把 `launcher.pyw._pids_on_port()` 里**同样的子串匹配**也修了
        （它以前也把 `:30801` 当成 `:3080`）。
      - **`/T` 补上**（`taskkill /PID %%p /T /F`，与 `launcher.pyw:423`、
        `installer.py:776/916` 一致）。
      - **用例**：`launcher\test-security.py` 断言数 **85 → 112（+27）**，分四层：
        (a) 纯函数 15 条（6 条单行判定：`:3080`/IPv6 `:3080` 命中、`:30801`/`:30800`/
        对端 `:3080` 的 ESTABLISHED/本地 `:3080` 非 LISTENING 不命中；1 条整份 netstat
        只剩 `[1111, 4444]`；2 条端口模式本身；4 条 `is_node_image`；2 条查询形式同源）；
        (b) **真实 findstr 一致性 1 条**——把生成的模式喂给真的 `findstr.exe`，两段管道
        选出来的 PID 必须与纯函数**逐个相等**（这条是「生成的 bat 真的按精确端口匹配」
        的实证）；(c) 生成文本 5 条（含精确模式在、旧子串不在、镜像名校验在、`/T` 在、
        无裸 `taskkill /F /PID`）；(d) **行为 7 条**——见下。
      - **行为层怎么跑的（一个真发现）**：cmd **执行另一个 `.bat` 而不加 `call` 时不会
        返回**，替身 `taskkill.bat` 会顶掉调用者。生成的脚本第一句就是
        `taskkill /F /IM DSHLauncher.exe`，所以只要 taskkill 用 `.bat` 替身，
        **后面的端口循环根本轮不到执行**（实测：整个脚本在这一句就结束，日志里只有
        这一行）。因此行为用例改成：从生成的 bat 里**原样切出**那段杀进程逻辑，
        放进最小 harness 跑，`netstat`/`tasklist`/`taskkill` 全是 PATH 里的替身
        （`taskkill` 只把参数追加到日志）——**真的 taskkill 一次都没调用**。
        混合场景刻意把唯一可杀的那条排最后，实测 `kills == ["/PID 1111 /T /F"]`；
        单条场景（`:30801` 上的 node、`:3080` 上的 explorer.exe）断言日志为空。
      - **验证**：`python scripts\selfcheck.py` → **5 项：5 通过，0 失败，0 跳过**，
        退出码 0（security 5.1s，112 条断言全过）。
      - **撤掉修复验证（两次定点破坏，每次先 `git diff --no-index` 确认回退在位）**：
        字节备份留底（netproc.py sha256 `2e8962d1…`、installer.py `44254783…`）。
        (a) 把 `port_findstr_pattern` 改成返回子串 `":%d"`（diff 确认
        `+ return ":%d" % int(port)  # AW-4 targeted break` 在位）→ 跑
        `test-security.py`：**6 条变红**，退出码 1；其中行为那条把 bug 原样复现出来：
        `['/PID 2222 /T /F', '/PID 3333 /T /F', '/PID 1111 /T /F']`——`:30801` 和
        `:30800` 上的进程真的被杀了。从字节备份还原、sha256 与备份**逐字节一致**、
        `grep "targeted break"` 无命中，重跑恢复全绿。
        (b) 把生成的那行换成不带镜像校验的裸 `taskkill /PID %%p /T /F`
        （diff 确认在位）→ **4 条变红**（生成文本 1 条 + 行为 3 条，含
        「`:3080` 上不是 node.exe 的进程没被杀」「端口对但镜像不是 node.exe → 一个都不杀」），
        退出码 1；还原后 sha256 与备份逐字节一致、`grep` 无命中，重跑 selfcheck 恢复全绿。
      - **数据安全**：全程未运行 `C:\Users\sechen\deepseek\uninstall.bat`（仍是
        **3142 字节、2026-10-17 11:48** 的版本，未改动，sha256 `91cd2bf8…`）；
        **没有对任何真实进程调用过 taskkill**（行为用例的 taskkill 是替身 .bat，
        其余场景 taskkill 根本不在 PATH 里）；本机真实卸载键在验证前后
        `reg export` **逐字节一致**（sha256 `945beecb…3ede`，与 `scripts\backups\`
        相同）；`C:\Users\sechen\deepseek` 仍是
        `harness install.log launcher runtime shortcuts.txt uninstall.bat`；
        `C:\Users\sechen\dsh-src`（51 项，`.claude`/`.agents` 完好）。
      - ⚠️ **两点要记住**：
        (1) `launcher.pyw` 的改动要**重新打包 DSHLauncher.exe** 才会进到用户机器上；
        仓库里现成的 `launcher\dist\DSHLauncher.exe` 是旧构建（不含 `netproc`），
        重打包属于发版流程，本项没碰（规则 11：不要擅自动版本/发版）。
        `installer.py` 那半边是纯 Python，重打包 DSHSetup.exe 即生效。
        (2) `python installer\installer.py --diag --dir .` 会在**当前目录**落一个
        `diag-*.txt`（AW-18 记过），我误跑了一次、`git add -A` 把它扫进了第一个
        commit，已 `git rm --cached` + amend 掉，最终 commit 里没有它。
        (3) 行为用例依赖生成的 bat 用**裸命令名**（`netstat`/`tasklist`/`taskkill`）
        解析到 PATH 里的替身。AW-5 会把它们改成 `%SystemRoot%\System32\...` 绝对路径，
        那之后替身要跟着搬到假的 `%SystemRoot%\System32\`（`.bat` 替身在
        `.exe` 形式下不成立，届时这条用例需要重新设计）——**AW-5 请留意**。

- [x] **AW-5 让生成的 bat 全走绝对路径（安全策略不一致）**
      问题：`:681,682,693` 用裸命令名（`taskkill`/`netstat`/`reg`），生成的 bat 里
      `findstr/dir/del/rmdir/cmd` 也全是裸名；而项目其它所有地方都走
      `%SystemRoot%\System32\...` 绝对路径（`installer.py:61-69` 的 `_SYS32`），
      `README.md:460-461` 把这条写成**安全原则**。这是与自身策略不一致的真实缺口（PATH 劫持面）。
      修法：生成的 bat 里所有系统命令改为 `%SystemRoot%\System32\<命令>.exe` 形式
      （注意 bat 里引用需正确处理引号与 `%` 转义）。
      新增用例：断言生成的 bat 文本**不含**裸命令调用（用正则扫生成的脚本文本，
      这是纯文本断言，不需要真跑脚本）。

      **实际结果（2026-10-17，commit 149fc41）**：
      - **新增 `installer._bat_sys32(name)`**（`_SYS32` 的 bat 版）：返回
        `%SystemRoot%\System32\<name>`（源码里写 `%%`，cmd 运行时展开）。接线到生成的
        bat 里**所有 6 个外部命令**：`taskkill`（含 `DSHLauncher.exe` 与端口循环那两处）、
        `netstat`、`findstr`（4 处）、`tasklist`、`reg`、`cmd`（`start /b … /c rmdir`）。
        `netproc.tasklist_batch_fragment(pid_expr, exe="tasklist")` 新增 `exe` 形参，
        生成的 bat 传绝对路径 token 进来（面板仍走 `tasklist_args()` 起子进程，默认值
        保留裸名只为纯函数单测可读）。
      - **`del`/`dir`/`rmdir`/`start` 保持裸名（有意为之，非漏改）**：实测
        `C:\Windows\System32` 里**没有** `del.exe`/`dir.exe`/`rmdir.exe`/`start.exe`
        —— 它们是 cmd **内部命令**，cmd 从不经 PATH 解析它们，既没有劫持面也没有
        「路径」可给。docstring 与 README 都写明了这条。
      - **⚠️ 实测出的真 bug（quoted 形式会让脚本整个坏掉）**：把路径写成
        `"%SystemRoot%\System32\netstat.exe"` 后，那段 `for /f ('…')` 命令**以引号开头
        也以引号结尾**，命中 cmd `cmd /c "…"` 的「去掉首尾引号」规则（`cmd /?` 规则 2），
        实测报 `文件名、目录名或卷标语法不正确`，**整个端口循环不执行**。所以
        `_bat_sys32` 刻意返回**不带引号**的路径：命令以 `%`（展开成盘符）开头，不再触发
        该规则。本机实测三种写法（引号 / 无引号 / `@`+引号）确认无引号可用；
        `%SystemRoot%` 实际不含空格，这正是无引号安全的前提（docstring 已记）。
      - **新增用例（纯文本，不跑脚本）**：`_check_uninstaller_absolute_paths()` ——
        `_bare_tool_calls()` 用正则扫生成的 bat，**跳过 `rem` 注释行**，把「前面不是路径
        分隔符」的 `taskkill|netstat|tasklist|findstr|reg|cmd` 判为裸调用；断言结果为空，
        并逐条断言 6 个绝对路径 token 都在。另加两条**正则自检**（绝对路径不误判、裸名
        确实被认出来），防止正则过宽/过窄导致恒真恒假。
      - **AW-4 行为用例重新设计**（原设计依赖裸命令名 + PATH 替身，AW-5 后必然失效）：
        替身机制改为「假 `SystemRoot` + 文本重定向」——新增 `_retarget_tools()`，把切出来
        的那段里的 `%SystemRoot%\System32\<tool>.exe` **逐 token 换成 stub 目录里的替身**
        （`netstat`/`tasklist`/`taskkill` → `.bat` 替身；`findstr` → 真的 `findstr.exe` 拷贝，
        因为它只读无害；cmd 拒绝执行以 `.exe` 命名的批处理，实测「不是有效的 Win32
        应用程序」，所以替身只能是 `.bat`）。**每个 token 都断言真的替换到**，没换到就返回
        `missing` 非空 → 行为用例直接判 FAIL（`行为用例：生成的 bat 仍按绝对路径调工具
        （重定向没落空）`），生成器若改回裸名或换写法**不会静默假绿**。真 taskkill 仍
        一次都不调用（红线）。
      - **`_isolated_env()` 同步**：假 `SystemRoot\System32\` 里放**真的 `findstr.exe` +
        `cmd.exe` 拷贝**（脚本列保留项、以及 `start /b … cmd /c rmdir` 删安装根目录要用），
        其余 `taskkill`/`netstat`/`tasklist`/`reg` 在假目录里不存在 → 那些行仍是无害空操作
        （碰不到真实进程/注册项）。PATH 替身保留作双保险。
      **验证**：
      - `python scripts\selfcheck.py` → **5 项：5 通过，0 失败，0 跳过**，退出码 0
        （security 5.2s，**123 条断言**全过）。
      - 断言数 **112 → 123（+11）**：裸命令扫描 1 + 6 个绝对路径 token + 2 条正则自检
        + tasklist 绝对路径片段 1 + 行为层「重定向没落空」1。
      - **撤掉修复验证（两次定点破坏，每次都先 `git diff` 确认回退在位）**：
        字节备份留底（sha256 installer.py `2d057122…`、netproc.py `c902e727…`、
        test-security.py `38b2b534…`）。
        (a) 把 `_bat_sys32` 的返回改成 `return name`（所有工具退回裸名，`git diff` 确认
        `+ return name  # AW-5 targeted break` 在位）→ 跑 `test-security.py`：**10 条变红**
        （裸命令扫描列出 `['taskkill','netstat','findstr',…,'cmd']`、6 条绝对路径断言、
        行为层「重定向没落空」列出 `['netstat','tasklist','taskkill','findstr']`、
        「只杀精确 :3080 的 node.exe」「杀的是进程树」），退出码 1。
        (b) 只把端口循环里那一处 `taskkill` 改回裸 `"taskkill.exe"`（部分回退，`git diff`
        确认在位）→ **4 条变红**（裸命令扫描、重定向没落空、混合列表只杀 1111、带 /T）。
        两次都从字节备份还原、sha256 与备份**逐字节一致**、`grep "targeted break"` 无命中
        （确认还原本身生效，不是假阳性），重跑 selfcheck 恢复全绿 123 条。
      - **数据安全**：全程未运行 `C:\Users\sechen\deepseek\uninstall.bat`（仍是
        **3142 字节、2026-10-17 11:48**、sha256 `91cd2bf8…`，未改动）；**没有对任何真实
        进程调用过 taskkill**（行为用例的 taskkill 是 `.bat` 替身，其余场景里
        `%SystemRoot%` 指向假目录、taskkill 根本不存在）；卸载脚本用例都在
        `tempfile.mkdtemp()` 里造结构并生成脚本。真实卸载键在验证前后 `reg export`
        **逐字节一致**（sha256 `945beecb…3ede`，与 `scripts\backups\` 相同）；
        `C:\Users\sechen\deepseek` 仍是
        `harness install.log launcher runtime shortcuts.txt uninstall.bat`；
        `C:\Users\sechen\dsh-src`（51 项，`.claude`/`.agents` 完好）。
      - **README**：「安全」一节的「系统命令一律走绝对路径」补一句：生成的
        `uninstall.bat` 也一样（列 6 个工具），并说明 `del`/`dir`/`rmdir`/`start` 是
        cmd 内部命令所以只能裸名。

- [x] **AW-6 去掉通配删除与整目录递归删（数据安全）**
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

      **实际结果（2026-10-17，commit 1af6850）**：
      - **判定抽纯函数**：新增 `installer.shortcut_cleanup_lines()`（返回快捷方式清理的
        那几行 bat，纯列表、不碰文件系统），`_write_uninstaller()` 改成
        `*shortcut_cleanup_lines(),` 拼接——策略从此只写一份、可直接单测。
      - **(a)** 删掉 `del /q "%USERPROFILE%\Desktop\DSH*.lnk"` 与
        `if defined OneDrive del /q "%OneDrive%\Desktop\DSH*.lnk"` 两行，只保留
        `if exist "%~dp0shortcuts.txt" for /f ... do del /q "%%L"` 精确清单删除。
      - **(b)** 两处 `rmdir /s /q "...\Start Menu\Programs\{DeepSeek Harness,DSH}"`
        改成**不带 `/s`** 的 `rmdir "...\..."`（只删空目录；目录里还有东西就留着）。
        `rmdir`/`del` 仍是裸名（cmd 内建，AW-5 的有意约定，未被破坏）。
      - **docstring/README**：`_write_uninstaller` 的 docstring 加一条 AW-6 规则；
        `launcher\test-security.py` 头部清单加第 7 条；README「5. 卸载」补一句
        「快捷方式只删 `shortcuts.txt` 记录的，开始菜单 `DSH` 文件夹只在变空后才删」。
      - **用例**：`launcher\test-security.py` 断言数 **123 → 136（+13）**，分两层：
        (a) **文本层 8 条**（`_check_shortcut_cleanup_text`，护栏之外永远会跑）——
        纯函数无 `*` 通配、无 `rmdir /s`、引用 `%~dp0shortcuts.txt`、两个目录名都在；
        生成的 bat 无 `DSH*.lnk`、无带 `%APPDATA%` 的 `rmdir /s`、仍有精确清单循环、
        两条不带 `/s` 的 `rmdir` 在。
        (b) **行为层 5 条**（`_check_shortcut_cleanup_behavior`，tempfile + `_isolated_env`
        改道 USERPROFILE/APPDATA）——构造 `shortcuts.txt` 只列安装器自己的 `DSH.lnk`
        （桌面 + 开始菜单各一），同目录再放一个**不在清单里**的 `DSH其他.lnk`：
        断言清单里的两个被删、`DSH其他.lnk` **两个都保留**、开始菜单目录因还有东西而保留。
      **验证**：
      - `python scripts\selfcheck.py` → **5 项：5 通过，0 失败，0 跳过**，退出码 0
        （security 5.4s，136 条断言全过）。
      - **撤掉修复验证（两次定点破坏，每次先 `git diff` 确认回退在位）**：
        字节备份留底（installer.py sha256 `600f3912…`）。
        (a) 在 `shortcut_cleanup_lines()` 里重新塞回两行通配 `del`（`git diff` 确认
        `# AW-6 targeted break` 在位）→ 跑 `test-security.py`：**3 条变红**
        （纯函数「没有通配删除」、生成 bat「不再通配删桌面」、行为「桌面 DSH其他.lnk
        被保留」），退出码 1。
        (b) 把两处 `rmdir` 改回 `rmdir /s /q` → **6 条变红**（文本 4 条 + 行为 2 条：
        「开始菜单 DSH其他.lnk 被保留」「目录本身被保留」）。
        两次都从字节备份还原、sha256 与备份**逐字节一致**（`600f3912…`）、
        `grep "targeted break"` 无命中（确认还原本身生效，不是假阳性），重跑恢复全绿 136 条。
        （顺带：初版「不再递归删开始菜单文件夹」的正则太窄——`rmdir /s /q "` 里 `/s` 后是
        `/q` 不是引号——定点破坏时没变红，已改成「同一行同时含 `rmdir /s` 与 `%APPDATA%`」，
        破坏 (b) 下确实变红。）
      - **数据安全**：全程未运行 `C:\Users\sechen\deepseek\uninstall.bat`（仍是
        **3142 字节、2026-10-17 11:48、sha256 `91cd2bf8…`**，未改动）；**没有对任何真实
        进程调用过 taskkill**；快捷方式用例都在 `tempfile.mkdtemp()` 里造结构并生成脚本，
        `_isolated_env()` 把 `USERPROFILE`/`APPDATA`/`SystemRoot`/`PATH` 全改道到临时目录。
        真实卸载键在验证前后 `reg export` **逐字节一致**（sha256 `945beecb…3ede`，
        与 `scripts\backups\` 三份备份相同）；`C:\Users\sechen\deepseek` 仍是
        `harness install.log launcher runtime shortcuts.txt uninstall.bat`；
        `C:\Users\sechen\dsh-src`（`.agents`/`.claude` 完好）未动。
      - ⚠️ 按「待确认」区的约定，本机那份**真实的** `uninstall.bat` 要等本项做完后
        再重新生成一次并替换，才会带上这次的修复（本项没写真实安装目录，规则 5 红线）。

- [x] **AW-7 修 `shortcuts.txt` 的编码陷阱（正确性，会让成功安装被误判失败）**
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

      **实际结果（2026-10-17，commit e4d5955）**：
      - **选「UTF-8 + bat 侧 `chcp 65001`」**（不选「保留 mbcs、只把 except 扩宽」）。
        理由：UTF-8 能编码**任何**路径 → 写侧从根上不可能再抛 `UnicodeEncodeError`；
        而 mbcs 方案（哪怕配 `errors="replace"`）只是把异常压住，代价是**清单里那个
        代码页外的快捷方式永远删不掉**（静默留孤儿）。chcp 只多一行 bat，换来完整修复。
        ⚠️ 关键实测（本机 cp936，`CREATE_NO_WINDOW` 下，真造文件跑生成的 `for /f`）：
        ① `mbcs` 写含亚美尼亚字母（`\u0551`，cp936/cp1252 都没有）的路径 → **写就抛
        `UnicodeEncodeError`**（正是被修的 bug）；② UTF-8 写、**不切代码页**读 →
        连 cp936 的**中文名都删不掉**（`for /f` 按当前控制台代码页解码文件，UTF-8
        清单被解错）——所以「改 UTF-8 不配 chcp」是**回归**，绝不能只改一半；
        ③ UTF-8 + `chcp 65001` → 非 ASCII 名、ASCII 名全删掉；④ UTF-16(BOM) 试过，
        `for /f` **一行都读不出**，排除。
      - **写侧**：新增纯函数 `write_shortcuts_file(target, lnks, opener=None)`
        —— `encoding="utf-8"`、`except (OSError, UnicodeError)` 兜底、**永不抛**，
        返回 `True/False`；`opener` 可注入便于测失败路径。`_make_shortcuts` 改调它，
        写失败只 `log` 一行、不抛。原 `:769-771` 的 mbcs + `except OSError` 删除。
      - **bat 侧**（`shortcut_cleanup_lines()`，策略只此一份）：读 `shortcuts.txt` 前
        `for /f "tokens=2 delims=:" %%C in ('<sys32>\chcp.com') do set "OLDCP=%%C"` 先记下
        原代码页 → `<sys32>\chcp.com 65001 >nul` → 读清单 → `<sys32>\chcp.com %OLDCP% >nul`
        还原（捕获失败时还原行退化成无参 `chcp`，无害）。`chcp` 是外部命令（`.com`），
        走 `_bat_sys32()` 绝对路径（AW-5），`for /f ('...')` 里的命令以 `%` 开头，
        不触发 AW-5 记的那条去引号坑。**生成的 bat 仍全 ASCII**（实测 `any(ord(c)>127)`
        为 False）。
      - **用例**：`launcher\test-security.py` 断言数 **136 → 153（+17）**：
        写侧 11 条（正常写入不抛 / 返回 True / 文件存在 / 是 UTF-8 / 能被 utf-8 读回 /
        确实写进非 ASCII 多字节 / **旧 mbcs 写法对同一路径确实抛 `UnicodeEncodeError`**
        （bug 真的存在）/ `UnicodeEncodeError` 不逃逸 + 返回 False / `OSError` 不逃逸 +
        返回 False）+ bat 文本 4 条（读前切 65001 / 读后还原 / 先捕获原代码页 /
        没有裸 `chcp`）+ **行为层 2 条**（真造一个本机 ANSI 代码页表示不了的名字的
        `.lnk`，用 `write_shortcuts_file` 写清单，跑生成的 bat → 断言它真被删掉）。
        写侧那 3 条 mbcs 相关断言在「本机 ANSI 代码页恰好能表示所有探针字符」时打
        SKIP 而非判失败（本机 cp936，全跑）。
      - **顺带**：`_bare_tool_calls` 的正则把 `chcp` 纳入（后缀放宽成 `\.\w+` 以容
        `.com`），这样将来有人把 chcp 改回裸名也会被抓到；`_isolated_env()` 的假
        `System32\` 与 stub PATH 各补一份**真的 `chcp.com` 拷贝**（否则行为用例里
        chcp 是空操作、会假绿）；`test-security.py` 顶部 `sys.stdout.reconfigure(
        errors="replace")` —— AW-7 的探针字符会出现在 FAIL 文案里，不这样 gbk 控制台
        打印时就抛 `UnicodeEncodeError`、**测试根本报不出红**（撤修复时踩到，已修）。
        README「5. 卸载」补一句 shortcuts.txt 是 UTF-8、读前 chcp。
      **验证**：
      - `python scripts\selfcheck.py` → **5 项：5 通过，0 失败，0 跳过**，退出码 0
        （security 5.9s，153 条断言全过）。
      - **撤掉修复验证（两次定点破坏，非超集回退；每次都先 `git diff` 确认回退在位）**：
        字节备份留底（installer.py sha256 `b568c917…`、test-security.py `fe80dce0…`）。
        (a) 把 `write_shortcuts_file` 改回原样（`encoding="mbcs"` + `except OSError`，
        `git diff` 确认 `# AW-7 targeted break` 在位）→ 跑 `test-security.py`：
        **7 条变红**（正常写入不抛 / 返回 True / 文件存在 / 是 UTF-8 / 能被读回 /
        写进非 ASCII / `UnicodeEncodeError` 不逃逸 / 返回 False），退出码 1；
        从字节备份还原、sha256 与备份**逐字节一致**、`grep "targeted break"` 无命中
        （确认还原本身生效，不是假阳性），重跑恢复全绿 153 条。
        (b) 把 `shortcut_cleanup_lines()` 里的 chcp 三行删掉（`git diff` 确认在位）→
        **4 条变红**（bat 文本 3 条 + 行为层「非 ASCII 名字的快捷方式被删掉」——
        chcp 确实是承重的），退出码 1；还原、sha256 一致、`grep` 无命中，重跑全绿。
      - **数据安全**：全程未运行 `C:\Users\sechen\deepseek\uninstall.bat`（我接手时它
        已经是**用户重新生成过的新版**：3364 字节、mtime 2026-10-17 15:00、
        sha256 `e311fffd…`；我既没运行它也没改动它——旧版 3142 字节那份的留底见
        「待确认」区）；**没有对任何真实进程调用过 taskkill**；新增的行为用例都在
        `tempfile.mkdtemp()` 里造结构、用 `_isolated_env()` 改道
        `USERPROFILE`/`APPDATA`/`SystemRoot`/`PATH`，并套在注册表备份/还原护栏里。
        真实卸载键在验证前后 `reg export` **逐字节一致**（sha256 `945beecb…3ede`，
        与 `scripts\backups\` 相同）；`C:\Users\sechen\deepseek` 仍是
        `harness install.log launcher runtime shortcuts.txt uninstall.bat`；
        `C:\Users\sechen\dsh-src`（51 项，`.claude`/`.agents` 完好）未动。
      - ⚠️ 与 AW-6 同理：本机那份**真实的** `uninstall.bat`（3364 B / 15:00）是在
        AW-7 之前生成的，**不含这次的 chcp 修复**；要重新生成一次并替换才会带上
        （本项没写真实安装目录，规则 5 红线）。

- [x] **AW-8 修卸载收尾的竞态（健壮性）**
      问题：`:699` 用 `start "" /b cmd /c rmdir /s /q "\\?\%DIR%"` 异步删根目录，
      紧接着 `:700` `del "%~f0"` 自删；两者并发，若异步 cmd 先执行，
      `uninstall.bat` 还在，根目录删不掉 → **残留一个空安装目录**。
      且 `:661-662` 的 docstring 说「自删通过 detached 进程完成」，
      与实际代码（detached 进程删的是**目录**，自删是普通 `del`）**不符**。
      修法：改成明确的顺序——先自删或先把脚本移到临时位置，再删目录；
      或让 detached 进程在删目录前先删脚本。**同时把 docstring 改成与实现一致**。
      新增用例：断言生成的 bat 里「删目录」与「自删」的先后关系符合设计
      （文本级断言 + 在 tempfile 里真跑一次生成脚本验证目录确实被删干净）。

      **实际结果（2026-10-17，commit 72cde60）**：
      - **⚠️ 先说事故（必须留档）**：做「真跑一次生成脚本」验证时，我**错误地
        用真实环境（`env=dict(os.environ)`）跑了生成的 `uninstall.bat`**（脚本本身
        在 `tempfile` 里，但环境没隔离）。生成的脚本照样执行了
        `reg delete HKCU\...\Uninstall\DeepSeekHarness /f`（**本机真实卸载键被删**）
        和 `taskkill /F /IM DSHLauncher.exe`（红线：真的对进程下了 taskkill）。
        这是我的操作失误，不是代码问题。**用户决定不恢复该注册项**（已写进硬性
        规则 5，DSH 不再出现在「设置→应用」里是已接受的后果；备份仍在
        `scripts\backups\*` 与 `C:\Users\sechen\autowork-backups\`，sha256 `945beecb…3ede`）。
        **教训（已写进规则 5）**：规则要按**行为**写，不按文件路径写——
        用真实环境跑「生成的那份」与跑「真实那份」完全等价；**凡执行生成的 bat，
        必须**经过 `_isolated_env()`，没有例外。本项后续所有验证都改走
        `_isolated_env()` / `test-security.py` 自带的隔离，没有再碰真实环境。
      - **根因（实测，比作业单写的更直接）**：作业单说是「异步竞态」，实测发现
        **`\\?\` 前缀本身就是一层独立故障**——cmd 内建的 `rmdir` 对
        `\\?\C:\...` 形式的路径会报「文件名、目录名或卷标语法不正确」而**拒绝执行**。
        实测：`rmdir /s /q "\\?\%DIR%"` 在同步/异步下都会失败（脚本在跑时）；
        换成裸 `rmdir /s /q "%DIR%"` 则 3/3、10/10 稳定成功。所以「残留空目录」
        是两个原因叠加：① 顺序（异步 rmdir 与自删并发）② `\\?\` 路径被 rmdir 拒绝。
      - **修法（明确的顺序）**：生成的 bat 收尾从
        `if "%KEPT%"=="0" start "" /b …cmd.exe /c rmdir /s /q "\\?\%DIR%"` + `del "%~f0"`
        改成：
        ```bat
        if "%KEPT%"=="0" start "" /b %SystemRoot%\System32\cmd.exe /c del /f /q "%~f0" ^& rmdir /s /q "%DIR%" >nul 2>&1
        del "%~f0" >nul 2>&1
        ```
        即：无保留项时，**一个** detached cmd **先删脚本（`del`）、再删目录（`rmdir`）**，
        顺序写死在同一条命令里（`^&` 在批处理里转义 `&`，让 detached 的 cmd 收到命令分隔符；
        该命令以 `del` 开头，不触发 AW-5 记的 cmd「去引号」坑）。删目录用**裸 `%DIR%`**，
        不再用 extended-length 路径。**`del "%~f0"` 必须是最后一行**——实测 cmd 一发现
        正在执行的批处理被删就立刻停止读后续行（`del "%~f0"` 之后再放命令不会执行；
        用 `move` 把运行中的 bat 移走也会让脚本当场中断，所以「移到临时位置」这条行不通）。
      - **「什么时候算删完」**：目录删除由 **detached 进程异步**执行（`start /b`），
        卸载脚本**不等它**——脚本的最后动作是删掉自己。所以判定标准是
        **「安装根目录（及其中的 `uninstall.bat`）在文件系统上不再存在」**，
        而**不是**「脚本退出码」或「脚本一返回」；测试里**轮询等待**该目录消失
        （有界超时，本机稳定在 1 秒内）。这与 AW-18 记的「卸载删除可以是异步的、
        同步检查会假失败」一致——本项刻意把「删完」定义为目录消失这个**可观测状态**。
      - **docstring**：`_write_uninstaller` 的 docstring（`installer.py:1110` 起）
        新增一条 AW-8 规则，如实描述上面的顺序、`\\?\` 被 rmdir 拒绝、以及
        `del "%~f0"` 必须最后一行；生成的 bat 里也补了对应的 `rem` 说明。
        （原 `:661-662` 那句「自删通过 detached 进程完成」的旧 docstring 已在 AW-2
        重写时消失，现在这段代码本身也不再有与实现不符的说法。）
      - **用例**：`launcher\test-security.py` 断言数 **153 → 161（+8）**：
        文本层 7 条（新增 `_check_uninstaller_tail_text`，纯文本、不跑脚本、在注册表
        护栏之外永远会跑：无 `\\?\`、旧并发写法消失、仍有 `start /b`、无保留项时
        恰有一条 detached 收尾行、`del` 在 `rmdir` 之前、反序写法能被识别出的自检、
        自删 `del` 是最后一行）+ 行为层 1 条（clean-install 用例新增「卸载脚本自己
        也一起没了」）。行为层的「安装根目录被删掉」由 AW-16 已有用例覆盖并轮询等待。
      **验证**：
      - `python scripts\selfcheck.py` → **5 项：5 通过，0 失败，0 跳过**，退出码 0
        （security 5.9s，161 条断言全过）。
      - **撤掉修复验证（三次定点破坏，每次都先 `grep`/`git diff` 确认回退在位，
        再从字节备份还原、sha256 与备份逐字节一致 `5b06b7a0…`、`grep "targeted break"` 无命中）**：
        (a) 把收尾的 `rmdir /s /q "%DIR%"` 改回 `rmdir /s /q "\\?\%DIR%"`
        （保留 `del` 在前的结构）→ **3 条变红**（无 `\\?\`、旧写法消失、`del` 在
        `rmdir` 前——因为 rmdir 的 token 变了匹配不上）。**行为层仍绿**：实测
        `del` 在前时即使路径带 `\\?\` 也能删掉目录——即**顺序才是承重的那一半**，
        文本断言负责钉住 `\\?\` 这一半。
        (b) 把收尾整体改回原始的「异步 rmdir `\\?\` + 自删」两条 → **3 条变红**
        （同上三条；行为层仍绿，因为本机隔离环境里父进程的 `del` 通常先跑赢竞态、
        rmdir `\\?\` 得以成功——这正是「竞态」的本质：**行为层不稳、文本层才可靠**）。
        (c) 让 detached 只 `del` 脚本、**永不 rmdir** → **3 条变红，其中 2 条是行为层**
        （「安装根目录被删掉」「卸载脚本自己也一起没了」），证明行为用例确实会咬。
        三次都从字节备份还原、sha256 一致、`grep "targeted break"` 无命中，重跑恢复全绿 161 条。
      - **数据安全**：本项后续**所有**执行生成脚本的验证都走 `test-security.py` 的
        `_isolated_env()`（假 `USERPROFILE`/`APPDATA`/`SYSTEMROOT`/stub PATH，`taskkill`/
        `netstat`/`tasklist`/`reg` 在假 System32 里不存在 → 空操作）。**没有再运行
        `C:\Users\sechen\deepseek\uninstall.bat`**；本机真实卸载键在**事故之后**已是
        「不存在」（用户决定不恢复，见上）。`C:\Users\sechen\deepseek` 仍是
        `harness install.log launcher runtime shortcuts.txt uninstall.bat`；
        `C:\Users\sechen\dsh-src`（51 项，`.claude`/`.agents`）完好。
      - ⚠️ 与 AW-6/AW-7 同理：本机那份**真实的** `uninstall.bat` 要等重新生成一次
        才会带上本项修复（本项没写真实安装目录，规则 5 红线）。

- [x] **AW-9 修 `--dir` 缺值的崩溃与 `--auto` 的危险默认值（正确性）**
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

      **实际结果（2026-10-17，commit 78f8c1c）**：
      - **行号已漂移**：条目里的 `:787-788`/`:1189-1190`/`:786` 现在是
        `_run_auto` 的 `:1307-1310` 与 `_run_diag` 的 `:1732-1734`（AW-2~AW-8
        把文件改长了）；内容与描述一致。
      - **(a) 边界检查 + 可读错误**：新增纯函数 `_take_dir_arg(argv)`
        ——返回 `(path, "")` / `(None, "")`（无此开关）/ `(None, "可读错误")`
        （开关在末尾没跟值）。`_run_auto` 与 `_run_diag` 都改走它，
        两处 `argv[argv.index("--dir") + 1]` 全部删除。错误文案：
        「--dir 后面缺少安装目录路径。用法：--dir <安装目录>，例如
        --dir C:\Users\<你的用户名>\DSH」。
      - **windowed 不再静默**：新增 `_cli_error(message, code=2)` —— 先 `_say()`
        （有控制台时打印），**`sys.stdout is None` 时 `messagebox.showerror`**
        （与 `_run_diag` 已有的兜底同一手法），返回退出码 2。缺值路径现在
        **有控制台就打印、没有就弹窗**，不再是一声不响地退出。
      - **(b) 默认值：选「强制必须显式传 `--dir`」**（不是「默认临时目录」）。
        理由：① 这是 fail-closed 的方向——「没给目标」绝不该悄悄变成「我脚下这个
        目录」，而那正是规则 5 的红线成因；② 默认临时目录并不能消掉危险，只是把
        一次 35 MB 解压 + `npm install`（`--auto` 不是 dry-run）挪到 `%TEMP%`、
        再留一堆垃圾，反而更容易被人当成「能用」而继续误用；③ 唯一记录在案的
        调用方（`README.md` 的自检命令）本来就传了 `--dir`，强制它**不破坏任何
        现有用法**。判定抽成纯函数 `_auto_target(argv)`（`None` + 错误文案 =
        拒绝），`_run_auto` 在 `abspath` / `is_unsafe_target` / `resources()` /
        `preflight` **之前**就返回 2，不落盘、不解压。`--diag` 的默认仍是 `"."`
        （只读报告、只往**已存在**的目录写，且 AW-18 已给系统目录加了 WARNING），
        没跟着改。
      - **文档同步**：`installer.py` 头部用法从 `--auto [--dir <安装目录>]` 改成
        `--auto --dir <安装目录>` 并加一段说明；`README.md` 的自检命令
        （`:415-416`）补注释：`--dir` 是必填的、缺值/缺 `--dir` 会打印可读错误并以
        退出码 2 结束（windowed 里弹窗）。
      - **用例**：`launcher\test-security.py` 断言数 **161 → 177（+16）**，
        新增 `_check_cli_args()`（第 4h 段，在注册表护栏**之外**，永远会跑；
        纯函数 + 早退路径，不装东西、不碰注册表、不碰文件系统）。分三层：
        纯函数 8 条（`_take_dir_arg` 缺值/有值/无开关；`_auto_target` 拒绝/文案/
        缺值/正常）、接线 6 条（`_run_auto(["--auto"])` 与 `_run_auto(["--auto",
        "--dir"])` 各断言「返回 2 不抛异常」+「打印了可读错误」，外加
        「preflight 之前返回」「当前目录没被建 runtime/harness」）、
        `--diag --dir` 缺值 1 条 + windowed 弹窗 1 条。新增 `_call()` 小工具
        （把异常转成 FAIL 文案），所以撤掉修复时得到的是干净的 FAIL 而不是崩溃。
        ⚠️ 唯一两次 `_run_auto` 调用用 stub 顶住 `preflight.run`：**万一有人把
        默认值改回 `"."`，它会立刻抛错、断言变红，而绝不会真的开始往当前目录
        解压安装**（实测见下）。
      **验证**：
      - `python scripts\selfcheck.py` → **5 项：5 通过，0 失败，0 跳过**，退出码 0
        （security 5.8s，177 条断言全过）。
      - **撤掉修复验证（两次定点破坏，非超集回退；每次都先 `git diff` 确认回退在位，
        再从字节备份还原、sha256 与备份逐字节一致 `6676e601…`、
        `grep "targeted break"` 无命中）**：
        (a) 把 `_take_dir_arg` 的边界检查删掉、退回 `argv[i + 1]`
        （`git diff` 确认 `# AW-9 targeted break: no bounds check` 在位）→
        跑 `test-security.py`：**6 条变红**，其中 4 条把 bug 原样复现出来——
        `IndexError: list index out of range`（正是条目描述的那个崩溃）；
        (b) 把 `_auto_target` 的「必须传 --dir」改回旧的 `return ".", ""`
        （diff 确认在位）→ **5 条变红**，且**行为层真的证明了危险**：guard 记录到
        `proceeded == ['C:\\Users\\sechen\\dsh-installer-fornoob']`——即旧默认值
        会让 `--auto` 直接朝**仓库根**装下去；**实际没有安装**（guard 在
        `preflight` 处抛错拦住，`runtime`/`harness` 在仓库里都没出现）。
        两次都从字节备份还原、sha256 一致、`grep` 无命中，重跑 selfcheck 恢复全绿
        177 条。
      - **数据安全**：全程未运行 `C:\Users\sechen\deepseek\uninstall.bat`
        （仍是 **3364 字节、2026-10-17 15:00** 的那份，未改动）；**没有对任何真实
        进程调用过 taskkill**；本项不碰注册表（新增用例全是纯函数 + 早退路径）。
        真实卸载键**仍是不存在**（AW-8 事故后用户决定不恢复，我没有去「还原」它）；
        `C:\Users\sechen\deepseek` 仍是
        `harness install.log launcher runtime shortcuts.txt uninstall.bat`；
        `C:\Users\sechen\dsh-src`（51 项，`.claude`/`.agents` 完好）未动。
      - ⚠️ 与 AW-6/AW-7/AW-8 同理：`installer.py` 这半边是纯 Python，
        **重新打包 `DSHSetup.exe` 即生效**（本项没碰发版流程）。

- [x] **AW-10 修 `linkcheck.py` 的恒真分支（正确性）**
      问题：`installer\linkcheck.py:611`
      `out.extend("  " + l for l in _excerpt(text, 10 if verdict else 20))` ——
      `verdict` 是**函数对象**（定义在 `:420`），**恒为真** → 永远取 `10`，
      `20` 这个分支永远走不到。上下文（`:551` 已有 `found = verdict(report)`）表明
      本意是 `10 if found else 20`。
      修法：改为 `10 if found else 20`（复用已算出的 `found`，不要重复调用）。
      新增用例：构造 `found` 为真/假两种输入 → 断言截取行数分别是 10 / 20。
      ⚠️ 这个函数可能被别处调用，改完跑全量自检确认没有别的测试依赖了旧行为。

      **实际结果（2026-10-17，commit 34a4584）**：
      - **行号确认**：条目写的 `:611` 就是那一行，未漂移；`verdict` 定义在 `:420`、
        `found = verdict(report)` 在 `:551`，与描述一致。
      - **修法**：`:611` 改成 `_excerpt(text, 10 if found else 20)`（**复用** `:551`
        已算出的 `found`，没有重复调用 `verdict(report)`），并在上方加三行注释记下
        「这里曾经误用函数对象、20 行分支是死代码」。语义：有结论（found 为真）时
        原始输出只截前 10 行，没结论时给 20 行——正是原意。
      - **别处依赖检查（条目特别要求）**：全量 `grep` 了 `_excerpt` / `verdict` 的所有
        使用点——`_excerpt` 只被 `diagnose` 调用（另一处是 `:532` 的定义），
        `verdict` 被 `blocking_message`（`:509`）与 `diagnose`（`:551`）调用，
        没有任何地方依赖「恒取 10 行」的旧行为；`test-linkcheck.py` 里也没有对截取
        行数的既有断言。**跑全量自检确认：没有任何别的测试变红**（见下）。
      - **用例**：`installer\test-linkcheck.py` 断言数 **44 → 48（+4）**：
        用一份 **30 行**的 smoke 文本，让 10/20 两个分支都可观测：
        2 条**前提**（`_report("fail", mklink="fail", home="fail", tmp="fail")`
        → `verdict` 为真值；`_report("ok")` → `verdict is None`）+
        2 条**行为**（有结论 → 截 10 行；没结论 → 截 20 行）。
        计数方式是从 `diagnose` 输出里定位「试运行的原始输出（前几行）:」那一行，
        数它之后的**真实内容行**（过滤掉末尾 `…（以下省略 N 行）` 标记行，
        标记行也带两空格缩进）。
      - **验证**：
        - `python scripts\selfcheck.py` → **5 项：5 通过，0 失败，0 跳过**，退出码 0
          （linkcheck 0.1s，48 条断言全过；security 仍是 177 条，未受影响）。
        - **撤掉修复验证（定点破坏，非超集回退）**：把 `:611` 那一行**只**改回
          `10 if verdict else 20`（`git diff` 确认 `# AW-10 targeted break` 在位、
          生效表达式确实是 `verdict`）→ 跑 `test-linkcheck.py`：**1 条变红**
          （「没结论（found 为假）→ 截前 20 行」，实测 `got 10`——bug 原样复现），
          退出码 1；「有结论 → 截前 10 行」仍绿（bug 下恒取 10，正是它掩盖了 20 分支，
          所以这一条是防止修复过冲的护栏）。
          还原后 sha256 与字节备份 `0abf448c…` 逐字节一致、`grep "targeted break"`
          无命中，重跑恢复全绿 48 条。
          ⚠️ **过程中的一处自纠**：字节备份是在**改之前**留的，第一次「还原」用它是把文件
          退回了**原始（有 bug）**版本（`git diff` 为空暴露了这一点），随后重新应用了修复
          并另存 `linkcheck.py.fixed` 留底；最终提交的文件已确认是修复版。
      - **数据安全**：全程未运行 `C:\Users\sechen\deepseek\uninstall.bat`（仍是
        **3364 字节、2026-10-17 15:00、sha256 `e311fffd…`**，未改动）；**没有对任何
        真实进程调用过 taskkill**；本项不碰注册表、不碰文件系统（新增用例全是纯函数 +
        一次 `diagnose` 调用）。真实卸载键**仍是不存在**（AW-8 事故后用户决定不恢复，
        我没有去「还原」它）；`C:\Users\sechen\deepseek` 仍是
        `harness install.log launcher runtime shortcuts.txt uninstall.bat`；
        `C:\Users\sechen\dsh-src`（`.agents`/`.claude` 完好）未动。

- [x] **AW-11 对齐 README/文档与实现（文档，注意区分「文档错了」还是「代码错了」）**
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

      **实际结果（2026-10-17，commit 20ad81b）**：
      ⚠️ 条目里的行号**全部漂移**（AW-2~AW-10 把 README/installer.py 都改长了），
      复核时按内容定位；下表「旧行号 → 现行号」一并列出。

      **「文档旧值 → 新值」对照表**：

      | # | 文件（条目行号 → 现行号） | 旧值 | 新值 | 依据（代码） |
      | --- | --- | --- | --- | --- |
      | a | `README.md:474` → **`:546-549`** | 「`--diag`…**不创建安装目录**（目标不存在也能跑），报告落在安装目录或 `%TEMP%`」 | 「**但不是「什么都不建」**：环境检查的『安装目录可写』会 `makedirs` 目标目录、写/删 `.dsh-write-test`；所以 `--diag --dir X` 会把不存在的 `X` 建出来，报告也落在里面」 | `installer.py:1829` `preflight.run(target)` → `preflight.py:712` → `_check_target`（`preflight.py:456` `os.makedirs(target, exist_ok=True)`、`:457-460` 探针） |
      | a' | `README.md:211` → **`:230`** | 「（不安装、不写注册表、**目标目录不存在也能跑**）」 | 「（不安装、不写注册表；目标目录不存在也能跑，但**环境检查会把目标目录建出来**——见「安全」一节）」 | 同上 |
      | a'' | `installer.py:1184-1186` → **`:1784-1791`**（`_run_diag` docstring） | 「Writes …beside install.log when the target exists, else into %TEMP%… the target directory does not have to exist.」 | 如实写明：报告写进目标目录；目标不必存在**但会被建出来**（preflight 的「可写」检查 `makedirs` + 探针），只有该检查自己失败才退回 `%TEMP%`；并注明 README 已明说、别再写成「不建目录」 | 同上（`installer.py:1853` 的 `out_dir = target if os.path.isdir(target) else TEMP` 说明目标此时已是目录） |
      | b | `README.md:142` → **`:161`** | `launcher\  面板（DSHLauncher.exe + harness.txt + icon.ico + **logo.png**）` | `launcher\  面板（DSHLauncher.exe + harness.txt + icon.ico）` | `installer.py:790-797` 只复制 `DSHLauncher.exe` + `icon.ico`、写 `harness.txt`；`logo.png` 由 `launcher/build/DSHLauncher.spec:17` 打进 exe，运行时走 `sys._MEIPASS`（`launcher.pyw:125-128`）→ 磁盘上不需要 |
      | c | `README.md:332` → **`:351`** | 「…（内含便携 Node 与启动器，约 **36 MB**）」 | 「…（内含便携 Node 与启动器，约 **59 MB / 58.6 MiB**）」 | 实测 `installer\dist\DSHSetup.exe` = **61,412,566 B** = 58.57 MiB |
      | c' | `installer\build\DSHSetup.spec:5` | 「keeps this exe at **~36 MB** instead of ~95 MB.」 | 「keeps this exe at **~59 MB** instead of ~95 MB.」 | 同上（注释也过时，一并改） |
      | d | `README.md:334` → **`:353`** | 「发布标签和 `VERSION` 保持一致（`v1.5.2` 里就是 `1.5.2`）」 | **不改**（该要求当前成立） | 见下「(d) 核实结论」 |
      | e | `installer.py:661-662` | 旧 docstring「自删通过 detached 进程完成」 | **无需改**（AW-8 已重写；现 `:661-662` 已是 `progress()` 方法体） | AW-8 实际结果已记录；按条目「AW-8 已改就跳过」 |

      **(d) 核实结论：没有漂移，README 属实，不改文档。**
      `git ls-remote --tags origin` 实测（末尾几条，原文照抄）：
      `refs/tags/v1.5.5 658d9571…`、`v1.5.6 c7f1531e…`、`v1.5.7 f04ff616…`、
      `v1.5.8 9cc62614…`、`v1.5.9 68382f0ea26ed4529c674112f88e18e4c8a236ee`
      ——**远端确实已有 v1.5.8 / v1.5.9**（条目原文「最新 tag 只有 v1.5.7」不成立）。
      进一步把两个 tag 拉进 `FETCH_HEAD`（只读，未创建/未改任何 tag）核对内容：
      `v1.5.8` 的 `launcher/launcher.pyw` 是 `VERSION = "1.5.8"`（2026-09-24 11:37）、
      `v1.5.9` 的是 `VERSION = "1.5.9"`（commit `68382f0`，2026-09-24 22:55）。
      工作区 `launcher.pyw:167` 仍是 `1.5.9` →
      **tag 与 VERSION 一一对应，`README.md:353` 的要求当前完全成立**，
      所以 (d) **只改文档没有对象可改**；条目原文「最新 tag 只有 v1.5.7」的前提**不成立**。
      相应地把 **硬性规则 11** 和 **「待确认」区**里过时的漂移描述一并改成事实（见那两处），
      并按条目要求在「待确认」区**登记**（结论是「无需决策」）。**没有发任何 tag、
      没有改任何版本号。**

      **(a) 实测复核**（不跑真实 `--diag`、不碰 `%USERPROFILE%\.dsh`）：
      在 `tempfile` 里取一个不存在的路径，直接调 `preflight._check_target()` →
      **调用前 `exists=False`、调用后 `exists=True`**（`status=ok`），
      即代码路径确实会 `makedirs` 目标目录；`--diag` 正是经 `preflight.run(target)`
      走这一项（`installer.py:1829`），所以文档「不创建安装目录」与实现相反，已按上表改文档。

      **(b) 复核**：`launcher.pyw:125-131` 冻结时 `LOGO = sys._MEIPASS\logo.png`，
      非冻结才读 `LAUNCHER_DIR\logo.png`；`DSHLauncher.spec` 的 `datas` 把
      `logo.png` 打进 exe。安装器（`installer.py:790-797`）不复制它 → 安装后的
      `launcher\` 里没有 `logo.png`，README 列表错，已删。**这是文档错，不是代码退化**
      （面板要的图在 exe 内，安装器无需再放一份）。

      **(c) 复核**：`stat` 实测 `installer\dist\DSHSetup.exe` = 61,412,566 B
      （= 58.57 MiB = 61.4 MB），与条目给的 58.6 MiB 一致。

      **(e) 复核**：`installer.py:661-662` 现在是 `progress()` 的实现，条目里那句旧
      docstring 已在 AW-2/AW-8 重写时消失 → 按条目约定跳过。

      **验证**：
      - `python scripts\selfcheck.py` → **5 项：5 通过，0 失败，0 跳过**，退出码 0
        （security **177** 条、linkcheck **48** 条，与基线一致；本项只改文档/docstring
        文本，未动任何被测逻辑，也没加/删用例）。
      - 复核方式：逐条 `file:line` 对照上表（含「条目行号 → 现行号」映射），
        并附一次 `preflight._check_target` 的最小实测（(a)）与 `stat`（(c)）、
        `git ls-remote --tags` + 两个 tag 的内容核对（(d)）。
      - **数据安全**：本项只改文档（README / spec 注释 / docstring），
        没有运行 `C:\Users\sechen\deepseek\uninstall.bat`、没有 `taskkill`、
        没有碰注册表（真实卸载键仍是「不存在」，用户决定不恢复，我没有去还原）、
        没有碰 `%USERPROFILE%\.dsh`；`C:\Users\sechen\dsh-src` 未动。
        唯一一次「接近真实」的动作是 `preflight._check_target()`，但目标指向
        `tempfile` 临时目录，与真实安装目录无关。

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
- ~~**发版流程漂移怎么处理？**~~ —— **2026-10-17 AW-11 核实：没有漂移，无需决策。**
  远端 tag 已有 `v1.5.8`、`v1.5.9`（`git ls-remote --tags origin`），且 `v1.5.9` 那份
  `launcher/launcher.pyw` 的 `VERSION` 就是 `1.5.9`（`v1.5.8` 同理是 `1.5.8`），
  与 `README.md` 里「发布标签和 VERSION 保持一致」的要求相符。原先记的
  「最新 tag 只有 v1.5.7」已过时（硬性规则 11 已同步改成事实）。
  **没有补发/新增任何 tag，也没有改任何版本号。**
  （顺带一提：tag 序列里缺 `v1.5.4`——从 `v1.5.3` 直接跳到 `v1.5.5`——属历史跳号，
  不影响 tag 与 VERSION 的一致性；如需补齐由你定。）
- ~~**`repo/` 要不要移出安装目录？**~~ —— **2026-10-17 已解决，用户批准「两个都做」**：
  (1) 本机 `C:\Users\sechen\deepseek\uninstall.bat` 已用修好的生成器重新生成并就地替换
  （旧版留底 `autowork-backups\deepseek-uninstall-OLD-20261017-114837.bat.bak`）；
  (2) `repo/` 已移到 **`C:\Users\sechen\dsh-src`**（51 项，`.claude`/`.agents` 完好）。
  安装根现在只剩 `harness/ launcher/ runtime/ install.log shortcuts.txt uninstall.bat`。
  ⚠️ **但替换上去的那版仍带着 AW-6 的两条过宽删除**（`del "%USERPROFILE%\Desktop\DSH*.lnk"`
  通配删桌面、`rmdir /s /q …\Programs\DSH` 递归删整个开始菜单文件夹）。
  **AW-6 做完后应再重新生成一次并替换**，那才是最终形态。
- **`--auto` 默认目标改成什么？** AW-9 已**实现为「强制必须显式传 `--dir`」**
  （理由见 AW-9 实际结果：fail-closed，且不破坏唯一记录在案的调用方）。
  如果你更想要「默认临时目录」，说一声，改回去是纯函数 `_auto_target` 里一行的事。
- **要不要给仓库加 LICENSE？** 目前没有。

## 收尾

队列清空（全部 `[x]` 或 `BLOCKED`）后**停下来**，在文件末尾写一节「## 作业总结」：
逐条列出完成了什么、验证结果（跑了哪些自检）、`BLOCKED` 项及原因、待确认项，
并特别注明 **`HKCU\...\Uninstall\DeepSeekHarness` 有没有被动过、是否完好**
以及 **`C:\Users\sechen\deepseek\repo` 是否还在**。
然后向用户报告。**不要自己发明新条目继续做。**
