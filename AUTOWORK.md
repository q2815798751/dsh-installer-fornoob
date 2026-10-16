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
    - **`dsh-linkprobe.js` 不存在**。所谓探针是 `installer\linkcheck.py:69-111` 里的
      **内嵌 JS 字符串**，用 `node -e` 执行（刻意不落盘，避免被启发式杀软盯上）；
      临时目录名才叫 `.dsh-linkprobe`。仓库历史上**从未有过任何 `.js`/`.bat` 文件**。
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

- [ ] **AW-0 建聚合自检入口 + 备份护栏（可验证性）** —— 后面所有条目的前提，必须第一个做。
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

- [ ] **AW-1 修 `test-security.py` 的注册表还原静默失效（会删真实注册项，最高优先级）**
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

- [ ] **AW-2 修卸载脚本的弱守卫与无差别删除（数据安全，最高优先级）**
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

- [ ] **AW-3 拒绝盘根与系统目录作为安装目录（数据安全）**
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

## 待确认（不要擅自做，等用户拍板）

- **卸载要不要加交互确认？** AW-2 改成白名单删除后，遇到白名单外的内容会保留并提示。
  但「要不要先问用户一句再删」属于交互决策。
- **盘根/系统目录的黑名单范围**（AW-3）：我按「盘根 + SystemRoot + ProgramFiles +
  USERPROFILE 本身」实现，是否还要包含桌面/文档根？
- **发版流程漂移怎么处理？** `launcher.pyw` VERSION = 1.5.9，最新 tag 只有 v1.5.7（AW-11）。
  是补发 tag 还是把 VERSION 降回去，属于你的发版决策。
- **`repo/` 要不要移出安装目录？** 本机 `C:\Users\sechen\deepseek\repo` 是 DSH 源码树，
  放在安装根下会被卸载脚本连锅端。AW-2 的白名单能保住它，但**更彻底的做法是把它挪走**
  （例如 `C:\Users\sechen\dsh-src`）。这是你的数据，我不擅自搬。
- **`--auto` 默认目标改成什么？** AW-9 建议改成临时目录。如果你更想「强制必须传 `--dir`」，说一声。
- **要不要给仓库加 LICENSE？** 目前没有。

## 收尾

队列清空（全部 `[x]` 或 `BLOCKED`）后**停下来**，在文件末尾写一节「## 作业总结」：
逐条列出完成了什么、验证结果（跑了哪些自检）、`BLOCKED` 项及原因、待确认项，
并特别注明 **`HKCU\...\Uninstall\DeepSeekHarness` 有没有被动过、是否完好**
以及 **`C:\Users\sechen\deepseek\repo` 是否还在**。
然后向用户报告。**不要自己发明新条目继续做。**
