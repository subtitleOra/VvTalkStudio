# VvTalk Studio 原生 macOS 版

原生工作台使用 SwiftUI、AppKit 和 AVFoundation，要求 macOS 14 或更新版本。窗口左侧按句导航，中间编辑文稿并查看音高，右侧检查器调整参数和发音单元。分析引擎随应用打包，通过进程管道调用，不需要浏览器、本机监听端口或预装 Python。

## 在 Xcode 运行

在仓库根目录准备一次构建环境：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
```

用 Xcode 15 或更新版本打开 `macOS/VvTalkStudio.xcodeproj`，选择 **VvTalkStudio → My Mac**，按 **⌘R**。首次构建会用 PyInstaller 打包分析引擎；后续只改 Swift 界面时会复用引擎。也可设置 `VVTALK_ENGINE_PYTHON` 指向已安装依赖的 Python。Python 必须与目标 Mac 的架构相同。

在终端运行 `./build.sh` 会执行回归测试、自检和 Release 构建，生成 **`dist/VvTalkStudioNative.app`**。默认产物使用本机架构和临时签名，用于本机运行。旧版 WKWebView 应用可以用 `./build.sh --web` 生成；其下载与打包方式见 [macOS 兼容版说明](macos.md)。

## 使用工作台

1. 选择语言，写入文稿或点击「载入示例」，然后点击「生成语调」（⌘↩）。
2. 在音高图拖动音符右端调整发音时长，上下拖动蓝色曲线调整当前范围的音高，拖动图右侧「幅度」手柄改变起伏。图上的编辑松手即生效，可用 ⌘Z 撤销。选择「全文」调整全文，选择一句话只调整该句。生成文稿的后续音符随时长变化顺延，参考录音的音符在原时间轴上调整。右侧检查器也可输入精确数值。
3. 点击「导入参考」选择 WAV、FLAC、AIFF 或 VSQX4，也可直接用麦克风录制。录音分析需要填写对应原文，可提供 CSV/TextGrid 或使用已配置的本机 MFA。麦克风权限由 macOS 在首次录音时请求。
4. 按 ⌘S 保存 `.vvtalk.json`。原生版与网页工作台可互开该文件；网页里未手动保存的草稿请先另存。点击「导出」选择目标引擎，再选择保存位置。
5. 「ACE 试听」合成侧栏当前选定范围。试听要求 ACE Studio 正在运行并启用 External Agent Access，具体宿主和声库要求见 [引擎说明](engine-support.md)。

在右侧「语调参数 → ACE 试听与导出」中选择洛天依、乐正绫或言和。三款使用 Verse23 模型，默认选择洛天依。选择会随工程保存，并用于 ACE 试听及 ACEP 导出。可以离线导出工程，试听前需在 ACE Studio 解锁所选声库。

若要用个人 QQ 发送试听，先在 NapCat 登录 QQ，并在「网络配置」启用绑定到 `127.0.0.1` 的 OneBot HTTP 服务端，设置 Token。合成后点击音高图下方的「QQ 语音…」，填写该 HTTP 端口和 Token，读取群列表，核对发送账号并选择目标群。点击「发送语音」会把当前试听发送为可播放的 QQ 语音消息。可在侧栏选一句再合成，单个试听文件上限为 16 MB。[NapCat 的 OneBot 配置说明](https://napneko.github.io/config/basic)

原生草稿和分析数据默认在 `~/Library/Application Support/VvTalkStudio`，可用 `VVTALK_DATA_DIR` 覆盖。草稿只保存编辑状态；重新打开已保存的参考曲线时，如需听原录音，请重新选择音频。
