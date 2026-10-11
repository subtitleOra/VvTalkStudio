"""ACEP2 export preserving a real ACE Studio header and singer configuration.

Container layout: LibreSVIP plugins/acep/acep_io.py. Absolute pitch anchors:
SVIXAGENT skills/acep/scripts/acep.cjs; anchors use local ticks and MIDI semitones.
"""

import copy
import io
import math
import os
import struct
import tempfile
import uuid
from bisect import bisect_right
from pathlib import Path

import cbor2
import zstandard

from pronunciation import (ACE_LANGUAGE_CODES, ace_syllable_for_pinyin, ace_syllable_for_reading,
                           ace_english_syllable, ace_voice_for_language)
from languages import normalize_language, normalize_pronunciation_override, english_syllables, text_units


_MAX_PAYLOAD = 256 * 1024 * 1024
_PITCH_SAMPLE_TICKS = 15 / 16
_LANGUAGE_NAMES = {"zh": "中文", "ja": "日语", "en": "英语"}


def _container(path):
    data = Path(path).read_bytes()
    if len(data) < 51 or data[:5] != b"ACEP2" or data[5] != 1:
        raise ValueError("需要 ACE Studio 保存的 ACEP2 原生工程模板。")
    offset, compressed_size, raw_size = struct.unpack_from("<QQQ", data, 8)
    metadata_size = struct.unpack_from("<H", data, 32)[0]
    if offset < 51 + metadata_size or offset + compressed_size != len(data):
        raise ValueError("ACEP2 头部长度或压缩长度不一致。")
    if not 0 < raw_size <= _MAX_PAYLOAD:
        raise ValueError("ACEP2 原始内容长度无效或过大。")
    if data[34 + metadata_size] != 1:
        raise ValueError("ACEP2 metadata 标记不受支持。")
    return data, offset, compressed_size, raw_size


def read_acep(path) -> dict:
    """Read ACEP2, including zstd frames without an embedded content size."""
    data, offset, compressed_size, raw_size = _container(path)
    raw = zstandard.ZstdDecompressor().decompress(
        data[offset:offset + compressed_size], max_output_size=raw_size,
        allow_extra_data=False,
    )
    if len(raw) != raw_size:
        raise ValueError("ACEP2 解压长度与头部声明不一致。")
    stream = io.BytesIO(raw)
    document = cbor2.CBORDecoder(stream).decode()
    if stream.tell() != len(raw) or not isinstance(document, dict):
        raise ValueError("ACEP2 内容必须是一棵完整 CBOR map。")
    return document


def write_acep(document, template_path, dest_path) -> Path:
    """Write a derivative; preserve the template header except size fields."""
    template, destination = Path(template_path), Path(dest_path)
    if template.resolve() == destination.resolve():
        raise ValueError("原生导出必须写入副本，不能覆盖模板。")
    source, offset, _, _ = _container(template)
    if not isinstance(document, dict):
        raise ValueError("ACE 工程内容必须是 dict。")
    raw = cbor2.dumps(document)
    if not 0 < len(raw) <= _MAX_PAYLOAD:
        raise ValueError("原生工程内容过大。")
    compressed = zstandard.ZstdCompressor(level=3, write_content_size=False).compress(raw)
    header = bytearray(source[:offset])
    struct.pack_into("<QQ", header, 16, len(compressed), len(raw))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".acep", delete=False) as file:
            temporary = Path(file.name)
            file.write(header)
            file.write(compressed)
        if read_acep(temporary) != document:
            raise ValueError("原生工程回读与写入内容不一致。")
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def _finite(value, label, lower, upper):
    value = float(value)
    if not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f"{label}超出有效范围。")
    return value


def _curve_lanes(curve, tick_rate, duration_ticks):
    by_tick, previous_time = {}, -1.0
    for point in curve:
        time = _finite(point["time"], "曲线时间", 0, 600)
        if time < previous_time:
            raise ValueError("曲线时间必须有序。")
        previous_time = time
        tick = round(time * tick_rate)
        value = point.get("pitch")
        pitch = None if value is None else _finite(value, "曲线音高", 0, 127)
        # A silence marker wins tick collisions so quantization never joins pauses.
        if tick not in by_tick or by_tick[tick] is not None or pitch is None:
            by_tick[tick] = pitch

    anchors, segment = [], []

    def finish():
        if segment:
            anchors.append({"type": "anchor", "points": segment.copy(),
                            "pointsVUV": [0] * (len(segment) // 2)})
            segment.clear()

    ticks = sorted(by_tick)
    for tick in ticks:
        if by_tick[tick] is None:
            finish()
        else:
            segment.extend([tick, by_tick[tick]])
    finish()
    if not anchors:
        raise ValueError("没有可写入 ACE 的有声音高点。")

    # Native pitch/vuv data uses the 15/16-tick analysis grid; anchors have no offset.
    values = []
    for index in range(math.ceil(duration_ticks / _PITCH_SAMPLE_TICKS) + 1):
        tick = index * _PITCH_SAMPLE_TICKS
        point_index = bisect_right(ticks, tick) - 1
        voiced = (point_index >= 0 and tick <= ticks[-1]
                  and by_tick[ticks[point_index]] is not None)
        values.append(1.0 if voiced else 0.0)
    return anchors, [{"type": "data", "offset": 0, "values": values}]


def _vocal_template(document):
    target = next(((track, pattern) for track in document.get("tracks", [])
                   if track.get("type") == "sing" for pattern in track.get("patterns", [])
                   if pattern.get("timeUnit") == "tick" and pattern.get("notes")), None)
    if target is None:
        raise ValueError("模板需要一个含音符的 tick 人声片段。")
    return target


def _english_note_parts(source, tick_rate):
    override = normalize_pronunciation_override(source.get("pronunciation_override"), "en")
    # Effective phonemes contain stress overrides; the saved user string is the original input.
    phones = source.get("phonemes") or (override.split() if override else None)
    if not phones:
        units = text_units(str(source["lyric"]), "en")
        phones = units[0].get("phonemes") if len(units) == 1 else None
    if not phones:
        raise ValueError(f"英语单词“{source['lyric']}”没有可用读音；ACE 导出前请填写带重音的 ARPAbet 读音覆盖。")
    if not isinstance(phones, (list, tuple)) or not all(isinstance(phone, str) for phone in phones):
        raise ValueError("英语 phonemes 必须是带重音的 ARPAbet 音素列表。")
    # Validate the whole pronunciation before splitting it into ACE's single-syllable notes.
    phones = normalize_pronunciation_override(" ".join(phones), "en").split()
    stresses = source.get("stress_override")
    if stresses is not None:
        vowels = [i for i, phone in enumerate(phones) if phone[-1:] in "012"]
        if (not isinstance(stresses, list) or len(stresses) != len(vowels) or
                any(isinstance(s, bool) or not isinstance(s, int) or s not in (0, 1, 2) for s in stresses)):
            raise ValueError("英语 stress_override 需要逐音节提供 0/1/2。")
        for index, stress in zip(vowels, stresses):
            phones[index] = phones[index][:-1] + str(stress)
    syllables = english_syllables(phones)
    start = round(_finite(source["start"], "音符起点", 0, 600) * tick_rate)
    end = round(_finite(source["end"], "音符终点", 0, 600) * tick_rate)
    if end - start < len(syllables):
        raise ValueError(f"英语单词“{source['lyric']}”时长不足以容纳各个音节；请延长该词。")
    weights = [float(syllable["weight"]) for syllable in syllables]
    total, cumulative, previous, parts = sum(weights), 0.0, start, []
    for index, syllable in enumerate(syllables):
        cumulative += weights[index]
        remaining = len(syllables) - index - 1
        boundary = end if not remaining else min(end - remaining, max(previous + 1,
                         round(start + (end - start) * cumulative / total)))
        parts.append({**source, "start": previous / tick_rate, "end": boundary / tick_rate,
                      # '-' is a melisma in ACE, so each new syllable keeps a regular lyric.
                      "lyric": source["lyric"],
                      "ace_syllable": ace_english_syllable(syllable["phonemes"]),
                      "ace_source_word": source["lyric"], "ace_syllable_index": index,
                      "ace_syllable_count": len(syllables)})
        previous = boundary
    return parts


def _build_pattern(result, pattern_template, tick_rate, name=None, note_limit=1000,
                   declared_duration=None, language=None):
    language = normalize_language(result.get("language", language))
    name = name or _LANGUAGE_NAMES[language] + "语调"
    pattern = copy.deepcopy(pattern_template)
    note_template = pattern["notes"][0]
    source_notes = result.get("notes", [])
    if not source_notes or len(source_notes) > note_limit:
        raise ValueError(f"每段需要 1 至 {note_limit} 个音符。")
    expanded = []
    for source_note in source_notes:
        if normalize_language(source_note.get("language", language)) != language:
            raise ValueError("ACE 每个导出工程需要一种语言；请将混合语言段落分开导出。")
        expanded.extend(_english_note_parts(source_note, tick_rate) if language == "en" else [source_note])
    if len(expanded) > 1000:
        raise ValueError("拆分音节后的 ACE 片段超过 1000 个音符；请将文稿分为较短句子。")
    notes, previous_end, previous_off = [], 0.0, 0
    for source_note in expanded:
        start = _finite(source_note["start"], "音符起点", 0, 600)
        end = _finite(source_note["end"], "音符终点", 0, 600)
        key = _finite(source_note["key"], "音符音高", 0, 127)
        if end <= start or start < previous_end - 1e-8 or not key.is_integer():
            raise ValueError("音符必须无重叠且音高为整数 MIDI 值。")
        on, off = round(start * tick_rate), max(round(start * tick_rate) + 1, round(end * tick_rate))
        if on < previous_off:
            raise ValueError("量化后的音符发生重叠；请调整逐字时间。")
        lyric = str(source_note["lyric"])
        if language == "ja":
            lyric = source_note.get("reading") or lyric
            override = normalize_pronunciation_override(source_note.get("pronunciation_override"), language)
            if override and override != "ー":
                lyric = override
            if lyric == "ー":
                raise ValueError("日语长音需要先根据前一拍确定母音读音。")
        if not lyric:
            raise ValueError("音符歌词不能为空。")
        note = copy.deepcopy(note_template)
        for field in ("vibrato", "phonemeTimings", "pronunciation", "consonantLen"):
            note.pop(field, None)
        note.update(uuid="{" + str(uuid.uuid4()) + "}", pos=on, dur=off - on,
                    pitch=int(key), lyric=lyric, language=ACE_LANGUAGE_CODES[language], extraInfo={},
                    headConsonants=[], tailConsonants=[], syllable="",
                    freezedDefaultSyllable="", brLen=0.0)
        if language == "zh" and source_note.get("pinyin_override") is not None:
            note["syllable"] = ace_syllable_for_pinyin(source_note["pinyin_override"])
        elif language == "ja":
            note["syllable"] = ace_syllable_for_reading(lyric, language)
        elif language == "en":
            note["syllable"] = source_note["ace_syllable"]
            note["extraInfo"] = {"vvtalkStudio": {
                "sourceWord": source_note["ace_source_word"],
                "syllableIndex": source_note["ace_syllable_index"],
                "syllableCount": source_note["ace_syllable_count"]}}
        notes.append(note)
        previous_end, previous_off = end, off

    curve = result.get("curve", [])
    if not curve or len(curve) > 200000:
        raise ValueError("需要有效的连续音高曲线。")
    curve_end = max(_finite(point["time"], "曲线时间", 0, 600) for point in curve)
    duration = max(previous_end, curve_end)
    if declared_duration is not None:
        if declared_duration < duration - 1e-6:
            raise ValueError("段落时长不能短于音符或音高曲线。")
        duration = max(duration, declared_duration)
    duration_ticks = max(previous_off, math.ceil(duration * tick_rate))
    anchors, vuv = _curve_lanes(curve, tick_rate, duration_ticks)
    parameters = {key: [] for key in pattern.get("parameters", {})}
    parameters.update(pitchDelta=anchors, vuv=vuv)
    pattern.update(uuid="{" + str(uuid.uuid4()) + "}", name=name, timeUnit="tick",
                   pos=0.0, dur=float(duration_ticks), clipPos=0.0, clipDur=float(duration_ticks),
                   enabled=True, notes=notes, parameters=parameters, vocalControls={}, extraInfo={})
    return pattern


def configure_ace_voice(track, language):
    """Return a derivative track with a verified stock singer and owned seed recipe."""
    language = normalize_language(language)
    track = copy.deepcopy(track)
    voice = ace_voice_for_language(language)
    carriers = track.get("singers", [])
    if not carriers or not carriers[0].get("singer", {}).get("composition"):
        raise ValueError("ACE 模板缺少可替换的原生声库配置。")
    carrier = copy.deepcopy(carriers[0])
    singer = carrier["singer"]
    component = copy.deepcopy(singer["composition"][0])
    component.update(code=voice["seed_code"], timbre=1.0, style=1.0, lock=True)
    # A stock voice ID names the singer; a seed code names its recipe component.
    singer.update(id=voice["id"], name="", head=-1, router=voice["model_id"],
                  state="Unmixed", group="", composition=[component])
    track["singers"] = [carrier]
    track["extraInfo"] = {**track.get("extraInfo", {}), "vvtalkStudio": {
        "language": language, "singerRef": voice["ref"], "singerName": voice["name"],
        "seedRef": voice["seed_ref"], "modelId": voice["model_id"], "modelName": voice["model_name"]}}
    return track


def _save_patterns(document, track_template, patterns, bpm, template_path, dest_path, language="zh"):
    language = normalize_language(language)
    track = configure_ace_voice(track_template, language)
    track.update(uuid="{" + str(uuid.uuid4()) + "}", name=_LANGUAGE_NAMES[language] + "语调", mute=False, solo=False,
                 record=False, listen=False, language=ACE_LANGUAGE_CODES[language], patterns=patterns)
    duration_ticks = math.ceil(max(pattern["pos"] + pattern["dur"] for pattern in patterns))
    document.update(tracks=[track], duration=duration_ticks,
                    tempos=[{"position": 0.0, "bpm": bpm, "bend": 0.0}],
                    timeSignatures=[{"barPos": 0, "numerator": 4, "denominator": 4}],
                    loop={"valid": False, "active": False, "start": 0, "end": duration_ticks},
                    videoTracks=[])
    if "chordTrack" in document:
        document["chordTrack"]["patterns"] = []
    return write_acep(document, template_path, dest_path)


def build_acep(result, template_path, dest_path) -> Path:
    """Build a vocal clip with language-aware notes and absolute pitch anchors."""
    language = normalize_language(result.get("language"))
    document = read_acep(template_path)
    bpm = _finite(result["bpm"], "BPM", 20, 400)
    track, pattern_template = _vocal_template(document)
    pattern = _build_pattern(result, pattern_template, bpm * 480 / 60)
    return _save_patterns(document, track, [pattern], bpm, template_path, dest_path, language)


def build_long_acep(document, template_path, dest_path) -> Path:
    """Place local section results on one vocal track without global clip limits."""
    sections = document.get("sections", [])
    if not isinstance(sections, list) or not sections:
        raise ValueError("长文工程需要有效的段落列表。")
    language = normalize_language(document.get("language", document.get("settings", {}).get("language")))
    unit_count = sum(len(section["result"].get("notes", [])) for section in sections)
    if not 1 <= unit_count <= 10000:
        raise ValueError("长文工程需要 1 至 10000 个发音单位。")
    bpm = _finite(document.get("bpm", document.get("settings", {}).get("bpm",
                  sections[0]["result"].get("bpm"))), "BPM", 20, 400)
    tick_rate = bpm * 480 / 60
    project = read_acep(template_path)
    track, pattern_template = _vocal_template(project)
    patterns, previous_end = [], 0.0
    for index, section in enumerate(sections):
        if normalize_language(section["result"].get("language", language)) != language:
            raise ValueError("ACE 长文各段落的语言必须与全文一致。")
        offset = _finite(section["offset"], "段落起点", 0, 3600)
        duration = _finite(section["duration"], "段落时长", 0, 600)
        if duration <= 0 or offset < previous_end - 1e-6 or offset + duration > 3600:
            raise ValueError("段落必须有序、无重叠，全文时长不能超过 1 小时。")
        name = f"{index + 1:03d} " + str(section.get("text", ""))[:12]
        pattern = _build_pattern(section["result"], pattern_template, tick_rate,
                                 name=name, note_limit=120, declared_duration=duration, language=language)
        pattern["pos"] = float(round(offset * tick_rate))
        patterns.append(pattern)
        previous_end = offset + duration
    return _save_patterns(project, track, patterns, bpm, template_path, dest_path, language)
