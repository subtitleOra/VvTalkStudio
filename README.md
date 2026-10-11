# VvTalk Studio
使用GPT基于https://github.com/GalaxieT/VvTalk项目为参考开发的语调教辅助工具。
VvTalk Studio 1.1.2 是 Windows 本地语音调教工作台。它支持中文逐字、日语逐拍和英语逐词编辑，将文字语调草稿或参考录音的连续基频转换为 ACE Studio、Synthesizer V Studio 2 Pro 和 VOCALOID 5/6 可使用的工程。每次导出只生成所选引擎的一个文件；工作台编辑信息通过单独的 `.vvtalk.json` 保存。1.1.2 修复了界面外层多余滚动，并保留面板内部滚动与键盘访问。

文字生成使用本地词典与可编辑的节奏、重音和句调规则，不是语音识别，也不保证自然朗读的逐点复现。要还原实际说话的音高，请提供内容已知的参考录音及时间标注。代码独立实现了本工作台，并复用了已有 ACEProsody 模块；运行时不会导入原版 VvTalk 的 Talker、分析器或 VSQX Writer。原版 VvTalk 的 MFA 安装仅作为用户自行提供的外部对齐资源，未随本项目分发。

## 下载与运行

在 [GitHub Releases](https://github.com/subtitleOra/VvTalkStudio/releases) 打开 `v1.1.2`，下载 Windows x64 便携 ZIP，完整解压后运行 `VvTalkStudio.exe` 或 `Start-VvTalk.cmd`。不要只把 EXE 从 ZIP 中拖出运行：同目录的源码、许可证和说明是发行的一部分。源码仓库的自动生成 ZIP 本身不包含预编译 EXE；如 Releases 暂无二进制附件，请按下文从源码运行。

EXE 已包含 Python 和运行依赖。桌面窗口使用 Microsoft Edge WebView2 Runtime；缺少或无法使用该运行时，可以运行 `VvTalkStudio.exe --browser`，通过系统浏览器访问本地工作台。应用只监听 `127.0.0.1`，默认端口为 `8777`。若另一个版本仍占用该端口，请关闭对应版本，或为新版本使用 `--port 8778`；程序不会把不同版本当作可复用的同一服务。

当前发行文件未进行代码签名，Windows 可能显示未知发布者或 SmartScreen 提示。请从本仓库的 Releases 获取附件，并与该版本提供的 SHA-256 清单核对。组织设备若禁止未签名程序，应由管理员核验后允许，或使用源码运行；本项目不要求关闭系统安全功能。正式签名流程见 [代码签名说明](docs/code-signing.md)。

工作数据默认保存在 `%USERPROFILE%\AppData\Local\VvTalkStudio`，包括上传录音、输出、对齐任务和窗口配置。可用 `VVTALK_DATA_DIR` 指定独立的数据目录。关闭桌面窗口会结束其本地服务；浏览器模式可通过随包 `Stop-VvTalk.cmd` 结束。请主动保存工作台文件，重新打开工程后若需要播放原始录音，应重新选择该音频。

## 文字与参考录音

新建工程后先选择中文、日语或英语，再输入文稿。表格可编辑时长、停顿、音高基准及读音；日语可覆盖单拍的低/高，英语可覆盖 ARPAbet 音素和音节重音。中文旧工程缺少语言字段时仍按中文打开。已导入的录音曲线或 VSQX 保持原语言，要更换语言请新建或重新导入。日英读音与重音边界见 [多语言说明](docs/multilingual.md)。

参考录音须为 WAV 或 FLAC，长度为 0.1 至 180 秒，文字必须与录音内容对应。选择录音、填写已知文字，确认基频上下限，再选择自动对齐、CSV/TextGrid 标注或明确的均分草稿。程序保留音符间停顿和清音帧；对齐缺资源或失败会报告原因，不会自动改成均分。

CSV 使用 `start,end,lyric` 列，时间单位为秒，`lyric` 可省略。中文一个区间对应一个字，日语对应一拍，英语对应一个词。TextGrid 使用对应单位的 IntervalTier，整句区间或声学音素区间不能直接充当逐字、逐拍或逐词标注。均分模式只是便于编辑的估算时间，不代表真实对齐。

中文自动对齐复用本机已有 VvTalk MFA 2 环境。默认查找 `%USERPROFILE%\Documents\Vocaloid\VvTalk_1.0.1`，其他安装位置通过 `VVTALK_SOURCE` 指定。该目录须包含 `misc/src/MiniConda/envs/vvTalkEnv/python.exe`、同环境下 `Scripts/mfa-script.py`、`misc/mfa/mfa_model_v20.dict` 和 `misc/mfa/mandarin_mfa.zip`。本程序在独立工作目录调用它们，不修改原安装。EXE 没有捆绑 MFA、声学模型或这些字典，没有该环境仍可使用文字生成与人工时间标注。

英语自动对齐另需配置 `VVTALK_MFA_EN_DICTIONARY`、`VVTALK_MFA_EN_MODEL`，日语对应 `VVTALK_MFA_JA_DICTIONARY`、`VVTALK_MFA_JA_MODEL`。资源须兼容上述 MFA 2 环境；日语字典还必须与逐拍读音匹配。普通日语逐词字典不能直接作为逐拍字典。

## 引擎使用条件

| 目标 | 单次输出 | 宿主条件 |
| --- | --- | --- |
| ACE Studio | `.acep` | 安装并授权与工程语言兼容的声库及模型 |
| Synthesizer V Studio 2 Pro | `.svp` | 2.1.0 或更高版本支持原生 PitchControlCurve；选择兼容语言声库 |
| VOCALOID 5 / 6 | `.vsqx` | 导入后选择已授权的对应语言声库并重新计算发音 |

ACE 导出可离线完成。缓存默认声音为中文“橘”（stock id 8 / seed 6）、日语“黑昴宿”（34 / 30）及英语“Elirah”（56 / 110），模型为 Verse24。这些是已核对的声库目录映射，不等于其他账号已拥有这些声音。遇到不可用声音，先在宿主中确认该声库与模型的安装和授权；模板不携带个人声音库授权。

ACE 试听功能还要求已安装 `C:\Program Files\ACE Studio\acestudio-cli.exe`、ACE Studio 正在运行并开启 External Agent Access。本工作台会检查宿主未保存状态，避免覆盖现有工作。语调工程能否成功导入、能否合成以及声音是否适合朗读，是三个不同的检查步骤。

SVP 直接携带 Studio 2 原生连续曲线。若希望向已有工程添加轨道，可使用可选的“复制 SV2 脚本数据”，再运行随包脚本。界面安装按钮自动查找 `%APPDATA%\Dreamtonics\Synthesizer V Studio 2\scripts`；独立 `plugins/install-synthv.cmd` 可选择实际脚本目录。此操作不增加导出附件，导入轨道可在宿主中撤销。VOCALOID 5/6 的交付是 VSQX 工程，不是旧版 V3 Job Plugin、VST 或 DLL 插件。

已有中文 ACE 与 SV2 脚本的实际宿主导入、保存回读证据；最新版 ACE 声音种子修正、公开模板净化和直接 SVP 输出完成了格式与数值检查，没有新增三语宿主试听。VOCALOID 5 未执行宿主验收，VOCALOID 6 的实际启动被声库授权提示阻断。完整边界见 [公开验收概要](docs/验收记录.md) 与 [1.1.2 发行说明](docs/RELEASE-1.1.2.md)。

## 从源码运行与构建

需要 Windows x64 与 Python 3.12。在仓库目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe app.py --browser
```

运行普通回归测试和导出自检：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe app.py --self-test
```

普通测试在临时目录生成夹具，不依赖私人录音或 `.qa` 目录。真实 MFA 测试默认跳过；要执行它，先配置本机 MFA，再将 `VVTALK_RUN_MFA_TEST=1` 与 `VVTALK_TEST_REFERENCE_WAV` 显式设为自己录制的“今天，我们一起回家吧。”WAV。测试不会改写该录音。

执行 `powershell -ExecutionPolicy Bypass -File .\build.ps1` 会使用锁定依赖、运行测试和自检，再通过 PyInstaller 生成 `dist/VvTalkStudio.exe`。正式发行须随 EXE 提供同版本完整对应源码、构建文件、许可证及必要第三方源码包；不要只发布 EXE。[引擎格式说明](docs/engine-support.md) 记录时间和音高单位，[原版 VSQX 对照说明](docs/vvtalk-comparison.md) 说明数值验证方法。

## 设计与许可

界面设计保存在已授权公开的 [Figma 文件](https://www.figma.com/design/R5pvrQSBdbLndCJaekhMEd/VvTalk-Studio?node-id=8-56)，可编辑节点见 [设计记录](docs/figma-design.md)。

本项目以 GNU GPL v3 或更新版本提供，授权通知位于 [LICENSE-NOTICE.md](LICENSE-NOTICE.md)，完整正文位于 [LICENSE](LICENSE)。第三方依赖、词典数据、模板来源及对应源码交付规则见 [第三方通知](docs/THIRD_PARTY_NOTICES.md) 和 `docs/licenses/`。原版 VvTalk 为 CC BY-NC-SA 4.0，未将其源码或模型并入本项目的 GPL 源树；调用本机外部资源不改变其原有许可。商业歌声引擎、声库、模型和录音素材的使用权由各自许可决定。
