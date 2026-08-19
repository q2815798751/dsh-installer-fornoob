# DeepSeek Harness 一键安装包（Windows）

把 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 装到一台
Windows 电脑上，全程不需要命令行。安装后会在桌面生成「DSH 启动器」，一键
**启动后端 / 打开网页 / 关闭 / 最小化到系统托盘**。

> 面向电脑小白：双击 → 下一步 → 等待 → 完成。就这么简单。

---

## 一、快速开始

### 1. 安装

1. 双击 `DSHSetup.exe`（一键安装程序）。
2. 选择安装目录（默认 `%LOCALAPPDATA%\DeepSeekHarness`），点击 **开始安装**。
3. 等待依赖下载完成。**首次安装需要联网**，耗时约 5~20 分钟，占用约 2 GB 磁盘。
4. 安装完成后，勾选「立即启动」并点击 **完成**。

安装程序会自动：

- 解压 DeepSeek Harness 源码与内置 Node.js 运行时（无需预先安装 Node）；
- 运行 `pnpm install` 安装全部依赖；
- 在**桌面**和**开始菜单**创建「DSH 启动器」快捷方式；
- 在「设置 → 应用」登记卸载入口。

### 2. 使用

双击桌面的 **DSH 启动器**，会看到一个小窗口：

| 按钮 | 作用 |
| --- | --- |
| ▶ 启动 | 在后台启动 DeepSeek Harness 后端（`dsh web`，监听 `127.0.0.1:3080`） |
| ↗ 打开 | 用 Chrome 打开网页界面（若后端未运行会自动先启动） |
| ■ 关闭 | 停止后端进程 |
| —（标题栏） | **最小化到系统托盘**，后端继续运行 |

窗口右上角的 `—` 按钮会把窗口隐藏到**系统托盘**（通知区域），后端不受影响。
托盘图标：

- **双击** 或选「显示 / 隐藏窗口」→ 恢复窗口；
- 右键菜单：启动后端 / 打开网页 / 关闭后端 / 退出。

> 提示：关闭启动器窗口（✕ / 退出）只关闭窗口本身，**后端会继续运行**；
> 需要彻底停止时点「关闭」或使用托盘菜单。

### 3. 首次打开网页后

1. 浏览器自动打开 `http://127.0.0.1:3080`（Chrome；未安装 Chrome 时可手动访问）。
2. 到 **设置 → 模型** 填入你的 DeepSeek API Key（没有的话去
   https://platform.deepseek.com 申请）。
3. 之后就可以在网页里和 Agent 对话、运行任务了。

### 4. 卸载

- 方式一：**设置 → 应用 → DeepSeek Harness → 卸载**；
- 方式二：运行安装目录里的 `uninstall.bat`。

卸载会停止后端、删除快捷方式、删除注册信息与安装目录。

---

## 二、目录结构（安装后）

```
DeepSeekHarness\
├── repo\          DeepSeek Harness 源码（含构建产物）
├── runtime\       便携版 Node.js（node.exe / npm / corepack）
├── launcher\      DSH 启动器（DSHLauncher.exe + repo.txt）
│   └── data\      运行状态（pid.txt、web.log、error.log）
├── uninstall.bat  一键卸载
└── install.log    安装日志
```

## 三、常见问题（FAQ）

**Q：安装时提示「pnpm install 失败」？**
安装目录下 `install.log` 有完整日志。通常是网络问题（npm 仓库不通），请检查
网络/代理后点「重试」。也可以先手动打开一次 https://registry.npmjs.org 确认可访问。

**Q：没有 Chrome 怎么办？**
启动器的「打开」按钮使用 Chrome（`Program Files` 下的 Google Chrome）。
未安装 Chrome 时，启动后端后手动在任意浏览器访问 `http://127.0.0.1:3080` 即可。

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
│   ├── make-icon.py  生成 icon.ico
│   └── build\         PyInstaller spec
├── installer\        一键安装程序源码（installer.py + make-shortcut.ps1）
│   └── build\         PyInstaller spec
├── payload\          安装负载（构建时生成，不入库）
└── scripts\
    └── build.ps1     一键构建脚本
```

### 前置要求（构建机）

- Windows 10/11（x64）
- Python 3.10+（含 tkinter），`pip install pyinstaller`
- 一份已 `pnpm install` 好的 deepseek-harness 源码（用于打源码包）

### 构建步骤

```powershell
# 1) 把 deepseek-harness 源码放到本机（或用环境变量指向它）
#    scripts\build.ps1 默认从 C:\Users\<you>\deepseek-harness 打包源码，
#    可自行修改脚本里的路径。

# 2) 一键构建：启动器 exe → 下载便携 Node → 打源码包 → 安装程序 exe
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

产物：

| 文件 | 说明 |
| --- | --- |
| `launcher\dist\DSHLauncher.exe` | 启动器（启动/打开/关闭/最小化托盘） |
| `installer\dist\DSHSetup.exe` | 一键安装程序（内含全部负载，约 90 MB） |

### 自检

```powershell
# 启动器自检（真实启动/停止一次 dsh web，输出到 launcher\data\selftest*.txt）
python launcher\launcher.pyw --selftest-tray
python launcher\launcher.pyw --selftest

# 安装程序自检（headless 完整安装到临时目录，不创建快捷方式/注册表）
python installer\installer.py --auto --dir .\dist\test-install
```

---

## 五、技术要点

- **启动器**：`tkinter` 无边框窗口；后端通过
  `node --import tsx/esm apps/cli/src/bin.ts web` 启动；状态用 3080 端口探测；
  关闭时按 `pid.txt` + `netstat` 双重定位进程树并 `taskkill /T /F`。
- **最小化到托盘**：纯 `ctypes` 调用 `Shell_NotifyIcon`，自带消息循环线程，
  与 tkinter 主循环通过队列通信——零第三方依赖。
- **安装程序**：PyInstaller onefile，负载（源码 tar.gz + 便携 Node zip +
  启动器 exe）全部内嵌；安装时用内嵌 corepack 运行 `pnpm install` 拉依赖；
  快捷方式用 WScript.Shell 生成；卸载走 `uninstall.bat`（UTF-16LE，中文无乱码）。
- **隐私**：安装过程不收集任何数据，不写系统级目录（默认装在用户目录下），
  不需要管理员权限。

## 六、许可

- 框架本体：DeepSeek Harness（MIT，见上游仓库 LICENSE）。
- 本仓库（安装器/启动器/构建脚本）：MIT。
