# DeepSeek Harness 一键安装包（Windows）

把 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 装到一台
Windows 电脑上，全程不需要命令行。安装后会在桌面生成「DSH 启动器」，一键
**启动后端 / 打开网页 / 关闭 / 最小化到系统托盘**。

> 内置框架版本：**deepseek-harness v0.1.5-rc.2**（`dsh-v0.1.5-rc.2`）。

> 源码与发布：https://github.com/q2815798751/dsh-installer-fornoob （私有仓库，
> 最新安装包在 Releases 页面下载）

> 面向电脑小白：双击 → 下一步 → 等待 → 完成。就这么简单。

---

## 一、快速开始

### 1. 安装

1. 双击 `DSHSetup.exe`（一键安装程序）。
2. 选择安装目录（默认 `%LOCALAPPDATA%\DeepSeekHarness`），点击 **开始安装**。
3. **先做环境检查**：程序会逐项检查网络连接、磁盘空间、目录权限、端口占用等，
   把结果列出来。全部通过后弹窗询问「是否开始安装」，你确认了才会真正开始写磁盘。
4. 等待依赖下载与构建完成。**全程需要联网**，耗时约 10~25 分钟，占用约 4~5 GB 磁盘。
5. 安装完成后，勾选「立即启动」并点击 **完成**。

安装程序会自动：

- 解压 DeepSeek Harness 源码与内置 Node.js 运行时（**无需预先安装 Node**）；
- 运行 `pnpm install` 安装全部依赖；
- 运行 `pnpm build` 构建服务端与前端产物（这一步是必须的，`dsh web` 没有
  构建产物根本起不来）；
- 在**桌面**和**开始菜单**创建「DSH 启动器」快捷方式；
- 在「设置 → 应用」登记卸载入口。

> **不需要安装任何编译器或开发工具。** 早期版本（0.1.3）依赖的 `fs-ext`
> 原生模块需要 Visual Studio C++ 才能编译，全新电脑上必然装不上；上游从
> 0.1.5 起已经把它换成了仓库内自带的实现，所以现在整条链路只需要纯 JS
> 工具链。详见「技术要点」。

### 2. 使用

双击桌面的 **DSH 启动器**，会看到一个小窗口：

| 按钮 | 作用 |
| --- | --- |
| ▶ 启动 | 在后台启动 DeepSeek Harness 后端（`dsh web`，监听 `127.0.0.1:3080`） |
| ↗ 打开 | 用**系统默认浏览器**打开网页界面（若后端未运行会自动先启动） |
| ■ 关闭 | 停止后端进程 |
| ↻ 检查更新 | 获取官方发布列表，选一个版本原地更新（见下一节） |
| —（标题栏） | **最小化到系统托盘**，后端继续运行 |

窗口右上角的 `—` 按钮会把窗口隐藏到**系统托盘**（通知区域），后端不受影响。
托盘图标：

- **双击** 或选「显示 / 隐藏窗口」→ 恢复窗口；
- 右键菜单：启动后端 / 打开网页 / 关闭后端 / 退出。

> 提示：关闭启动器窗口（✕ / 退出）只关闭窗口本身，**后端会继续运行**；
> 需要彻底停止时点「关闭」或使用托盘菜单。

### 3. 更新到新版本

官方发布新版本后，点启动面板上的 **↻ 检查更新**：

1. 窗口列出官方的全部发布，分 **正式版** 和 **测试版** 两个页签。点某个
   版本，右边显示它的更新说明（就是官方发布说明的正文）。
2. 选中要装的版本，点 **更新到此版本**。
3. 先跑一遍**环境检查**：官方发布接口 / 源码下载源 / 依赖源三处网络、磁盘
   空间、目录权限、内置 Node 运行时、后端运行状态，逐项列结果。**红色**
   项要处理掉，黄色只是提醒。
4. 检查通过后确认，开始更新：**下载源码 → 解压 → 重建 → 试运行**。全程有
   进度条和实时日志，约 **5~20 分钟**，取决于网速。
5. 完成后点 **启动后端** 就能用了。

几点说明：

- **更新是整份替换**。上游只发源码、没有预编译产物，所以更新一个新版本 =
  下载该版本的源码覆盖 `repo\`，再跑一次 `pnpm install` + `pnpm build`。
  已经下载过的依赖（`node_modules`）会搬到新目录直接复用，不会重新下载，
  所以第二次更新比第一次安装快得多。
- **失败会自动还原**。过程中任何一步出错，或者新版本装完却起不来（试运行
  没监听到端口 / 没取到登录令牌），程序会把旧版本原样放回去。最坏的结果是
  「还是原来那个版本」，不会留下装坏的环境。
- **更新前会先停掉后端**，更新完不会自动启动，需要你自己点「启动」。
- **正式版页签目前是空的**。上游 deepseek-harness 至今发布的全部是
  `alpha` / `rc` 预览版，还没发过正式版（`vX.Y.Z`）。所以正式版页签会一直
  显示「上游暂无正式版」，而所有发布都落在测试版页签里。这是上游的现状，
  不是检查更新出错了。
- 完整日志在 `launcher\data\update.log`。

> 「检查更新」按钮是启动器 v1.4.0 才有的。**已经装过旧版本的机器上不会自己
> 出现这个按钮**，需要跑一次最新的 `DSHSetup.exe` 覆盖安装（你的 API Key 和
> 会话记录不受影响），之后就能用启动器自助更新了。

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

---

## 二、目录结构（安装后）

```
DeepSeekHarness\
├── repo\          DeepSeek Harness 源码（含构建产物）
│   └── node_modules\  依赖（更新时会被搬到新版本目录复用）
├── runtime\       便携版 Node.js（node.exe / npm / corepack）
├── launcher\      DSH 启动器（DSHLauncher.exe + repo.txt）
│   └── data\      运行状态（pid.txt、web.log、error.log、update.log、version.json）
├── uninstall.bat  一键卸载
└── install.log    安装日志
```

更新过程中会临时出现 `repo.new\`（新版本源码）和 `repo.old\`（旧版本备份）；
正常更新完两个都不留，更新失败时回滚后也会清掉。

## 三、常见问题（FAQ）

**Q：环境检查有几项是黄色警告，还能装吗？**
能。只有**红色**项会拦住安装（网络不通、磁盘不够、目录不可写、系统不满足），
黄色只是提醒，可以继续。常见的黄色项：

- **长路径未启用** —— 检查结果里会给出「最长路径预计 N 字符 / 上限 260」。
  依赖树里最深的一个文件在安装目录之下 215 层字符（AWS SDK 的一个子模块），
  所以**安装目录本身的长度**决定了会不会撞上 Windows 的 260 字符上限：
  默认目录 `%LOCALAPPDATA%\DeepSeekHarness` 算下来正好是 260，属于压线。
  Node 和 pnpm 内部会用 `\\?\` 前缀绕过这个限制，所以实测能装上；但如果你
  选了更长的目录（比如放在「文档」下的中文路径），安装中途可能会报路径过长。
  真遇到了，把安装目录换成短的（例如 `D:\DSH`）再装一次即可。
- **端口 3080 被占用** —— 多半是旧版本还在后台跑。先运行旧安装目录里的
  `uninstall.bat`，或者重启电脑。
- **已安装旧版本** —— 继续装会覆盖程序文件，你的 API Key 和会话记录不受影响。

**Q：环境检查里网络显示「直连失败，已改用系统代理」？**
说明你这台机器只能通过代理上网。Windows 的代理设置写在「Internet 选项」里，
但 pnpm 只认环境变量，所以默认情况下它不会走代理 —— 表现就是「莫名其妙下载
失败」。安装程序会先直连试一次，直连不通才用你系统里配置的代理，并把代理传给
pnpm。**不放心的话可以先关掉代理软件再重新检查。**

**Q：安装时提示「依赖下载失败」或「构建失败」？**
安装目录下 `install.log` 有完整日志（包含 pnpm 的全部输出）。通常是网络问题，
检查网络/代理后点「重试」即可 —— 已经下载过的部分会跳过，不会从头再来。
也可以先手动打开一次 https://registry.npmjs.org 确认能访问。

**Q：没有装 Chrome 怎么办？**
不用管。启动器的 **↗ 打开** 按钮调用的是**系统默认浏览器**，Chrome / Edge /
Firefox / 其他都行，装哪个就用哪个。万一连默认浏览器都调不起来，程序会退而
依次尝试 Edge 和 Chrome；都不行时会在界面上提示你手动访问日志里打印的地址。

**Q：需要装 Visual Studio / Node.js / Python 吗？**
都不需要。Node.js 是内置的便携版，构建工具是纯 JS 的，整个安装过程不碰任何
C++ 编译器 —— 哪怕电脑上什么开发工具都没有也能装成功。

**Q：更新要多久？中途关掉会怎样？**
下载源码 + `pnpm install` + `pnpm build`，约 **5~20 分钟**（第一次更新之后依
赖有缓存，通常更快）。中途可以点「取消更新」，已经下载/构建的部分会被丢弃
并还原到当前版本。**更新期间不要退出启动器**（启动器会拦住 ✕），因为更新
线程在启动器进程里。

**Q：更新会不会把现在能用的版本弄坏？**
不会。更新失败（网络断、磁盘满、构建报错、新版本起不来）都会自动把旧版本
放回去，最坏的结果是「还是原来那个版本」。真遇到回滚也失败（罕见），日志
`launcher\data\update.log` 会写明 `repo.old` 和 `repo` 哪个是好的，手工改名
即可。

**Q：为什么「正式版」页签是空的？**
因为上游 deepseek-harness 至今只发过 `alpha` / `rc` 预览版，没有正式版。
页签不是坏了，是上游确实没发。等上游发一个 `vX.Y.Z`，它会自动出现在那里。

**Q：点「启动」后一直显示「已停止」？**
看 `launcher\data\web.log` 和 `launcher\data\error.log`。常见原因：端口 3080 被
占用（先点「关闭」再试）、磁盘空间不足、杀毒软件拦截了后台进程。

**Q：最小化到托盘后找不到窗口了？**
双击托盘里的 DSH 图标即可恢复；图标藏在任务栏右侧的小箭头（^）里时可先展开。

**Q：想换端口？**
安装后编辑 `launcher\repo.txt` 旁无端口设置；如需换端口，可设置环境变量
`DSH_LAUNCHER_PORT=3080` 后再启动（改数字即可）。

**Q：这是官方安装包吗？**
不是。这是为 DeepSeek Harness 框架做的社区分发安装器，框架本体来自
<https://github.com/deepseek-ai/deepseek-harness>（MIT 协议）。

---

## 四、从源码构建（开发者）

仓库内容：

```
dsh-installer\
├── launcher\         启动器源码（launcher.pyw，纯标准库 + tkinter/ctypes）
│   ├── updater.py    更新引擎（发布列表 / 环境检查 / 下载重建 / 回滚）
│   ├── update_ui.py  「检查更新」窗口（列表 + 更新日志 + 进度 + 实时日志）
│   ├── test-updater.py  更新/回滚自检（合成安装目录，不需要真实环境）
│   ├── make-icon.py  生成 icon.ico
│   └── build\         PyInstaller spec
├── installer\        一键安装程序源码
│   ├── installer.py       向导 + 安装流程（依赖、构建、快捷方式、卸载）
│   ├── preflight.py       安装前环境检查
│   ├── make-shortcut.ps1  生成快捷方式
│   └── build\             PyInstaller spec
├── payload\          安装负载（构建时生成，不入库）
└── scripts\
    └── build.ps1     一键构建脚本
```

### 前置要求（构建机）

- Windows 10/11（x64）
- Python 3.10+（含 tkinter），`pip install pyinstaller`
- 可选：一份 deepseek-harness 源码（用于打源码包）。不准备也行 ——
  `scripts\build.ps1` 在本地没有源码时会自动下载内置版本 v0.1.5-rc.2。

### 构建步骤

```powershell
# 1) 打包的 deepseek-harness 版本固定为 v0.1.5-rc.2（scripts\build.ps1 里的 $HARNESS_TAG）。
#    build.ps1 优先用默认路径 C:\Users\<you>\deepseek-harness，也可用 -HarnessDir 指定；
#    本地没有源码时会自动下载内置版本，无需手动准备。
#    打包前会校验该目录 package.json 的版本是不是 $HARNESS_VERSION，不符会给出警告。
#    ⚠ 换版本时三处要一起改：$HARNESS_TAG、$HARNESS_VERSION，以及
#      installer\installer.py 里的 HARNESS_COMMIT（该 tag 的 commit SHA，
#      安装时作为 DSH_CLIENT_COMMIT_HASH 注入构建）。

# 2) 一键构建：启动器 exe → 下载便携 Node → 打源码包 → 安装程序 exe
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

产物：

| 文件 | 说明 |
| --- | --- |
| `launcher\dist\DSHLauncher.exe` | 启动器（启动/打开/关闭/最小化托盘） |
| `installer\dist\DSHSetup.exe` | 一键安装程序（内含全部负载，约 95 MB） |

### 自检

```powershell
# 启动器自检（真实启动/停止一次 dsh web，输出到 launcher\data\selftest*.txt）
python launcher\launcher.pyw --selftest-tray
python launcher\launcher.pyw --selftest
# 更新链路自检（拉官方发布列表 + 跑一遍环境检查，不写盘，输出 selftest-update.txt）
python launcher\launcher.pyw --selftest-update

# 更新回滚自检（合成一个安装目录，一分钟出结果；覆盖正常更新/构建失败/试运行
# 失败/中途取消/依赖已迁移未切换/切换中途失败 六条路径，全部通过才返回 0）
python launcher\test-updater.py

# 安装程序自检（headless 完整安装到临时目录，不创建快捷方式/注册表）
python installer\installer.py --auto --dir .\dist\test-install
```

---

## 五、技术要点

- **启动器**：`tkinter` 无边框窗口；后端通过
  `node --import tsx/esm apps/cli/src/bin.ts web --no-open` 启动；状态用 3080
  端口探测；关闭时按 `pid.txt` + `netstat` 双重定位进程树并 `taskkill /T /F`。
- **默认浏览器**：`os.startfile` 走 ShellExecute，天然尊重系统默认浏览器与
  单窗口标签复用；失败再退 `webbrowser`，最后按路径找 Edge / Chrome。
- **登录令牌**：`dsh web` 每次启动都会生成一个新的登录令牌，不带令牌访问会
  返回 401。令牌只出现在后端的启动日志里，所以启动器记录 `web.log` 的读取
  偏移量、从当前这次运行写下的内容里取 URL —— 上一轮运行的令牌绝不会被复用。
- **最小化到托盘**：纯 `ctypes` 调用 `Shell_NotifyIcon`，自带消息循环线程，
  与 tkinter 主循环通过队列通信——零第三方依赖。
- **安装程序**：PyInstaller onefile，负载（源码 tar.gz + 便携 Node zip +
  启动器 exe）全部内嵌；安装时补 corepack 垫片 → `pnpm install` 拉依赖 →
  `pnpm build` 构建产物；快捷方式用 WScript.Shell 生成；卸载走
  `uninstall.bat`（UTF-16LE，中文无乱码）。
- **为什么要 `pnpm build`**：`dsh web` 直接跑源码时，服务端要 `lib/*.js`、
  浏览器端要各包的 `lib/client.js`，缺任何一份都会以
  `client bundles not found; run \`pnpm run build\` before launch` 退出。
  只跑 `pnpm install` 是不够的。
- **环境预检**：安装前跑 `installer\preflight.py`，覆盖系统/磁盘/目录权限/
  长路径/内存/网络/代理/端口/已装版本。网络那一项是真的发一次 HTTPS 请求，
  而不是探测端口——只探测端口的话，代理或运营商劫持会「连得上但没数据」，
  这种故障要等到二十分钟后的 pnpm 报错才暴露。
- **更新**：`launcher\updater.py`。发布列表走 GitHub API（`prerelease` 标记
  与版本号后缀两个信号一起判断正式版/测试版，因为上游把所有发布都标成了
  prerelease）；源码从 codeload 取，和 `scripts\build.ps1` 打包用的是同一个
  地址。**原地更新用「换目录」而不是「覆盖解压」**：新源码解到 `repo.new`，
  把 `node_modules` 移过去（同盘改名，不复制），再把 `repo` 改名 `repo.old`、
  `repo.new` 改名 `repo`。这样既不会留下旧版本里已被删除的残留文件，又省掉
  重新下载依赖的大头。任何一步失败（含新版本起不来的**冒烟测试**——真启动
  一次、等端口、等日志里的登录令牌）都会把 `node_modules` 搬回去并复位目录，
  所以失败的代价是「还是旧版本」，而不是「装坏了」。
- **实时进度**：下载按 `Content-Length` 算百分比；`pnpm install` / `pnpm build`
  的输出逐行 tee 进 `update.log` 并推给界面，这两步时长不可预测，所以进度条
  切成不确定态、下面给滚动日志，而不是假造一个百分比。
- **一处上游适配**：构建时注入 `DSH_CLIENT_COMMIT_HASH`。payload 里没有
  `.git`，而上游构建脚本会跑 `git rev-parse HEAD`；两者都没有时它直接抛错
  （`scripts/client-build-environment.ts`）。`$HARNESS_TAG` 换版本时，
  `installer.py` 里的 `HARNESS_COMMIT` 要跟着换成该 tag 的 commit SHA。
- **隐私**：安装过程不收集任何数据，不写系统级目录（默认装在用户目录下），
  不需要管理员权限。

## 六、许可

- 框架本体：DeepSeek Harness（MIT，见上游仓库 LICENSE）。
- 本仓库（安装器/启动器/构建脚本）：MIT。
