# 宿主与工程格式

内部统一使用秒、整数 MIDI 音符基准与绝对 MIDI 半音连续曲线，`null` 表示没有可靠基频。导出前检查数值、时间顺序、音符重叠、语言和读音覆盖。界面每次只生成所选目标的一个工程文件；工作台 JSON 单独保存，SV2 剪贴板操作也不会附带输出文件。

| 目标 | 文件 | 连续音高编码 |
| --- | --- | --- |
| Synthesizer V Studio 2 Pro 2.1.0+ | SVP | 原生 PitchControlCurve：绝对 MIDI 基准与相对半音曲线点 |
| ACE Studio | ACEP | 原生 pitchDelta 锚点和有声/清音分段 |
| VOCALOID 5 / 6 | VSQX4 | PIT/PBS 整数弯音，相对于当前音符的音高基准 |

## Synthesizer V Studio 2 Pro

SVP 使用真实 SV2 保存文件核对过的 v196 结构，每四分音符为 705600000 blick。`NoteGroup.pitchControls` 包含组内 `pos`、绝对 MIDI 基准 `pitch` 与交错的相对 blick / 相对半音 `points`。旧版音分 `pitchDelta` 保持为空，避免双重叠加。遇到清音帧拆分曲线；孤立测量使用 1 blick 的恒值曲线。直接 SVP 的静态解码保持了连续音高，已完成与未执行的宿主检查分别列于 [公开验收概要](验收记录.md)。

可选剪贴板插件使用官方 JavaScript ES5.1 脚本 API。它先验证对象，再建立一个撤销记录并添加独立轨道；通过宿主 `TimeAxis.getBlickFromSeconds` 处理已有变速工程，原速度事件保持不变。导入后须选择支持当前语言的声库。界面安装按钮探测 `%APPDATA%\Dreamtonics\Synthesizer V Studio 2\scripts`，独立 `plugins/install-synthv.cmd` 则允许选择宿主实际脚本目录，同名脚本先备份。

`Note.setLanguageOverride` 使用 `mandarin`、`japanese`、`english`，SVP 主引用设置相同语言。日语长音先确定母音读音。英文 ARPAbet 覆盖保存在工作台和元数据，SV 的发音仍由自己的词典计算，不把这些符号当作已经兼容的宿主音素。[官方脚本说明](https://resource.dreamtonics.com/scripting/)、[PitchControlCurve](https://resource.dreamtonics.com/scripting/PitchControlCurve.html)、[NoteGroup](https://resource.dreamtonics.com/scripting/NoteGroup.html)、[TimeAxis](https://resource.dreamtonics.com/scripting/TimeAxis.html)、[Note API](https://resource.dreamtonics.com/scripting/Note.html)。

## ACE Studio

ACEP 复用已建立的 ACEProsody 原生编解码实现，短文或长文分别生成原生片段，保留句间时间偏移。模板为本项目自生成的容器起点，公开版本去除了个人库引用、工程身份、效果和加密元数据。代码不把该模板中的信息当作账号授权，声库与模型仍由宿主实际安装决定。结构和导出语义检查通过，未新增净化模板的宿主开存或试听。

ACE 使用 CHN/JPN/ENG 语言标签。随包 `core/ace_language_cache.json` 来源于 ACE Studio 2.1.8 / CLI 0.17.0 的只读词典、音素表、声库和模型查询，含 154 个可解析日语假名拍及已核对的英语音素。缓存允许日英离线导出；未知假名或无有效英文读音会明确报错，不能替代新机器的声库授权和宿主词典版本检查。中文手动拼音需要当前 ACE CLI 的只读词典解析，ACE 必须运行并允许外部访问。

stock singer ID 与声音种子 code 是不同命名空间。默认中文为“橘” id 8 / seed 6，日语为“黑昴宿” 34 / 30，英语为 Elirah 56 / 110，当前缓存中都对应 Verse24；router 13 在本机只读回读中确认为 Verse24。导出分别写入 `singer.id` 和 `singer.composition[].code`。这些配置来自已验证的目录映射，不意味着任意账号已经安装或获权使用对应声音。

ACE 的一个音符只容纳一个连续元音段。英文多音节词按有效音素和重音拆为子音符，总起止 tick 与原词一致，绝对音高曲线和停顿不变；各子音符显示原词并携带明确音素和源词元数据。ACE 中 `-` 表示延长上一音节，因此不用它代替新音节。词内辅音归组和音节时间分配仍是可编辑草稿，未进行人工发音验收。[ACE 官方发音编辑说明](https://docs.acestudio.ai/ai-vocal-synth/creating-ai-vocals/editing-lyrics.md)。

## VOCALOID 5 / 6

交付为 VSQX4 工程，不是 V3 Job Plugin、DLL 或 VST。时间使用 480 PPQ，弯音按 `PIT = (绝对音高 − 当前音符音高) / PBS × 8192` 量化，PBS 根据偏移范围取 2–24 半音。控制器按时间排序，在音符基准变化与清音边界处理相应事件。原始绝对曲线可由独立解码器还原并检查量化容差。

占位声库语言 bank 为日语 0、英语 1、中文 4，发音保持 `lock=0`。导入时选择本机已授权的对应语言声库，再重新计算发音。中文手动拼音去除声调数字后交给宿主字典；日语使用有效假名拍，英语保留原词。工作台保存原始文字与读音覆盖。导出没有复制来源不明的 VOCALOID 发音映射表，也没有绑定使用者尚未安装的声库。

VOCALOID 6 官方支持旧版本序列格式，并区分 VOCALOID 与 VOCALOID:AI 轨道；实际合成与效果兼容性仍需宿主复核。本机 V6 被声库授权提示阻断，V5 未安装，当前已完成的是 XML、PIT/PBS、几何、清音及量化静态检查。[VOCALOID6 参考手册](https://rsc-net.vocaloid.com/assets/pdf_files/bb/VOCALOID_Reference_Manual_ENG.pdf)、[官方兼容说明](https://www.vocaloid.com/en/learn/ln6105/)、[LibreSVIP VSQX 语言枚举](https://github.com/SoulMelody/LibreSVIP/blob/master/libresvip/plugins/vsqx/models/enums.py)。

## 录音与语言一致性

Praat 提取 Hz 基频，再转换为绝对 MIDI 半音；220 Hz、330 Hz 与中间静音的独立信号用于回归。中文自动字界调用用户本机外部 MFA 环境，在独立目录执行；原录音和原 VvTalk 安装不被修改。模型、字典、输入标签或输出区间不满足条件时报告错误，不自动均分。配置与标注规则见 [README](../README.md) 和 [多语言说明](multilingual.md)。

工程、结果与各音符使用同一 `zh`、`ja` 或 `en` 语言，旧文件缺省为中文。日语按拍，英语按词；中文拼音规则不会应用到非中文读音。VSQX 导入的覆盖文本按所选语言校验单位数量。外部日语独立长音根据前拍规范成母音，原歌词保存在 `source_lyric`；词首长音或无法确定母音会要求修正歌词或提供覆盖文本。

清音帧表示 F0 不可靠，不必然意味着静音。SV 与 VOCALOID 的音高控制不能强制消除持续音符内部的声音；实际清音和发音效果取决于声库。数值保持、格式可解析、宿主可加载和实际听感须分别验证，现有结论与限制见 [公开验收概要](验收记录.md)。
