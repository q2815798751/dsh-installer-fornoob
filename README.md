# DeepSeek Harness 一键安装包（Windows）

把 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 装到一台
Windows 电脑上，全程不需要命令行。安装后会在桌面生成「DSH」，一键
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
- 在**桌面**和**开始菜单**创建「DSH」快捷方式（图标是官方鲸鱼）；
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

双击桌面的 **DSH**，会看到一个小面板：

| 按钮 | 作用 |
| --- | --- |
| ▶ 启动 / ↗ 打开网页 | **同一个按钮**，跟着状态变：没跑时是「启动」，跑起来了变成「打开网页」 |
| ■ 停止 | 停止后端进程（没在跑时是灰的） |
| ↻ 检查更新 | 更新 dsh 本体或面板自己（见下一节） |
| —（标题栏） | **最小化到系统托盘**，后端继续运行 |

点「启动」后按钮会变成「正在启动」并出现一条进度条——后端起来要几秒（实测 npm 布局 1.9 秒，
源码布局 5.5 秒），这段时间**面板不会卡住**，随便拖动。就绪后状态灯变绿，按钮变成「打开网页」。
起不来会变成「启动失败 / 重试启动」，并提示去看 `data\web.log`。

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
3. 选中后点右边那个蓝色的按钮（写着 **更新到 v0.1.6-alpha.2**，具体版本号跟着你选的那个变）
   → 先跑一遍**环境检查** → 确认 → 更新。
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

1. 点面板里的 **↗ 打开网页**，会调用**你系统的默认浏览器**打开网页界面
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
│   └── .dsh-installed.json  安装完成标记（重试时据此跳过重复下载）
├── runtime\       便携版 Node.js（node.exe / npm / corepack）
├── launcher\      面板（DSHLauncher.exe + harness.txt + icon.ico + logo.png）
│   └── data\      运行状态（pid.txt、web.log、error.log、update.log、version.json）
├── uninstall.bat  一键卸载
├── install.log    安装日志（排障只看这一个文件就够）
├── smoke.log      试运行输出 —— 只在试运行失败时留下，含登录令牌，别外发
└── diag-*.txt     `--diag` 生成的诊断报告（跑过才有）
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
先看安装目录下的 `install.log` —— 它开头就是这台机器的环境（版本、是否管理员、
Windows 版本、磁盘、代理、**能不能创建目录链接**），结尾有 `-- 诊断 --` 一段，
直接写明判断和建议。**报障只发这一个文件**（`smoke.log` 含登录令牌，别外发）。

**失败提示里会写「可以右键以管理员身份运行再试」的情况**，只有两类：文件或注册表
权限不足、以及运行时被杀软拦掉。其他情况不会提 —— 提了也没用。

- **权限类**（日志里是 `EPERM` / `EACCES`，但不是 `symlink`）：右键安装包 →
  「以管理员身份运行」再装一次通常能过。已经是以管理员身份运行的就不用试了。
- **网络**：日志里出现 `ETIMEDOUT` / `ECONNREFUSED` / `npm ERR!`。检查网络/代理
  后点「重试」；也可以先手动打开一次 https://registry.npmjs.org 确认能访问。
  **管理员权限对网络问题没有任何帮助**，别在这里浪费时间。
- **这台机器建不了目录链接**：日志里出现 `EPERM: operation not permitted, symlink`
  和 `errno: -4048`，同时「本机链接能力」那行是 `FAIL`。dsh 启动时要在
  `%USERPROFILE%\.dsh` 里建目录链接（junction），**这一步不需要管理员权限**，
  所以「用管理员身份运行」帮不上忙。要查的是：本地安全策略 → 用户权限分配 →
  「创建符号链接」是否被清空、安全软件是否拦了 `runtime\node.exe`、
  或 `%USERPROFILE%` 是否被重定向到了网络盘。

**Q：装到一半失败了，重试要重新下载吗？**
不用。dsh 本体装好过就留着，重试会直接复用（日志里写 `reusing harness v…`），
几秒就能走到失败的那一步。想彻底重装就删掉整个安装目录，或先运行 `uninstall.bat`。

**Q：想让我们帮你定位问题？**
在安装目录里跑（或对安装包 exe 加 `--diag` 参数）：

```powershell
DSHSetup.exe --diag --dir "安装目录"
```

它会生成 `diag-<时间>.txt`（不安装、不写注册表、目标目录不存在也能跑），
把这个文件和 `install.log` 发出来即可。

**Q：双击安装包提示「Windows 已保护你的电脑 / 未知发布者」，怎么办？**
这是 **SmartScreen** 的提示，不是杀毒报毒 —— 所有**没有代码签名**的程序从网上下载
后第一次运行都会弹。点 **更多信息 → 仍要运行** 就能继续安装。

想让它不弹，只有两条路：买代码签名证书，或者等下载量攒够、SmartScreen 自己认得它。
代码里没有办法绕过。

**Q：杀毒软件报毒 / 把安装包删了？**
先看报的是什么。如果报的是 `Trojan:Win32/Sabsik.TE.A!ml`、`Wacatac.B!ml` 这类带
**`!ml`** 后缀的名字，那是**机器学习启发式误报**，不是特征码命中 —— PyInstaller 打包
的程序因为要「自解压再运行」，形状和 dropper 相似，被误判得很常见。

（v1.5.5 起两个 exe 都带了完整的版本信息资源，以前的包里完全没有 —— 属性里「文件版本」
显示「无」，看起来就更可疑了。）

确认是误报的话，可以提交给微软复核（免费，通常几天内有结果）：
<https://www.microsoft.com/en-us/wdsi/filesubmission> 选「I believe this file is
incorrectly detected as malware」。

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
双击托盘里的鲸鱼图标即可恢复；图标藏在任务栏右侧的小箭头（^）里时可先展开。

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
│   ├── test-security.py 安全回归自检（下载校验 / PATH / 进程过滤 / 卸载守卫）
│   ├── test-layout.py   环境检查页的布局自检（离屏渲染，查控件重叠）
│   ├── make-icon.py  从官方 path 数据生成 icon.ico + logo.png（无需字体）
│   └── build\         PyInstaller spec
├── installer\        一键安装程序源码
│   ├── installer.py       向导 + 安装流程（Node、npm 装 dsh、试运行、快捷方式、卸载）
│   ├── preflight.py       安装前环境检查
│   ├── linkcheck.py       目录链接能力探测 + 失败归因规则表
│   ├── test-linkcheck.py  上面那套规则与探针的自检
│   ├── make-shortcut.ps1  生成快捷方式
│   └── build\             PyInstaller spec
├── payload\          安装负载（构建时生成，不入库；只有便携版 Node 的 zip）
└── scripts\
    ├── build.ps1            一键构建脚本
    └── make-version-info.py 生成 exe 的版本信息资源（版本号从 VERSION 读）
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
| `launcher\dist\DSHLauncher.exe` | 面板（启动 / 打开网页 / 停止 / 托盘 / 检查更新） |
| `installer\dist\DSHSetup.exe` | 一键安装程序（内含便携 Node 与启动器，约 36 MB） |

**发布标签和 `launcher/launcher.pyw` 里的 `VERSION` 保持一致**（`v1.5.2` 里就是 `1.5.2`），
面板的自更新靠这个比较版本。

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

# 安全回归自检（下载校验 / 不用 PATH 里的 node / 系统命令走绝对路径 /
# 只杀 node.exe / 卸载脚本守卫）。它会临时导出再导入卸载注册表项，跑完还原）
python launcher\test-security.py

# 布局自检（离屏渲染面板与安装器的「环境检查」页，断言没有两个控件画在同一格上；
# 需要桌面会话，因为要起 tkinter）
python launcher\test-layout.py

# 链接探测与失败归因自检（规则表用真实失败样本断言，再在本机真跑一次探针；
# 需要 node，可用 DSH_TEST_NODE 指定，否则用 PATH 里的）
python installer\test-linkcheck.py

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
- **安装日志自己带排障信息**：`install.log` 每次运行开头写一个环境块（安装器版本、
  Windows 版本、账户、是否提权、开发者模式、磁盘、代理），紧接着一行**目录链接能力**，
  失败时结尾加 `-- 诊断 --` 一段，把失败步骤、链接能力矩阵和归因建议写在一起，
  并把 dsh 的登录令牌脱敏。所以一个 `install.log` 就能定位绝大多数安装故障。
- **链接能力探测**：`installer\linkcheck.py`。dsh 给每个 profile 建模块回退用的是
  `symlinkSync(..., "junction")` —— **junction 是重解析点，不需要管理员权限、
  不需要开发者模式**（等价于 `mklink /J`）。所以「装不上」的正确问法不是「有没有提权」，
  而是「这台机器能不能在 `%USERPROFILE%\.dsh` 里建 junction」。探测在解压完便携 Node
  之后、下载 600 MB 之前跑一次：只有**明确失败**才中止安装，探针自己没跑起来（超时、
  node 起不来）按「未知」处理、照常继续 —— 把「测不出来」当成「不行」会误杀好机器。


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

## 六、安全

这套程序会下载并执行代码、结束进程、写注册表、替换自己的可执行文件 —— 这些行为
本身就和恶意软件重合，所以这里把边界写清楚。

**已经做到的**

- **不请求管理员权限**（PE 清单是 `asInvoker`），不装服务，不写启动项 / Run 键，
  不碰系统目录。
- **系统命令一律走绝对路径**（`%SystemRoot%\System32\...`）。按裸名字调用会被 PATH
  里靠前的同名程序劫持。
- **装好的副本绝不用 PATH 里的 `node`** —— 只有内置运行时，找不到就报错。开发目录
  里才允许回退（那里本来就没有内置运行时）。
- **只杀 `node.exe`**。端口探测只用来找后端；谁监听 3080 就杀谁等于误伤别人的程序。
- **面板自更新校验 sha256**：下载下来的 exe 对不上 GitHub 发布声明的哈希就丢弃，
  原文件一个字节都不动。校验值优先**直连** GitHub API 取，直连不通才走代理 ——
  这样代理没法替自己的字节背书。
- **安装时 `npm install --ignore-scripts`**：上游的包自带各平台 prebuild，不需要跑
  任何安装脚本；显式关掉是为了永远不触发 `node-gyp`。
- **试运行只绑 `127.0.0.1`**（上游连 `--host 0.0.0.0` 都直接拒绝）。
- **日志脱敏**：dsh 启动时会打印带一次性登录令牌的 URL，`install.log` 写入前统一
  把 `token=...` 换成 `token=<redacted>`（发出去的是日志，不是凭证）。`smoke.log`
  是 dsh 自己写的、动不了，所以文档里明说它只在本机看、不要外发。
- **`--diag` 是只读的**：不装任何东西、不写注册表、不创建安装目录（目标不存在也能跑），
  报告落在安装目录或 `%TEMP%`。
- **链接能力探测不落盘**：探测用的 JS 是内嵌字符串、用 `node -e` 执行，不在 `%TEMP%`
  里生成脚本文件再执行（那正是启发式杀软盯的形状），跑完自己的临时目录也清掉。
- tar 解压有路径穿越防护；所有子进程都是 `shell=False`。

**还没做到的，说清楚**

- **exe 没有代码签名**。所以 Windows SmartScreen 会提示「未知发布者」；Defender 的
  机器学习启发式也可能误报（历史上命中过 `Trojan:Win32/Sabsik.TE.A!ml`）。这是
  PyInstaller onefile 的已知误报：它自解压到 `%TEMP%` 再执行，行为上和 dropper 一样。
  真正的解法只有两个 —— 改用 onedir 打包，或者买代码签名证书。
  **但要分清两种判定**：本机用 `MpCmdRun.exe -Scan -ScanType 3` 对构建产物做按需扫描
  一直是干净的，而**下载下来那一刻的判定更严**（云端信誉参与）。2026-09-20 实测到
  v1.5.5 的安装包在下载后被判为 `Sabsik.TE.A!ml` —— 同一个包在本机扫描是干净的。
  所以「误报还会不会出现」这件事，本机自测给不出保证，只能靠上面那两条真解法。
- **两个 exe 从 v1.5.5 起带完整版本信息资源**（CompanyName / ProductName / FileVersion /
  FileDescription / OriginalFilename / LegalCopyright）。此前完全没有 —— 属性里「文件版本」
  显示「无」，加上未签名，是启发式评分里最难看的一种组合。构建时由
  `scripts\make-version-info.py` 从 `launcher.pyw` 的 `VERSION` 生成，只有一个版本来源。
- **代理是对手时，自校验挡不住**。如果机器只能通过代理出网（校验值也只能走代理取），
  那么控制该代理的人可以同时改字节和改哈希。这种情况下整个 npm 安装链路本来也在
  他的手里 —— 不是这一处独有的问题。
- 安装时会从 npm 装 486 个包，供应链风险由上游决定，本安装器不额外引入。

回归测试在 `launcher\test-security.py`。

## 七、许可

- 框架本体：DeepSeek Harness（MIT，见上游仓库 LICENSE）。
- 本仓库（安装器/启动器/构建脚本）：MIT。
