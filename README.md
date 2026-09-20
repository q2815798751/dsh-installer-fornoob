# DeepSeek Harness 一键安装包（Windows）

把 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 装到一台
Windows 电脑上，全程不需要命令行。安装后会在桌面生成「DSH 启动器」，一键
**启动后端 / 打开网页 / 关闭 / 最小化到系统托盘 / 检查更新**。

> 源码与发布：https://github.com/q2815798751/dsh-installer-fornoob
> （最新安装包在 Releases 页面下载）

> 面向电脑小白：双击 → 下一步 → 等待 → 完成。就这么简单。

---

## 一、快速开始

### 1. 安装

1. 双击 `DSHSetup.exe`（一键安装程序）。
2. 选择安装目录（默认 `%LOCALAPPDATA%\DeepSeekHarness`），点击 **开始安装**。
3. **先做环境检查**：程序会逐项检查网络连接、磁盘空间、目录权限、端口占用等，
   把结果列出来。全部通过后弹窗询问「是否开始安装」，你确认了才会真正开始写磁盘。
4. 等待下载与安装完成（**需要联网，实测约 1 分钟**）。
5. 完成后会**自动试运行一次**新装好的后端，确认它真能起来；通过后再勾选
   「立即启动」并点击 **完成**。

安装程序会自动：

- 解压内置的便携版 Node.js 运行时（**无需预先安装 Node**）；
- 用这个 Node 自带的 npm 从**官方源**安装 DeepSeek Harness 本体到 `harness\`；
- 在**桌面**和**开始菜单**创建「DSH 启动器」快捷方式；
- 在「设置 → 应用」登记卸载入口。

> **不需要安装任何编译器或开发工具，也不需要 Visual Studio。** 装的是上游发布
> 在 npm 上的**预编译包** —— 上游自己的安装方式就是 `npx @deepseek-ai/dsh web`，
> 他们的 GitHub release 上没有任何可下载文件。所以整条链路不做本地构建。
>
> 顺便说一句：npm 11 默认不执行包的安装脚本。这里是**刻意保持**这个行为的
> （`--ignore-scripts`），因为上游的包自带各平台预编译好的二进制；而 `node-pty`
> 的安装脚本是「找不到预编译产物就现场编译」，一旦回退就会要求 MSVC。装完那次
> 试运行就是这条选择的兜底。

### 2. 使用

双击桌面的 **DSH 启动器**，会看到一个小窗口：

| 按钮 | 作用 |
| --- | --- |
| ▶ 启动 | 在后台启动 DeepSeek Harness 后端（`dsh web`，监听 `127.0.0.1:3080`） |
| ↗ 打开 | 用**系统默认浏览器**打开网页界面（若后端未运行会自动先启动） |
| ■ 关闭 | 停止后端进程 |
| ↻ 检查更新 | 更新 dsh 本体或启动器自己（见下一节） |
| —（标题栏） | **最小化到系统托盘**，后端继续运行 |

窗口右上角的 `—` 按钮会把窗口隐藏到**系统托盘**（通知区域），后端不受影响。
托盘图标：

- **双击** 或选「显示 / 隐藏窗口」→ 恢复窗口；
- 右键菜单：启动后端 / 打开网页 / 关闭后端 / 退出。

> 提示：关闭启动器窗口（✕ / 退出）只关闭窗口本身，**后端会继续运行**；
> 需要彻底停止时点「关闭」或使用托盘菜单。

### 3. 更新

启动器里有**两个互相独立的更新**，都在 **↻ 检查更新** 窗口里：

**dsh 本体**（`harness\` 里的东西，就是 AI 框架本身）

1. 窗口列出官方发布的**全部版本**，分 **正式版** 和 **测试版** 两个页签。
2. 点某个版本，右边显示它的更新说明（官方发布说明的正文，链接可点）。
   带 ★ 的是上游 npm `latest` 通道指向的版本，也就是他们推荐的默认版本。
3. 选中后点 **更新到此版本** → 先跑一遍**环境检查** → 确认 → 更新。
4. 更新完点 **启动后端** 就能用。

**启动器自己**

窗口顶部有一条横幅，发现比当前新的启动器时会提示，点 **更新启动器** 下载并
就地替换，然后点 **重启启动器** 生效。**后端不受影响。**

几点说明：

- **更新很快**。dsh 本体是从 npm 装官方预编译包，实测 **38 秒**装完（对比：老版本
  的源码+本地构建方案要 3.6 分钟）。你的设置、API Key 和会话都在 `~/.dsh`，
  更新不会碰。
- **失败会自动还原**。过程中任何一步出错，或者新版本装完却起不来（试运行没监听
  到端口 / 没取到登录令牌），程序会把旧版本原样放回去。最坏的结果是「还是原来
  那个版本」，不会留下装坏的环境。
- **更新前会先停掉后端**，更新完不会自动启动，需要你自己点「启动」。
- **正式版页签目前是空的**。上游至今发布的都是 `alpha` / `rc` 预览版，还没发过
  正式版（`vX.Y.Z`），所以 22 个版本**全部**落在测试版页签里。这是上游的现状，
  不是检查更新出错了。
- **从 1.4 及更早版本升级过来**：老的 `repo\` 源码目录会在第一次更新后彻底用不上，
  窗口会提示你删掉它（**能腾出 2 GB 以上**）。
- 完整日志在 `launcher\data\update.log`。

### 4. 首次打开网页后

1. 点启动器里的 **↗ 打开**，会调用**你系统的默认浏览器**打开网页界面
   （Chrome / Edge / Firefox 都行，装哪个就用哪个）。
2. 到 **设置 → 模型** 填入你的 DeepSeek API Key（没有的话去
   https://platform.deepseek.com 申请）。
3. 之后就可以在网页里和 Agent 对话、运行任务了。

> 网页地址带一个一次性登录令牌（形如
> `http://127.0.0.1:3080/?token=…`），每次启动后端都会变。启动器会自动从
> 后端日志里取到当前令牌再打开浏览器，所以你不需要手动拼这个地址。
> 若要在别的浏览器里手动打开，完整地址在
> `launcher\data\web.log` 的第一行（`dsh web: http://…`）；直接访问
> `http://127.0.0.1:3080` 不带令牌会返回 401 —— 这是正常的安全行为，
> 不是安装出错了。

### 5. 卸载

- 方式一：**设置 → 应用 → DeepSeek Harness → 卸载**；
- 方式二：运行安装目录里的 `uninstall.bat`。

卸载会停止后端、删除快捷方式、删除注册信息与安装目录。

> **你的设置、API Key 和会话记录在 `C:\Users\<你>\.dsh`，卸载不会删除它们。**

---

## 二、目录结构（安装后）

```
DeepSeekHarness\
├── harness\       DeepSeek Harness 本体（npm 安装的官方预编译包）
├── runtime\       便携版 Node.js（node.exe / npm / corepack）
├── launcher\      DSH 启动器（DSHLauncher.exe + harness.txt）
│   └── data\      运行状态（pid.txt、web.log、error.log、update.log、version.json）
├── uninstall.bat  一键卸载
└── install.log    安装日志
```

`launcher\harness.txt` 里写着一行路径，指向 `harness\`。启动器、更新器和安装器
都通过它找到本体，所以三者可以各自独立升级。

更新过程中会临时出现 `harness.new\`（正在装的新版本）和 `harness.old\`（旧版本
备份）；正常更新完两个都不留，更新失败回滚后也会清掉。

**用户数据不在这里**，在 `C:\Users\<你>\.dsh`：`settings.yaml`（模型配置）、
`.credentials.yaml`（API Key）、`sessions\`（会话）、`profiles\`。这也是为什么
换掉整个 `harness\` 不会丢任何东西。

## 三、常见问题（FAQ）

**Q：环境检查有几项是黄色警告，还能装吗？**
能。只有**红色**项会拦住安装（网络不通、磁盘不够、目录不可写、系统不满足），
黄色只是提醒，可以继续。

**Q：环境检查里网络显示「直连失败，已改用系统代理」？**
说明你这台机器只能通过代理上网。Windows 的代理设置写在「Internet 选项」里，
但 npm 只认环境变量，所以默认情况下它不会走代理 —— 表现就是「莫名其妙下载
失败」。安装程序会先直连试一次，直连不通才用你系统里配置的代理，并把代理传给
npm。**不放心的话可以先关掉代理软件再重新检查。**

**Q：安装时提示「dsh 安装失败」或「试运行失败」？**
安装目录下 `install.log` 有完整日志（包含 npm 的全部输出）。通常是网络问题，
检查网络/代理后点「重试」即可。也可以先手动打开一次
https://registry.npmjs.org 确认能访问。

**Q：需要装 Visual Studio / Node.js / Python 吗？**
都不需要。Node.js 是内置的便携版，装的是官方预编译包，整个安装过程不碰任何
C++ 编译器 —— 哪怕电脑上什么开发工具都没有也能装成功。

**Q：更新要多久？中途关掉会怎样？**
实测 **38 秒**（从 npm 下载约 600 MB 的包并换上去）。中途可以点「取消」，
已经下载/安装的部分会被丢弃并还原到当前版本。**更新期间不要退出启动器**
（启动器会拦住 ✕），因为更新线程在启动器进程里。

**Q：更新会不会把现在能用的版本弄坏？**
不会。更新失败（网络断、磁盘满、装完起不来）都会自动把旧版本放回去，最坏的
结果是「还是原来那个版本」。真遇到回滚也失败（罕见），日志
`launcher\data\update.log` 会写明 `harness.old` 和 `harness` 哪个是好的，
手工改名即可。

**Q：为什么「正式版」页签是空的？**
因为上游 deepseek-harness 至今只发过 `alpha` / `rc` 预览版，没有正式版。页签
不是坏了，是上游确实没发。等上游发一个 `vX.Y.Z`，它会自动出现在那里。

**Q：更新会不会删掉我的 API Key 和会话记录？**
不会。它们在 `C:\Users\<你>\.dsh`，更新只替换 `harness\` 目录。

**Q：从老版本升级上来，安装目录里那个 2 GB 的 `repo\` 是什么？**
是老版本的源码目录。1.5 起改用 npm 的预编译包，源码树不再需要了，更新完按窗口
提示删掉即可。

**Q：点「启动」后一直显示「已停止」？**
看 `launcher\data\web.log` 和 `launcher\data\error.log`。常见原因：端口 3080 被
占用（先点「关闭」再试）、磁盘空间不足、杀毒软件拦截了后台进程。

**Q：最小化到托盘后找不到窗口了？**
双击托盘里的 DSH 图标即可恢复；图标藏在任务栏右侧的小箭头（^）里时可先展开。

**Q：想换端口？**
启动前设置环境变量 `DSH_LAUNCHER_PORT=3080`（改数字即可）。

**Q：这是官方安装包吗？**
不是。这是为 DeepSeek Harness 框架做的社区分发安装器，框架本体来自
<https://github.com/deepseek-ai/deepseek-harness>（MIT 协议）。

---

## 四、从源码构建（开发者）

仓库内容：

```
dsh-installer\
├── launcher\         启动器源码（launcher.pyw，纯标准库 + tkinter/ctypes）
│   ├── updater.py    更新引擎（版本列表 / 环境检查 / npm 安装 / 回滚 / 启动器自更新）
│   ├── update_ui.py  「检查更新」窗口（列表 + 更新日志 + 进度 + 实时日志）
│   ├── test-updater.py  更新/回滚自检（合成安装目录，不需要联网）
│   ├── make-icon.py  生成 icon.ico
│   └── build\         PyInstaller spec
├── installer\        一键安装程序源码
│   ├── installer.py       向导 + 安装流程（Node、npm 装 dsh、试运行、快捷方式、卸载）
│   ├── preflight.py       安装前环境检查
│   ├── make-shortcut.ps1  生成快捷方式
│   └── build\             PyInstaller spec
├── payload\          安装负载（构建时生成，不入库；只有便携版 Node 的 zip）
└── scripts\
    └── build.ps1     一键构建脚本
```

### 前置要求（构建机）

- Windows 10/11（x64）
- Python 3.10+（含 tkinter），`pip install pyinstaller`

### 构建步骤

```powershell
# 启动器 exe → 下载便携 Node → 安装程序 exe（约 2 分钟）
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

> 在 Git Bash 里跑要留意：`/usr/bin/tar` 会顶掉 Windows 的 bsdtar。让
> `C:\Windows\System32` 排在 PATH 前面即可。

产物：

| 文件 | 说明 |
| --- | --- |
| `launcher\dist\DSHLauncher.exe` | 启动器（启动/打开/关闭/托盘/检查更新） |
| `installer\dist\DSHSetup.exe` | 一键安装程序（内含便携 Node 与启动器，约 36 MB） |

**发布标签和启动器版本号保持一致**（`v1.5.0` 里就是启动器 `1.5.0`），启动器的
自更新靠这个比较版本。

### 自检

```powershell
# 启动器自检（真实启动/停止一次 dsh web，输出到 launcher\data\selftest*.txt）
python launcher\launcher.pyw --selftest-tray
python launcher\launcher.pyw --selftest
# 更新链路自检（拉 npm 版本列表 + 跑一遍环境检查，不写盘，输出 selftest-update.txt）
python launcher\launcher.pyw --selftest-update

# 更新回滚自检（合成一个安装目录，一分钟出结果；覆盖正常更新/安装失败/试运行
# 失败/中途取消/源码布局迁移/切换中途失败 六条路径，全部通过才返回 0）
python launcher\test-updater.py

# 安装程序自检（headless 完整安装到临时目录，不创建快捷方式/注册表）
python installer\installer.py --auto --dir .\dist\test-install
```

## 五、技术要点

- **启动器**：`tkinter` 无边框窗口；后端通过
  `node harness\node_modules\@deepseek-ai\dsh\lib\bin.js web --no-open` 启动；
  状态用 3080 端口探测；关闭时按 `pid.txt` + `netstat` 双重定位进程树并
  `taskkill /T /F`。
- **两种布局都能跑**：启动器先找 npm 布局（`harness\node_modules\@deepseek-ai\dsh`），
  找不到再退回 1.4 及更早的源码布局（`repo\apps\cli\src\bin.ts`）。所以老装机
  不用重装，第一次更新就会自动迁到新布局。
- **默认浏览器**：`os.startfile` 走 ShellExecute，天然尊重系统默认浏览器与
  单窗口标签复用；失败再退 `webbrowser`，最后按路径找 Edge / Chrome。
- **登录令牌**：`dsh web` 每次启动都会生成一个新的登录令牌，不带令牌访问会
  返回 401。令牌只出现在后端的启动日志里，所以启动器记录 `web.log` 的读取
  偏移量、从当前这次运行写下的内容里取 URL —— 上一轮运行的令牌绝不会被复用。
- **最小化到托盘**：纯 `ctypes` 调用 `Shell_NotifyIcon`，自带消息循环线程，
  与 tkinter 主循环通过队列通信——零第三方依赖。
- **安装程序**：PyInstaller onefile，负载内嵌；先用内置 npm
  `npm install --ignore-scripts @deepseek-ai/dsh@latest` 装到 `harness\`，再
  **真启动一次**、等后端日志里的登录令牌，通过才算装完。快捷方式用
  WScript.Shell 生成；卸载走 `uninstall.bat`（UTF-16LE，中文无乱码）。
- **为什么用 npm 而不是源码**：上游 18 个 GitHub release **一个资产都没有**，
  官方安装方式是 `npx @deepseek-ai/dsh web`。走 npm 之后安装从 10~25 分钟
  降到约 1 分钟、磁盘从 4~5 GB 降到约 600 MB，而且不需要 pnpm 和编译器。
- **环境预检**：安装前跑 `installer\preflight.py`，覆盖系统/磁盘/目录权限/
  长路径/内存/网络/代理/端口/已装版本。网络那一项是真的发一次 HTTPS 请求，
  而不是探测端口——只探测端口的话，代理或运营商劫持会「连得上但没数据」，
  这种故障要等到几分钟后的 npm 报错才暴露。
- **更新**：`launcher\updater.py`。版本列表走 npm registry（比 GitHub 快得多，
  也才是真正能装的东西的权威）；更新说明从 GitHub release 按 `dsh-v<版本>` 取
  正文，取不到只是少一段文字，不影响更新。正式版/测试版按版本号后缀分（上游把
  所有版本都标了 prerelease，`prerelease` 位不可信），另用 npm 的 dist-tag
  标出上游推荐的那个版本。
- **原地更新用「换目录」而不是「覆盖」**：新版本装到 `harness.new`，再把
  `harness` 改名 `harness.old`、`harness.new` 改名 `harness`。装完**真启动一次**
  新版本、等端口、等日志里的登录令牌，任何一步失败都把 `harness.old` 改回来。
  所以失败的代价是「还是旧版本」，而不是「装坏了」。
- **启动器自更新**：查本仓库的 release，下载新的 `DSHLauncher.exe`。Windows
  不允许覆盖正在运行的 exe，但**允许改名** —— 所以是「下载 → 把运行中的 exe
  改名成 `.old` → 新 exe 就位 → 重启 → 下次启动时删掉 `.old`」。重启前会先
  释放单实例端口，否则新进程会以为已经有一个启动器在跑。
- **实时进度**：npm 输出逐行 tee 进 `update.log` 并推给界面；安装这一段时长
  不可预测，所以进度条切成不确定态、下面给滚动日志，而不是假造一个百分比。
- **隐私**：安装过程不收集任何数据，不写系统级目录（默认装在用户目录下），
  不需要管理员权限。

## 六、许可

- 框架本体：DeepSeek Harness（MIT，见上游仓库 LICENSE）。
- 本仓库（安装器/启动器/构建脚本）：MIT。
