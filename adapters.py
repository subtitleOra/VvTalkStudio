"""Independent project exporters; source projects and live editors are never changed."""

from __future__ import annotations

import bisect
import json
import math
import re
import shutil
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from native_acep import build_acep, build_long_acep
from pronunciation import normalize_pinyin_override
from languages import normalize_language, normalize_pronunciation_override


BLICK_PER_QUARTER = 705_600_000
VSQX_NAMESPACE = "http://www.yamaha.co.jp/vocaloid/schema/vsq4/"
PLUGIN_DIR = Path(__file__).resolve().parent / "plugins"
SV_LANGUAGES = {"zh": "mandarin", "ja": "japanese", "en": "english"}
LANGUAGE_NAMES = {"zh": "中文", "ja": "日语", "en": "英语"}
VOCALOID_BANKS = {"zh": 4, "ja": 0, "en": 1}
ET.register_namespace("", VSQX_NAMESPACE)


def _number(value, name, minimum, maximum):
    if isinstance(value, bool):
        raise ValueError(f"{name}必须是有效数字。")
    try:
        value = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name}必须是有效数字。") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name}超出支持范围。")
    return value


def validate_result(result):
    """Bound all external data before serialization or host-script generation."""
    if not isinstance(result, dict):
        raise ValueError("导出数据必须是分析结果。")
    language = normalize_language(result.get("language"))
    bpm = _number(result.get("bpm"), "速度", 20, 400)
    duration = _number(result.get("duration"), "时长", 0, 3600)
    source_notes, source_curve = result.get("notes"), result.get("curve")
    if not isinstance(source_notes, list) or not 1 <= len(source_notes) <= 10000:
        raise ValueError("导出需要 1 至 10000 个音符。")
    if not isinstance(source_curve, list) or not 1 <= len(source_curve) <= 1500000:
        raise ValueError("导出需要有效的音高曲线，最多 1500000 点。")
    notes, previous_end = [], 0.0
    for source in source_notes:
        if not isinstance(source, dict):
            raise ValueError("音符数据无效。")
        start = _number(source.get("start"), "音符起点", 0, 3600)
        end = _number(source.get("end"), "音符终点", 0, duration)
        key = _number(source.get("key"), "音符音高", 0, 127)
        lyric = source.get("lyric")
        if end <= start or start < previous_end - 1e-8 or not key.is_integer():
            raise ValueError("音符必须按时间排序、无重叠，音高为整数 MIDI 值。")
        if not isinstance(lyric, str) or not lyric or len(lyric) > 128 or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", lyric):
            raise ValueError("音符歌词无效。")
        note_language = normalize_language(source.get("language", language))
        if note_language != language:
            raise ValueError("每份导出工程需要使用同一种语言；请将混合语言段落分开导出。")
        if language != "zh" and source.get("pinyin_override") is not None:
            raise ValueError("日语和英语不能使用中文手动拼音；请使用当前语言的读音覆盖。")
        pronunciation = normalize_pronunciation_override(source.get("pronunciation_override"), language)
        override = normalize_pinyin_override(source.get("pinyin_override")) if language == "zh" else None
        if language == "zh" and pronunciation is not None:
            if override is not None and override != pronunciation:
                raise ValueError("手动拼音与读音覆盖不一致。")
            override = pronunciation
        notes.append({**source, "start": start, "end": end, "key": int(key),
                      "lyric": lyric, "language": language, "pinyin_override": override,
                      "pronunciation_override": pronunciation})
        previous_end = end
    curve, previous_time = [], -1.0
    for point in source_curve:
        if not isinstance(point, dict):
            raise ValueError("音高曲线数据无效。")
        time = _number(point.get("time"), "曲线时间", 0, duration)
        if time < previous_time:
            raise ValueError("音高曲线必须按时间排序。")
        pitch = point.get("pitch")
        if pitch is not None:
            pitch = _number(pitch, "连续音高", 0, 127)
        normalized = {"time": time, "pitch": pitch}
        # An unvoiced marker wins identical-time collisions.
        if curve and curve[-1]["time"] == time:
            if pitch is None or curve[-1]["pitch"] is not None:
                curve[-1] = normalized
        else:
            curve.append(normalized)
        previous_time = time
    return {**result, "language": language, "bpm": bpm, "duration": duration, "notes": notes, "curve": curve}


def voiced_segments(curve):
    """Never interpolate across an explicit unvoiced marker."""
    segments, segment = [], []
    for point in curve:
        if point["pitch"] is None:
            if segment:
                segments.append(segment)
                segment = []
        else:
            segment.append(point)
    if segment:
        segments.append(segment)
    return segments


def _lyric(note):
    language = normalize_language(note.get("language"))
    if language == "zh":
        return note["pinyin_override"][:-1] if note.get("pinyin_override") else note["lyric"]
    if language == "ja":
        override = note.get("pronunciation_override")
        return (override if override and override != "ー" else None) or note.get("reading") or note["lyric"]
    return note["lyric"]


def synthv_payload(result):
    result = validate_result(result)
    return {"format": "vvtalkstudio-sv2", "version": 1, "title": "VvTalk 语音调教",
            "language": result["language"],
            "duration": result["duration"], "notes": [
                {"start": n["start"], "end": n["end"], "pitch": n["key"],
                 "lyrics": _lyric(n), "sourceLyrics": n["lyric"], "language": n["language"],
                 "pinyinOverride": n.get("pinyin_override"),
                 "pronunciationOverride": n.get("pronunciation_override"),
                 "reading": n.get("reading"), "phonemes": n.get("phonemes"),
                 "stressOverride": n.get("stress_override")}
                for n in result["notes"]],
            "segments": [[[p["time"], p["pitch"]] for p in segment]
                         for segment in voiced_segments(result["curve"])]}


def _write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    return Path(path)


def _note_at(notes, starts, time):
    index = bisect.bisect_right(starts, time) - 1
    return notes[index] if index >= 0 and time < notes[index]["end"] else None


def _pitch_at(curve, times, time):
    index = bisect.bisect_right(times, time) - 1
    if index < 0 or curve[index]["pitch"] is None:
        return None
    left = curve[index]
    if index + 1 == len(curve) or left["time"] == time:
        return left["pitch"]
    right = curve[index + 1]
    if right["pitch"] is None:
        return left["pitch"]
    weight = (time - left["time"]) / (right["time"] - left["time"])
    return left["pitch"] + weight * (right["pitch"] - left["pitch"])


def write_svp(result, path):
    """SV2 v196 native controls, matching the actual editor-saved project schema."""
    result = validate_result(result)
    rate = result["bpm"] * BLICK_PER_QUARTER / 60
    group_id = str(uuid.uuid4())
    notes, previous_end = [], 0
    for note in result["notes"]:
        start, end = round(note["start"] * rate), round(note["end"] * rate)
        end = max(start + 1, end)
        if start < previous_end:
            raise ValueError("SVP 量化后音符发生重叠。")
        notes.append({"uuid": uuid.uuid4().hex[:16], "musicalType": "singing",
                      "onset": start, "duration": end - start, "pitch": note["key"],
                      "lyrics": _lyric(note), "phonemes": "", "accent": "", "detune": 0,
                      "attributes": {"evenSyllableDuration": True, "muted": False,
                                     "languageOverride": SV_LANGUAGES[note["language"]],
                                     "phonesetOverride": "xsampa"},
                      "scriptData": {"vvtalkstudio.sourceLyrics": note["lyric"],
                                     "vvtalkstudio.language": note["language"]}})
        for source_field, data_field in [("pinyin_override", "pinyinOverride"),
                                         ("pronunciation_override", "pronunciationOverride"),
                                         ("reading", "reading"), ("phonemes", "phonemes"),
                                         ("stress_override", "stressOverride")]:
            if note.get(source_field) is not None:
                notes[-1]["scriptData"]["vvtalkstudio." + data_field] = note[source_field]
        previous_end = end
    controls = []
    for index, segment in enumerate(voiced_segments(result["curve"])):
        position, anchor = round(segment[0]["time"] * rate), segment[0]["pitch"]
        points = {round(point["time"] * rate) - position: point["pitch"] - anchor for point in segment}
        # Preserve an isolated measurement as a constant one-blick curve, using the
        # verified curve schema rather than inventing a point object's file fields.
        if len(points) == 1:
            points[1] = next(iter(points.values()))
        controls.append({"pos": position, "pitch": anchor, "id": str(index * 2), "type": "curve",
                         "points": [value for pair in sorted(points.items()) for value in pair]})
    group = {"name": "VvTalk 语音调教", "uuid": group_id, "notes": notes,
             "parameters": {name: {"mode": "cubic", "points": []} for name in
                ("pitchDelta", "vibratoEnv", "loudness", "tension", "breathiness", "voicing", "gender", "toneShift", "mouthOpening")},
             "vocalModes": {}, "pitchControls": controls, "musicalScale": {"type": "Major", "root": "C"}}
    data = {"version": 196, "time": {"meter": [{"index": 0, "numerator": 4, "denominator": 4}],
                    "tempo": [{"position": 0, "bpm": result["bpm"]}]},
            "library": [], "tracks": [{"name": "VvTalk 语音调教", "groups": [], "dispColor": "ff75a68a",
                "dispOrder": 0, "renderEnabled": True,
                "mixer": {"gainDecibel": 0, "pan": 0, "mute": False, "solo": False, "display": True},
                "mainGroup": group, "mainRef": {"uuid": str(uuid.uuid4()), "groupID": group_id,
                    "blickAbsoluteBegin": 0, "blickAbsoluteEnd": -1, "blickOffset": 0, "pitchOffset": 0, "mute": False,
                    "isInstrumental": False, "database": {"name": "", "language": "",
                    "phoneset": "", "languageOverride": SV_LANGUAGES[result["language"]], "phonesetOverride": "",
                    "backendType": "", "version": "-2"},
                    "dictionary": "", "voice": {}}}],
            "renderConfig": {"destination": "./", "filename": "VvTalk", "numChannels": 1,
                             "aspirationFormat": "noAspiration", "bitDepth": 16, "sampleRate": 44100,
                             "exportMixDown": True}}
    return _write_json(path, data)


def write_synthv_script(result, path):
    payload = json.dumps(synthv_payload(result), ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    template = (PLUGIN_DIR / "VvTalkStudio_Import.js").read_text(encoding="utf-8")
    return Path(path).write_text(template.replace("var EMBEDDED_DATA = null;", "var EMBEDDED_DATA = " + payload + ";"), encoding="utf-8")


def _element(parent, name, value=None, **attributes):
    item = ET.SubElement(parent, "{" + VSQX_NAMESPACE + "}" + name, attributes)
    if value is not None:
        item.text = str(value)
    return item


def write_vsqx(result, path):
    """VSQX4 monophonic lane with explicit PIT/PBS and unlocked pronunciation."""
    result = validate_result(result)
    bank = VOCALOID_BANKS[result["language"]]
    rate = result["bpm"] * 480 / 60
    notes, previous_end = [], 0
    for note in result["notes"]:
        start = round(note["start"] * rate)
        end = max(start + 1, round(note["end"] * rate))
        if start < previous_end:
            raise ValueError("VSQX 的 480 PPQ 量化后音符发生重叠；请稍微延长过短音符。")
        notes.append({**note, "tick_on": start, "tick_off": end})
        previous_end = end
    starts = [n["start"] for n in notes]
    deviations = []
    for point in result["curve"]:
        note = _note_at(notes, starts, point["time"])
        if note is not None and point["pitch"] is not None:
            deviations.append(abs(point["pitch"] - note["key"]))
    times = [point["time"] for point in result["curve"]]
    for note in notes:
        pitch = _pitch_at(result["curve"], times, note["start"])
        if pitch is not None:
            deviations.append(abs(pitch - note["key"]))
    pbs = max(2, math.ceil(max(deviations, default=0)))
    if pbs > 24:
        raise ValueError("音高偏移超过 VOCALOID 的 24 半音 PBS 范围；请调整基准音高。")
    events, event_notes, unvoiced_ticks = {0: 0}, {}, set()
    for point in result["curve"]:
        note = _note_at(notes, starts, point["time"])
        tick = round(point["time"] * rate)
        value = 0 if point["pitch"] is None or note is None else round((point["pitch"] - note["key"]) / pbs * 8192)
        if point["pitch"] is None:
            unvoiced_ticks.add(tick)
        events[tick] = min(8191, max(-8192, value))
        event_notes[tick] = note if point["pitch"] is not None else None
    for tick in unvoiced_ticks:
        events[tick] = 0
    # Note-key changes require a new relative PIT even without a source F0 sample.
    for note in notes:
        events.setdefault(note["tick_off"], 0)
        pitch = _pitch_at(result["curve"], times, note["start"])
        value = 0 if pitch is None else round((pitch - note["key"]) / pbs * 8192)
        # Keep a same-note source sample; a previous note uses a different baseline.
        if note["tick_on"] not in unvoiced_ticks and event_notes.get(note["tick_on"]) is not note:
            events[note["tick_on"]] = min(8191, max(-8192, value))
    root = ET.Element("{" + VSQX_NAMESPACE + "}vsq4")
    _element(root, "vender", "Yamaha corporation")
    _element(root, "version", "4.0.0.3")
    voice = _element(_element(root, "vVoiceTable"), "vVoice")
    for key, value in (("bs", bank), ("pc", 0), ("id", "0000000000000000"),
                       ("name", "Select installed " + SV_LANGUAGES[result["language"]] + " voice")):
        _element(voice, key, value)
    parameters = _element(voice, "vPrm")
    for key in ("bre", "bri", "cle", "gen", "ope"):
        _element(parameters, key, 0)
    mixer = _element(root, "mixer")
    master = _element(mixer, "masterUnit")
    for key in ("oDev", "rLvl", "vol"):
        _element(master, key, 0)
    for unit in ("vsUnit", "monoUnit", "stUnit"):
        child = _element(mixer, unit)
        if unit == "vsUnit":
            _element(child, "tNo", 0)
        _element(child, "iGin", 0)
        if unit != "stUnit":
            _element(child, "sLvl", -898)
            _element(child, "sEnable", 0)
        _element(child, "m", 0)
        _element(child, "s", 0)
        if unit != "stUnit":
            _element(child, "pan", 64)
        _element(child, "vol", 0)
    master = _element(root, "masterTrack")
    for key, value in (("seqName", "VvTalk"), ("comment", "Speech prosody; choose a compatible voice and recompute phonemes"),
                       ("resolution", 480), ("preMeasure", 0)):
        _element(master, key, value)
    signature = _element(master, "timeSig")
    for key, value in (("m", 0), ("nu", 4), ("de", 4)):
        _element(signature, key, value)
    tempo = _element(master, "tempo")
    _element(tempo, "t", 0)
    _element(tempo, "v", round(result["bpm"] * 100))
    track = _element(root, "vsTrack")
    for key, value in (("tNo", 0), ("name", "VvTalk 语音调教"), ("comment", "Independent imported track")):
        _element(track, key, value)
    part = _element(track, "vsPart")
    for key, value in (("t", 0), ("playTime", max(previous_end, math.ceil(result["duration"] * rate)) + 1),
                       ("name", "VvTalk 语音调教"), ("comment", "Absolute source F0 encoded as PIT/PBS")):
        _element(part, key, value)
    plugin = _element(part, "sPlug")
    for key, value in (("id", "ACA9C502-A04B-42b5-B2EB-5CEA36D16FCE"),
                       ("name", "VOCALOID2 Compatible Style"), ("version", "3.0.0.1")):
        _element(plugin, key, value)
    style = _element(part, "pStyle")
    for key, value in (("accent", 0), ("bendDep", 0), ("bendLen", 0), ("decay", 0),
                       ("fallPort", 0), ("opening", 127), ("risePort", 0)):
        _element(style, "v", value, id=key)
    singer = _element(part, "singer")
    for key, value in (("t", 0), ("bs", bank), ("pc", 0)):
        _element(singer, key, value)
    cc = _element(part, "cc")
    _element(cc, "t", 0)
    _element(cc, "v", pbs, id="S")
    for tick, value in sorted(events.items()):
        cc = _element(part, "cc")
        _element(cc, "t", tick)
        _element(cc, "v", value, id="P")
    for note in notes:
        child = _element(part, "note")
        for key, value in (("t", note["tick_on"]), ("dur", note["tick_off"] - note["tick_on"]),
                           ("n", note["key"]), ("v", 64), ("y", _lyric(note))):
            _element(child, key, value)
        # Unlocked phonemes deliberately defer to the selected installed dictionary.
        _element(child, "p", "", lock="0")
        note_style = _element(child, "nStyle")
        for key, value in (("accent", 0), ("bendDep", 0), ("bendLen", 0), ("decay", 0),
                           ("fallPort", 0), ("opening", 127), ("risePort", 0), ("vibLen", 0), ("vibType", 0)):
            _element(note_style, "v", value, id=key)
    _element(root, "monoTrack")
    _element(root, "stTrack")
    _element(root, "aux")
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return Path(path)


def export_project(result: dict, document: dict | None, destination: Path, target: str, template: Path) -> dict:
    if target not in ("synthv", "ace", "vocaloid5", "vocaloid6", "all"):
        raise ValueError("请选择 Synthesizer V、ACE Studio、VOCALOID 5/6 或全部。")
    result = validate_result(result)
    if document is not None and normalize_language(document.get("language", document.get("settings", {}).get("language"))) != result["language"]:
        raise ValueError("分析结果与长文工程的语言不一致；请重新分析后导出。")
    language_name = LANGUAGE_NAMES[result["language"]]
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    files, warnings = [], []
    def record(path, name, format):
        files.append({"name": name, "path": str(Path(path).resolve()), "format": format})
    if target in ("synthv", "all"):
        path = destination / "语音调教.svp"
        write_svp(result, path)
        record(path, "Synthesizer V 工程", "svp")
        warnings.append(f"SVP 使用 SV2 原生绝对 pitchControls 曲线（要求 SV2 Pro 2.1.0+），导入后选择支持{language_name}的声库。剪贴板插件是已有工程中新建轨道的可选操作。")
    if target in ("vocaloid5", "vocaloid6", "all"):
        path = write_vsqx(result, destination / "语音调教.vsqx")
        record(path, "VOCALOID 5/6 可导入工程", "vsqx")
        warnings.append(f"VOCALOID 导入后选择已安装的{language_name}声库并重新计算未锁定发音。VSQX 的 PIT/PBS 已编码语调，V6 的 VOCALOID 与 VOCALOID:AI 轨道仍需在宿主中复核。")
        if result["language"] == "zh":
            warnings.append("中文手动拼音以无声调拼音歌词保存，原汉字保留在逐字数据中。")
    if target in ("ace", "all"):
        path = destination / "语音调教.acep"
        try:
            if document is not None:
                build_long_acep(document, template, path)
            else:
                build_acep(result, template, path)
        except ValueError as exc:
            if target != "all":
                raise
            warnings.append("ACE Studio 未导出：" + str(exc) + " 其他已列出的目标文件已生成。")
        else:
            record(path, "ACE Studio 原生工程", "acep")
            warnings.append(f"{language_name} ACEP 使用分别校验的 stock singer ID 与可用 seed code，默认声库来自离线缓存；导入后请复核实际发音与本机声库状态。")
    if result["language"] == "en" and target != "ace" and any(
            note.get("pronunciation_override") for note in result["notes"]):
        warnings.append("英语 ARPAbet 读音覆盖保留在 JSON/脚本元数据中；SV 与 VOCALOID 使用原词及各自发音词典，音素符号不能直接跨宿主通用，请在宿主复核该覆盖。")
    starts = [note["start"] for note in result["notes"]]
    if any(point["pitch"] is None and _note_at(result["notes"], starts, point["time"]) is not None
           for point in result["curve"]):
        warnings.append("音符内部含清音帧：曲线保留清音分段，但 SV/VOCALOID 无法仅通过音高控制强制静音；发音取决于声库。音符间停顿保持无音符。")
    return {"files": files, "warnings": warnings}


def install_synthv_script(folder):
    """Install only into the user-selected existing directory, preserving older files."""
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError("请选择 Synthesizer V 的现有 scripts 文件夹。")
    source = PLUGIN_DIR / "VvTalkStudio_Import.js"
    destination = folder / source.name
    backup = None
    if destination.exists():
        backup = folder / (source.name + ".backup-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        shutil.copy2(destination, backup)
    shutil.copy2(source, destination)
    return {"path": str(destination), "backup": str(backup) if backup else None,
            "message": "已安装；在 Synthesizer V 中重新扫描脚本，然后运行 VvTalk Studio → 导入剪贴板语调。"}
