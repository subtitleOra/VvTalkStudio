# VvTalk Studio
使用GPT基于https://github.com/GalaxieT/VvTalk 项目为参考开发的语调教辅助工具。
VvTalk Studio 1.1.2 是本地语音调教工作台，支持 Windows x64 与 macOS 12 或更高版本；当前 macOS 构建附件为 Apple Silicon（arm64），Intel Mac 可按相同源码步骤在本机构建。它支持中文逐字、日语逐拍和英语逐词编辑，将文字语调草稿或参考录音的连续基频转换为 ACE Studio、Synthesizer V Studio 2 Pro 和 VOCALOID 5/6 可使用的工程。每次导出只生成所选引擎的一个文件；工作台编辑信息通过单独的 `.vvtalk.json` 保存。1.1.2 修复了界面外层多余滚动，并保留面板内部滚动与键盘访问。

文字生成使用本地词典与可编辑的节奏、重音和句调规则，不是语音识别，也不保证自然朗读的逐点复现。要还原实际说话的音高，请提供内容已知的参考录音及时间标注。代码独立实现了本工作台，并复用了已有 ACEProsody 模块；运行时不会导入原版 VvTalk 的 Talker、分析器或 VSQX Writer。原版 VvTalk 的 MFA 安装仅作为用户自行提供的外部对齐资源，未随本项目分发。

## macOS 原生工作台

新原生版采用 SwiftUI，支持 macOS 14 或更新版本，提供按句导航、音高曲线、参数检查器和麦克风录制。用 Xcode 打开 `macOS/VvTalkStudio.xcodeproj`，选择 **VvTalkStudio → My Mac** 后运行；或执行 `./build.sh` 生成 `dist/VvTalkStudioNative.app`。首次构建的依赖和使用方式见 [原生 macOS 说明](docs/macos-native.md)。

下文的 macOS 12 兼容版使用 WKWebView；可用 `./build.sh --web` 构建。

## 下载与运行

在 [GitHub Releases](https://github.com/subtitleOra/VvTalkStudio/releases) 打开 `v1.1.2`，下载对应平台的便携 ZIP；若该次发行尚未提供 macOS 附件，可按下文从源码构建。源码仓库的自动生成 ZIP 本身不包含预编译程序；如 Releases 暂无二进制附件，请按下文从源码运行。

**Windows x64**：完整解压后运行 `VvTalkStudio.exe` 或 `Start-VvTalk.cmd`。不要只把 EXE 从 ZIP 中拖出运行：同目录的源码、许可证和说明是发行的一部分。EXE 已包含 Python 和运行依赖；桌面窗口使用 Microsoft Edge WebView2 Runtime，缺少或无法使用该运行时，可以运行 `VvTalkStudio.exe --browser`，通过系统浏览器访问本地工作台。

**macOS**：完整解压后运行 `VvTalkStudio.app` 或 `Start-VvTalk.command`。应用包已包含 Python 和运行依赖，桌面窗口使用系统自带的 WKWebView，不需要额外安装浏览器运行时。首次打开未签名版本时，Finder 可能提示无法验证开发者；请右键应用选择“打开”，或执行 `xattr -dr com.apple.quarantine VvTalkStudio.app` 后再打开。也可以运行 `VvTalkStudio.app/Contents/MacOS/VvTalkStudio --browser` 通过系统浏览器使用。WKWebView 桌面窗口当前不提供麦克风直录；需要现场录音时请用浏览器模式，或上传 WAV 文件。

应用只监听 `127.0.0.1`，默认端口为 `8777`。若另一个版本仍占用该端口，请关闭对应版本，或为新版本使用 `--port 8778`；程序不会把不同版本当作可复用的同一服务。

当前发行文件未使用发布者证书签名（macOS 构建为 ad-hoc 签名），Windows 可能显示未知发布者或 SmartScreen 提示，macOS 可能显示 Gatekeeper 提示。请从本仓库的 Releases 获取附件，并与该版本提供的 SHA-256 清单核对。组织设备若禁止未签名程序，应由管理员核验后允许，或使用源码运行；本项目不要求关闭系统安全功能。正式签名流程见 [代码签名说明](docs/code-signing.md)。

工作数据默认保存在 `%USERPROFILE%\AppData\Local\VvTalkStudio`（Windows）或 `~/Library/Application Support/VvTalkStudio`（macOS），包括上传录音、输出、对齐任务和窗口配置。可用 `VVTALK_DATA_DIR` 指定独立的数据目录。关闭桌面窗口会结束其本地服务；浏览器模式在 Windows 可通过 `Stop-VvTalk.cmd`、在 macOS 可通过 `Stop-VvTalk.command` 结束。请主动保存工作台文件，重新打开工程后若需要播放原始录音，应重新选择该音频。

## QQ 群聊机器人

可从源码单独启动 QQ 群机器人。群友 @ 机器人后可与 AI 对话，也可用 `/语音` 把回复合成为群内语音。配置方式见 [QQ 机器人说明](docs/qq-bot.md)。

## 文字与参考录音

新建工程后先选择中文、日语或英语，再输入文稿。表格可编辑时长、停顿、音高基准及读音；日语可覆盖单拍的低/高，英语可覆盖 ARPAbet 音素和音节重音。中文旧工程缺少语言字段时仍按中文打开。已导入的录音曲线或 VSQX 保持原语言，要更换语言请新建或重新导入。日英读音与重音边界见 [多语言说明](docs/multilingual.md)。

参考录音须为 WAV 或 FLAC，长度为 0.1 至 180 秒，文字必须与录音内容对应。选择录音、填写已知文字，确认基频上下限，再选择自动对齐、CSV/TextGrid 标注或明确的均分草稿。程序保留音符间停顿和清音帧；对齐缺资源或失败会报告原因，不会自动改成均分。

CSV 使用 `start,end,lyric` 列，时间单位为秒，`lyric` 可省略。中文一个区间对应一个字，日语对应一拍，英语对应一个词。TextGrid 使用对应单位的 IntervalTier，整句区间或声学音素区间不能直接充当逐字、逐拍或逐词标注。均分模式只是便于编辑的估算时间，不代表真实对齐。

中文自动对齐复用本机已有 VvTalk MFA 2 环境。默认查找 `%USERPROFILE%\Documents\Vocaloid\VvTalk_1.0.1`（Windows）或 `~/Documents/Vocaloid/VvTalk_1.0.1`（macOS），其他安装位置通过 `VVTALK_SOURCE` 指定。Windows 目录须包含 `misc/src/MiniConda/envs/vvTalkEnv/python.exe`、同环境下 `Scripts/mfa-script.py`、`misc/mfa/mfa_model_v20.dict` 和 `misc/mfa/mandarin_mfa.zip`。macOS 与 Linux 会识别该环境的 `bin/python` 及 `bin/mfa-script.py` 或 `bin/mfa`；也可用 `VVTALK_MFA_PYTHON`、`VVTALK_MFA_SCRIPT` 指向任意已有的 MFA 2 环境，用 `VVTALK_MFA_DICTIONARY`、`VVTALK_MFA_MODEL` 指定普通话字典与声学模型。本程序在独立工作目录调用它们，不修改原安装。发行包没有捆绑 MFA、声学模型或这些字典，没有该环境仍可使用文字生成与人工时间标注。

英语自动对齐另需配置 `VVTALK_MFA_EN_DICTIONARY`、`VVTALK_MFA_EN_MODEL`，日语对应 `VVTALK_MFA_JA_DICTIONARY`、`VVTALK_MFA_JA_MODEL`。资源须兼容上述 MFA 2 环境；日语字典还必须与逐拍读音匹配。普通日语逐词字典不能直接作为逐拍字典。

## 引擎使用条件

| 目标 | 单次输出 | 宿主条件 |
| --- | --- | --- |
| ACE Studio | `.acep` | 安装并授权与工程语言兼容的声库及模型 |
| Synthesizer V Studio 2 Pro | `.svp` | 2.1.0 或更高版本支持原生 PitchControlCurve；选择兼容语言声库 |
| VOCALOID 5 / 6 | `.vsqx` | 导入后选择已授权的对应语言声库并重新计算发音 |

ACE 导出可离线完成。缓存默认声音为中文“橘”（stock id 8 / seed 6）、日语“黑昴宿”（34 / 30）及英语“Elirah”（56 / 110），模型为 Verse24。这些是已核对的声库目录映射，不等于其他账号已拥有这些声音。遇到不可用声音，先在宿主中确认该声库与模型的安装和授权；模板不携带个人声音库授权。

ACE 试听功能还要求已安装 ACE Studio（Windows 默认 `C:\Program Files\ACE Studio\acestudio-cli.exe`，macOS 默认 `/Applications/ACE Studio.app/Contents/Helpers/acestudio-cli`，可用 `VVTALK_ACE_CLI` 覆盖）、ACE Studio 正在运行并开启 External Agent Access。本工作台会检查宿主未保存状态，避免覆盖现有工作。语调工程能否成功导入、能否合成以及声音是否适合朗读，是三个不同的检查步骤。

SVP 直接携带 Studio 2 原生连续曲线。若希望向已有工程添加轨道，可使用可选的“复制 SV2 脚本数据”，再运行随包脚本。界面安装按钮自动查找 Windows 的 `%APPDATA%\Dreamtonics\Synthesizer V Studio 2\scripts` 或 macOS 的 `~/Library/Application Support/Dreamtonics/Synthesizer V Studio 2/scripts`；独立安装脚本（Windows `plugins/install-synthv.cmd`、macOS `plugins/install-synthv.command`）可选择实际脚本目录，也可用 `VVTALK_SV_SCRIPTS_DIR` 指定。此操作不增加导出附件，导入轨道可在宿主中撤销。VOCALOID 5/6 的交付是 VSQX 工程，不是旧版 V3 Job Plugin、VST 或 DLL 插件。

已有中文 ACE 与 SV2 脚本的实际宿主导入、保存回读证据；最新版 ACE 声音种子修正、公开模板净化和直接 SVP 输出完成了格式与数值检查，没有新增三语宿主试听。VOCALOID 5 未执行宿主验收，VOCALOID 6 的实际启动被声库授权提示阻断。完整边界见 [公开验收概要](docs/验收记录.md) 与 [1.1.2 发行说明](docs/RELEASE-1.1.2.md)。

## 从源码运行与构建

需要 Python 3.12。Windows 需要 Windows 10/11 x64；macOS 需要 macOS 12 或更高版本（Apple Silicon 与 Intel），建议安装 Xcode Command Line Tools 以便本地编译依赖和使用签名工具。在仓库目录执行：

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe app.py --browser
```

macOS Terminal：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python app.py --browser   # 改用 app.py 可打开 WKWebView 桌面窗口
```

运行普通回归测试和导出自检：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe app.py --self-test
```

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python app.py --self-test
```

普通测试在临时目录生成夹具，不依赖私人录音或 `.qa` 目录。真实 MFA 测试默认跳过；要执行它，先配置本机 MFA，再将 `VVTALK_RUN_MFA_TEST=1` 与 `VVTALK_TEST_REFERENCE_WAV` 显式设为自己录制的“今天，我们一起回家吧。”WAV。测试不会改写该录音。

构建发行程序：

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

```bash
./build.sh --web  # macOS 12 兼容版
```

`build.ps1` 使用锁定依赖、运行测试和自检，再通过 PyInstaller 生成 `dist/VvTalkStudio.exe`。`build.sh --web` 执行相同流程并生成 `dist/VvTalkStudio.app`。macOS 正式发行建议使用 `./sign-release-macos.sh dist/VvTalkStudio.app "Developer ID Application: ..."` 签名；如需公证，设置 `NOTARY_PROFILE` 后再次运行。macOS 的路径、MFA、签名与公证细节见 [macOS 适配说明](docs/macos.md)。正式发行须随程序提供同版本完整对应源码、构建文件、许可证及必要第三方源码包；不要只发布程序本体。[引擎格式说明](docs/engine-support.md) 记录时间和音高单位，[原版 VSQX 对照说明](docs/vvtalk-comparison.md) 说明数值验证方法。

## 设计与许可

界面设计保存在已授权公开的 [Figma 文件](https://www.figma.com/design/R5pvrQSBdbLndCJaekhMEd/VvTalk-Studio?node-id=8-56)，可编辑节点见 [设计记录](docs/figma-design.md)。

本项目以 GNU GPL v3 或更新版本提供，授权通知位于 [LICENSE-NOTICE.md](LICENSE-NOTICE.md)，完整正文位于 [LICENSE](LICENSE)。第三方依赖、词典数据、模板来源及对应源码交付规则见 [第三方通知](docs/THIRD_PARTY_NOTICES.md) 和 `docs/licenses/`。原版 VvTalk 为 CC BY-NC-SA 4.0，未将其源码或模型并入本项目的 GPL 源树；调用本机外部资源不改变其原有许可。商业歌声引擎、声库、模型和录音素材的使用权由各自许可决定。
