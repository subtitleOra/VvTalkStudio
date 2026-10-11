# ACEP 格式模板来源

`speech_template.acep` 来自本项目作者自行在 ACE Studio 中创建的九字格式样例“今天我们一起回家吧”，不是 ACE 官方内容模板，也没有声库、音频样本或模型权重。公开派生副本保留九枚音符的时长、位置、音高与歌词，以及导出所需的 tick 片段、参数键和首枚音符结构；公开项目中的原创模板数据按项目 GPL-3.0-or-later 提供，不因此授权 ACE Studio 本体或声库。

公开副本已清空本机 `singer_library_id` 引用，替换历史 UUID 和片段/轨道名称，移除空历史轨道、效果器实例及其状态、历史音高曲线与已计算读音缓存。stock singer ID 与 composition seed code 是不同命名空间；模板采用本项目已记录的公开 stock 配置，导出时仍由 `core/ace_language_cache.json` 按语言选择对应 id、seed code 和模型 id。这些编号只是宿主项目参数，不能代替用户的声库授权。

旧文件的不透明加密 metadata 不随公开副本保留。新容器按公开 ACEP2 格式独立序列化，格式依据为 [LibreSVIP acep_io.py，commit 6944c2bae4085cd60bf55add12aba3034f4cf18b](https://github.com/SoulMelody/LibreSVIP/blob/6944c2bae4085cd60bf55add12aba3034f4cf18b/libresvip/plugins/acep/acep_io.py)。只参考字段布局与其中已有的中性头参数，没有复制上游实现源码或加入 LibreSVIP 运行依赖。该源文件 SHA256 为 `6b14b63eb728acd81728fbdd806af5154b11f712c85f4bd14270fa84225dabcb`。中性头长 192 字节：magic 为 ACEP2，flag 为 1，header_size 为 0，content_offset 为 192，encrypted_metadata 为 138 个零字节，metadata_flag 为 1，content_hash 为 16 个零字节，末尾 padding 为 3 个零字节；压缩内容长度和原内容长度按实际 CBOR/Zstandard payload 写入。

使用本项目 `read_acep` / `write_acep` 完成读写读回一致性检查；与原本地模板分别导出同一中文、日文、英文输入以及两段中文长文，生成音符、片段几何、连续音高/VUV 参数、声音配置和速度/拍号完全一致。轨道效果、历史 UUID 与本机 library 引用属于本次明确清理的内容，不计作音高几何。细节及模板 SHA256 见 [provenance.json](provenance.json)。本轮未在 ACE 宿主中加载这个新中性容器，不能把原模板的历史宿主验收当作本模板的加载证明。作者本机的原模板和旧发行包未修改。
