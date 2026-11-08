# macOS 兼容版适配说明

本文描述 macOS 12 的 WKWebView 兼容版。使用 Xcode 与 SwiftUI 的新工作台见 [原生 macOS 说明](macos-native.md)。

VvTalk Studio 1.1.2 起支持 macOS 12 或更高版本。源码与构建脚本可用于 Apple Silicon 和 Intel Mac；本次验证与生成的发行包为 Apple Silicon（arm64），Intel 包需在 Intel Mac 上按相同步骤构建。Windows x64 的既有行为和发行方式保持不变。本文记录 macOS 版与 Windows 版的差异、路径、构建和签名方法。

## 运行方式

发行 ZIP 解压后可直接运行 `VvTalkStudio.app`，或双击 `Start-VvTalk.command`。应用包已包含 Python 与运行依赖，桌面窗口使用系统 WKWebView，不需要 WebView2。

首次打开未签名版本时，Finder 可能提示无法验证开发者。可右键应用选择“打开”，或执行：

```bash
xattr -dr com.apple.quarantine VvTalkStudio.app
```

也可以从终端使用浏览器模式或只启动本机服务：

```bash
./VvTalkStudio.app/Contents/MacOS/VvTalkStudio --browser
./VvTalkStudio.app/Contents/MacOS/VvTalkStudio --serve --port 8777
```

应用只监听 `127.0.0.1`。浏览器模式可用 `Stop-VvTalk.command` 结束；桌面模式关闭窗口即结束本地服务。

本构建的 WKWebView 不向页面暴露 `navigator.mediaDevices`，因此桌面窗口内的麦克风直录不可用；界面会提示改用浏览器模式或上传 PCM WAV。需要边录边调时，请使用 `--browser`。应用包已在 `Info.plist` 声明麦克风用途，便于以后系统 WebView 开放该能力。

启动失败时查看 `~/Library/Application Support/VvTalkStudio/startup-error.log`；桌面窗口或 WebView 初始化失败会写入同目录的 `desktop.log`，并回退到系统浏览器。

## 数据目录

macOS 默认数据目录为：

```text
~/Library/Application Support/VvTalkStudio
```

其中包含 `outputs/`、`uploads/`、`alignment-jobs/`、`runtime.json` 和日志。可用 `VVTALK_DATA_DIR` 指定独立目录。Windows 的 `%USERPROFILE%\AppData\Local\VvTalkStudio` 行为不变。

WKWebView 的站点数据由系统保存在应用容器中；`webview-storage/` 目录仍会创建，但仅 WebView2 使用其中的自定义存储路径。

## 宿主与路径探测

`/api/info` 会根据当前平台报告宿主路径：

| 宿主 | macOS 默认路径 |
| --- | --- |
| ACE Studio | `/Applications/ACE Studio.app` |
| ACE CLI | `/Applications/ACE Studio.app/Contents/Helpers/acestudio-cli` |
| Synthesizer V Studio 2 Pro | `/Applications/Synthesizer V Studio 2 Pro.app` |
| SV2 脚本目录 | `~/Library/Application Support/Dreamtonics/Synthesizer V Studio 2/scripts` |
| VOCALOID6 | `/Applications/VOCALOID6 Editor.app` |

也支持用户目录下的 `~/Applications/...`。可用以下环境变量覆盖：

- `VVTALK_ACE_CLI`：ACE CLI 可执行文件。
- `VVTALK_SV_SCRIPTS_DIR`：Synthesizer V Studio 2 的 `scripts` 目录。

ACE 试听仍要求 ACE Studio 正在运行并开启 External Agent Access。ACE 工程导入、合成和声库授权是否成功，取决于用户安装的宿主版本与授权状态。

## 自动对齐与 MFA

原版 VvTalk 的 MFA 安装器是 Windows 专用的。macOS 上可继续使用人工 CSV/TextGrid 标注，也可以把已有的 MFA 2 环境接入：

```bash
export VVTALK_MFA_PYTHON="$HOME/mfa-env/bin/python"
export VVTALK_MFA_SCRIPT="$HOME/mfa-env/bin/mfa"
export VVTALK_MFA_DICTIONARY="$HOME/Documents/Vocaloid/VvTalk_1.0.1/misc/mfa/mfa_model_v20.dict"
export VVTALK_MFA_MODEL="$HOME/Documents/Vocaloid/VvTalk_1.0.1/misc/mfa/mandarin_mfa.zip"
```

若使用完整的 VvTalk 目录，可只设置 `VVTALK_SOURCE`。程序会依次识别 `bin/python`、`bin/mfa-script.py`、`bin/mfa`，以及 Windows 的 `python.exe`、`Scripts/mfa-script.py` 布局。日语和英语仍分别使用 `VVTALK_MFA_JA_*`、`VVTALK_MFA_EN_*` 指定字典和模型。自动对齐在独立工作目录运行，不修改原安装。

## 从源码运行与构建

需要 Python 3.12；建议安装 Xcode Command Line Tools，便于本地编译依赖和使用签名工具。在仓库目录执行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python app.py --browser
```

运行测试、自检和打包：

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python app.py --self-test
./build.sh --web
```

`build.sh --web` 生成 `dist/VvTalkStudio.app`（onedir 结构，便于签名和快速启动）。应用图标由 `app.ico` 转换的 `app.icns` 提供；如需重新生成，可用 Pillow 和系统 `iconutil` 从 `app.ico` 生成 iconset 后转换。

生成 macOS 便携发行包：

```bash
.venv/bin/python package_release.py --exe dist/VvTalkStudio.app
```

脚本使用 `ditto` 打包 `.app`，生成 `dist/VvTalkStudio-1.1.2-macOS-<架构>.zip`、源码 ZIP 和 SHA-256 清单。

## 签名与公证

本地测试可用 ad-hoc 签名：

```bash
./sign-release-macos.sh dist/VvTalkStudio.app
```

公开发行应使用 Developer ID Application 证书：

```bash
./sign-release-macos.sh dist/VvTalkStudio.app "Developer ID Application: Your Name (TEAMID)"
```

如需公证，先保存 `notarytool` 凭据配置，再运行：

```bash
NOTARY_PROFILE=vvtalk-notary ./sign-release-macos.sh dist/VvTalkStudio.app "Developer ID Application: Your Name (TEAMID)"
```

脚本会 `codesign --verify --deep --strict`，并在提供 `NOTARY_PROFILE` 时提交公证、装订票据。没有正式证书或未执行公证时，不要把发行包描述为已签名或已公证。

## 验证边界

本次 macOS 适配验证了源码运行、单元测试、导出自检、PyInstaller 打包以及本机 ACE / Synthesizer V 路径探测。ACE、Synthesizer V 与 VOCALOID 的实际宿主导入仍取决于宿主版本、声库授权和用户操作，不能由打包成功推导。
