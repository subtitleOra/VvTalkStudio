# 第三方软件与分发声明

本记录针对 2026-10-11 在本项目 `.venv` 中实际安装的 CPython 3.12.10、29 个 Python 分发包及 pywebview 所带的 Microsoft WebView2 SDK 辅助库。版本、原始许可证文件、来源 URL、文件大小与 SHA-256 保存在 [licenses/inventory.json](licenses/inventory.json)。许可证正文按原文件复制，包含安装包中的子组件许可；下面的简写便于查阅，不替代这些正文。

VvTalk Studio 的独立实现及复用的用户自编 ACEProsody 代码按 GPL-3.0-or-later 交付，项目根目录的 `LICENSE` 保存完整 GPLv3 正文，`LICENSE-NOTICE.md` 保存 GPLv3-or-later 授权通知。本交付随附可编辑源码、构建文件和已知 GPL 依赖的对应源码。再分发时应保留上述材料、版权声明与第三方许可证；改变本项目或重新打包时，应同步提供实际版本的对应源码和构建信息。PyInstaller 的打包例外不改变 Praat-Parselmouth 或本项目代码的许可条件，不能仅凭“能打包成 EXE”认定其可纳入任意闭源商业产品。

## VvTalk 参考项目与未分发资源

调教思路参考 [GalaxieT/VvTalk](https://github.com/GalaxieT/VvTalk)，包括中文读音、逐字时序与连续语调的组织方式。上游 [LICENSE](https://raw.githubusercontent.com/GalaxieT/VvTalk/master/LICENSE) 明确规定 CC BY-NC-SA 4.0，并限制其代码及派生代码的商业使用；本交付保存了一份 [参考许可证](licenses/references/VvTalk-upstream-LICENSE.txt) 用于说明来源。

当前工具没有复制或修改 VvTalk 源码，没有把其 CC BY-NC-SA 代码改标为 GPL。它独立实现工作台、调教与适配器，复用用户已有 ACEProsody 的自编工程编解码和语调代码。自动逐字对齐是对本机原 VvTalk 资源的外部调用：发行包不含 VvTalk 的 MiniConda 环境、MFA 声学模型、发音字典或任何商业声库。它们的许可与使用条件应从用户已有安装来源核对，不能从本程序的 GPL 授权推导。SV2、ACE Studio、VOCALOID、声库、Microsoft WebView2 浏览器运行时和系统 .NET 也由用户自行安装并按各自条件使用。

## 公开源码与中性格式模板

公开版本的 ACEP 格式模板来自本项目作者在 ACE Studio 中自行创建的九字样例，不是商业软件预置内容模板。它仅保留项目数据结构和普通音符，不附带声库、音频或模型。公开派生副本清空本机 library 引用、替换历史 UUID/名称、移除历史空轨道、原生效果器实例及其状态、历史曲线与读音缓存。声音的 stock ID、composition seed code 和模型 ID 仍按已记录的正确命名空间保留，不能因清理误删这些导出必需的参数；它们不构成声库授权。完整来源、ACEP2 中性头格式依据、确切上游 commit 和静态验证记录见 [templates/PROVENANCE.md](../templates/PROVENANCE.md) 与 [provenance.json](../templates/provenance.json)。容器按已公开格式独立实现，未复制 LibreSVIP 实现源码；本轮没有对新中性模板进行 ACE 宿主加载验收。

原版 VvTalk 的 CC BY-NC-SA 代码、安装环境、MFA 字典/模型、原版缓存、原始 VSQX、录音和宿主截图均不进入公开源码和公开发行包。对照研究留在作者本机；公开的测试辅助解析器为独立实现。原 VvTalk 的许可证参考文档不表示该项目代码已获得 GPL 授权。复用的 ACEProsody 部分是本项目作者自行编写的代码，本次随本项目按 GPLv3-or-later 提供。

`core/ace_language_cache.json` 是少量读音到音素的映射、音素清单及 stock 声音/种子/模型编号的离线兼容记录，没有商业模型权重、歌声样本、账号密码或授权令牌。其宿主来源在文件中注明；这些参数用于生成用户工程，仍需用户安装并拥有相应 ACE 功能和声音。它与具有单独数据许可证、直接随 EXE 分发的 UniDic Lite / CMUdict 词典，以及只在用户本机外部调用的 MFA 声学模型分别处理。

## 实际依赖与许可证

| 名称与版本 | 实际许可或安装信息 | 用途与来源 |
| --- | --- | --- |
| CPython 3.12.10 | PSF 及其历史/附带组件许可；正文 [CPython LICENSE](licenses/CPython-3.12.10-LICENSE.txt) | 冻结程序内的 Python 运行时；[Python 源码](https://github.com/python/cpython/tree/v3.12.10) |
| numpy 2.5.3 | 安装元数据：BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0；保留 wheel 的完整组件许可 | 数值与曲线处理；[NumPy](https://github.com/numpy/numpy) |
| praat-parselmouth 0.4.7 | 安装许可 GPLv3，分类器与上游声明 GPLv3-or-later；含直接编译的 Praat 代码 | 基频与音频分析；[Parselmouth](https://github.com/YannickJadoul/Parselmouth/tree/v0.4.7) |
| praatio 6.2.2 | MIT，Tim Mahrt 版权声明保留 | TextGrid 解析；[praatIO](https://github.com/timmahrt/praatIO) |
| pypinyin 0.55.0 | MIT | 中文拼音；[python-pinyin](https://github.com/mozillazg/python-pinyin) |
| fugashi 1.5.2 | MIT；随 wheel 的 MeCab 二进制保留 BSD-3-Clause 正文 | 日语形态分析；[fugashi](https://github.com/polm/fugashi) |
| unidic-lite 1.0.8 | 包装代码 MIT/WTFPL 可选 MIT；UniDic 2.1.2 数据为 BSD-3-Clause | 日语读音与词典重音；[UniDic Lite](https://github.com/polm/unidic-lite) |
| cmudict 1.1.3 | Python 包装代码 GPL-3.0-or-later；所附 CMU 发音数据保留单独 BSD 许可 | 英语 ARPAbet 与词重音；[cmudict](https://github.com/prosegrinder/python-cmudict) |
| importlib-metadata 9.0.1、importlib-resources 7.1.0 | Apache-2.0，分别保留正文 | CMUdict 资源读取依赖；[importlib](https://github.com/python/importlib_resources) |
| zipp 4.1.1 | MIT | importlib 依赖；[zipp](https://github.com/jaraco/zipp) |
| cbor2 6.1.5 | MIT | ACEP 数据；[cbor2](https://github.com/agronholm/cbor2) |
| zstandard 0.25.0 | BSD-3-Clause | ACEP 压缩；[python-zstandard](https://github.com/indygreg/python-zstandard) |
| pywebview 6.2.1 | BSD-3-Clause | 桌面窗口；[pywebview](https://github.com/r0x0r/pywebview) |
| bottle 0.13.4 | MIT | pywebview 依赖；[Bottle](https://github.com/bottlepy/bottle) |
| proxy_tools 0.1.0 | 安装元数据写 MIT；上游 LICENSE.txt 实际是两条 BSD 再分发条件，详见下文 | pywebview 依赖；[proxy_tools](https://github.com/jtushman/proxy_tools) |
| pythonnet 3.2.1 | MIT | Windows .NET 桥接；[pythonnet](https://github.com/pythonnet/pythonnet) |
| clr_loader 0.3.1 | 元数据未填写许可，但实际 LICENSE 为 MIT，Benedikt Reinartz 版权声明保留 | .NET 加载；[clr-loader](https://github.com/pythonnet/clr-loader) |
| cffi 2.1.1 | MIT-0，按本机安装元数据与 LICENSE 保留 | 原生接口依赖；[cffi](https://github.com/python-cffi/cffi) |
| pycparser 3.11 | BSD-3-Clause | cffi 依赖；[pycparser](https://github.com/eliben/pycparser) |
| typing_extensions 4.16.0 | PSF-2.0 | 类型支持；[typing_extensions](https://github.com/python/typing_extensions) |
| Pillow 12.3.0 | MIT-CMU，保留完整 wheel 许可证中的附带库许可 | 图像/打包依赖；[Pillow](https://github.com/python-pillow/Pillow) |
| packaging 26.3 | Apache-2.0 OR BSD-2-Clause，两份正文均保留 | 版本与构建依赖；[packaging](https://github.com/pypa/packaging) |
| PyInstaller 6.22.3 | GPLv2-or-later，附非自由软件打包/bootloader 特殊例外 | EXE 构建；[PyInstaller 许可](https://pyinstaller.org/en/stable/license.html) |
| pyinstaller-hooks-contrib 2026.8 | LICENSE 区分标准分析 hooks 的 GPLv2+ 与 runtime hooks 的 Apache-2.0 | 打包 hooks；[hooks-contrib](https://github.com/pyinstaller/pyinstaller-hooks-contrib) |
| altgraph 0.17.5 | MIT | PyInstaller 构建依赖；[altgraph](https://github.com/ronaldoussoren/altgraph) |
| pefile 2024.8.26 | MIT | PyInstaller Windows 构建依赖；[pefile](https://github.com/erocarrera/pefile) |
| pywin32-ctypes 0.2.3 | BSD-3-Clause | PyInstaller Windows 构建依赖；[pywin32-ctypes](https://github.com/enthought/pywin32-ctypes) |
| pip 25.0.1 | MIT | 安装工具；[pip](https://github.com/pypa/pip) |
| setuptools 84.0.0 | MIT；另保留已安装 vendored 子组件的 LICENSE/NOTICE | 构建工具；[setuptools](https://github.com/pypa/setuptools) |
| Microsoft.Web.WebView2 SDK 1.0.3856.49 | NuGet 包 LICENSE 为三条 BSD 式再分发条件；LICENSE 与 NOTICE 均保留 | pywebview 的 SDK DLL，版本取自本机 Core.dll 的 FileVersion；[同版本 NuGet 包](https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.3856.49) |

上述 29 个 Python 分发包包含运行和构建依赖，不表示 pip、setuptools 或全部构建模块一定进入冻结 EXE。收集其许可是为了让项目源码与构建环境也能随包检查。NumPy 和 Pillow 的 wheel 自带多种底层库许可，所以没有只复制一个简短 BSD/MIT 标签。所有已发现的安装许可证、NOTICE 和源码包许可证文件均保留原文。1.1.0 在 EXE 中附带 UniDic Lite 和 CMUdict 词典，离线分析日英读音；这些发音词典与未分发的 MFA 声学模型不同。

CMUdict 的 GPL Python 包装代码对应官方 [1.1.3 源码包](licenses/sources/cmudict-1.1.3.tar.gz) 已附在发行包中。版本、PyPI 原始来源与 SHA-256 记录在 `inventory.json` 的 `language_sources` 中；fugashi、MeCab、UniDic 和 CMU 发音数据的原始许可文件分别保存在对应版本目录。

`proxy_tools 0.1.0` 的已安装 wheel 与官方 0.1.0 源码包都没有附许可证正文。安装 metadata 的 MIT 标签与仓库 [LICENSE.txt](https://raw.githubusercontent.com/jtushman/proxy_tools/master/LICENSE.txt) 不一致；因此这里保留两个事实，并附仓库原文 [upstream-LICENSE.txt](licenses/proxy-tools-0.1.0/upstream-LICENSE.txt)，包括 Armin Ronacher 和 Jonathan Tushman 的版权声明。该副本按抓取日和 SHA-256 标识，不假称它原本就在 0.1.0 源码包内，也没有改写为另一许可证。

Microsoft WebView2 的 SDK 辅助 DLL 位于 pywebview 安装包中，本项目为这些文件取得与 Core.dll 版本一致的官方 NuGet 许可证及 NOTICE，保存在 [Microsoft.Web.WebView2-1.0.3856.49](licenses/Microsoft.Web.WebView2-1.0.3856.49/)。这些 SDK 文件与用户系统上单独安装的 WebView2 浏览器运行时不同；发行包不附运行时安装程序。

## Praat 对应源码与再构建

Praat-Parselmouth 将 Praat C/C++ 代码直接编译到 Python 模块中，不只是启动外部 Praat 程序。其上游说明采用 GPLv3-or-later，Praat 使用 GPLv2-or-later，相关 pybind11、fmt、Vorbis 等组件的原始许可也在源码包中。这里随附官方 PyPI 0.4.7 源码包 [praat_parselmouth-0.4.7.tar.gz](licenses/sources/praat_parselmouth-0.4.7.tar.gz)，包含 3090 个 Praat 源文件，未用空子模块目录代替源码；源码包的 LICENSE、pybind11、fmt、Vorbis 与 Praat GPL 正文还单独提取保存在 `licenses/praat-parselmouth-0.4.7/source-licenses`。

该包为 22,526,491 字节，SHA-256 为 `6dd81d246ce1eef5fd93d8cbdaf1bef61ca40ef1d2fc12aa23996a28071181e6`；来源为 [PyPI 0.4.7 发布文件](https://pypi.org/project/praat-parselmouth/0.4.7/)。重新构建该依赖可解压包并使用其中的 CMake、pyproject.toml 和上游构建说明，在相应的 Python/C++ 编译环境中构建 wheel。本项目冻结包依赖来自固定版本 `requirements.txt`，重新打包步骤见 [README](../README.md)。如果未来更新该依赖或改动它的源码，应一并更新此处的对应源码、版本与哈希。 官方源码包保持原貌，包含上游文档/测试样例；其中音频等素材按上游 README 的单独来源及许可说明处理，例如 The North Wind and the Sun 样例使用 CC BY-SA 3.0。这些上游附带素材不改标为本项目 GPL，也不是用户的参考录音。

为保留安装包原貌，另附 [proxy_tools-0.1.0.tar.gz](licenses/sources/proxy_tools-0.1.0.tar.gz)，但它不是解决上文许可正文缺失的替代品。`inventory.json` 对每个源码包均保存官方来源 URL、下载大小与 SHA-256。

本项目不捆绑商业引擎、声库、MFA 模型或用户录音素材。文稿和导出的歌声工程并不因保存成某种格式而自动获得素材授权。本声明只说明本次软件交付中的代码和依赖，不授予商业宿主、声库或外部模型的许可。
