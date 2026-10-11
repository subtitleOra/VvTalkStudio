"""Read one constant-tempo VSQX4 part without changing its source file."""

from __future__ import annotations

import bisect
import re
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path
from languages import normalize_language, text_units


def _integer(element, field, default=None):
    raw = element.findtext(field)
    if raw is None and default is not None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"VSQX 的 {field} 字段不是有效整数。") from exc


def read_vsqx(path, text=None, language="zh"):
    """Return the workbench's seconds/absolute-MIDI result, starting at note one."""
    language = normalize_language(language)
    source_path = Path(path)
    if not source_path.is_file():
        raise ValueError("VSQX 文件不存在。")
    if source_path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("VSQX 文件最多为 20 MB。")
    raw = source_path.read_bytes()
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", raw, re.I):
        raise ValueError("不支持含有 DTD 或外部实体声明的 VSQX。")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("VSQX 不是有效 XML 文件。") from exc
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    if root.tag != "vsq4":
        raise ValueError("目前只支持 VSQX4 文件。")
    master = root.find("masterTrack")
    if master is None:
        raise ValueError("VSQX 缺少 masterTrack。")
    resolution = _integer(master, "resolution")
    pre_measure = _integer(master, "preMeasure", 0)
    if resolution <= 0 or pre_measure < 0:
        raise ValueError("VSQX 的分辨率或预备小节无效。")
    tempos = [(_integer(event, "t"), _integer(event, "v")) for event in master.findall("tempo")]
    if not tempos or min(t for t, _ in tempos) != 0 or any(t < 0 or v <= 0 for t, v in tempos):
        raise ValueError("VSQX 必须从第 0 tick 提供有效速度。")
    if len({v for _, v in tempos}) != 1:
        raise ValueError("目前不支持变速 VSQX；请使用单一速度工程。")
    bpm = tempos[0][1] / 100
    if not 20 <= bpm <= 400:
        raise ValueError("VSQX 的速度需在 20 至 400 BPM 之间。")
    signatures = master.findall("timeSig")
    if len(signatures) != 1 or _integer(signatures[0], "m") != 0:
        raise ValueError("目前仅支持从第 0 小节开始的单一拍号。")
    numerator = _integer(signatures[0], "nu")
    denominator = _integer(signatures[0], "de")
    if numerator <= 0 or denominator not in (1, 2, 4, 8, 16, 32, 64):
        raise ValueError("VSQX 拍号无效。")
    tracks = root.findall("vsTrack")
    if len(tracks) != 1:
        raise ValueError("目前不支持多轨 VSQX；请单独导出一条人声轨。")
    parts = tracks[0].findall("vsPart")
    if len(parts) != 1:
        raise ValueError("目前不支持多段 VSQX；请单独导出一个人声段落。")
    part = parts[0]
    part_tick = _integer(part, "t")
    if part_tick < 0:
        raise ValueError("VSQX 段落起点不能为负数。")
    source_notes = []
    for note in part.findall("note"):
        start, length, key = (_integer(note, name) for name in ("t", "dur", "n"))
        if start < 0 or length <= 0 or not 0 <= key <= 127:
            raise ValueError("VSQX 音符的起点、长度或音高无效。")
        lyric = note.findtext("y", "")
        if not lyric:
            raise ValueError("VSQX 音符缺少歌词。")
        source_notes.append({"start": start, "end": start + length, "key": key,
                             "lyric": lyric, "phoneme": note.findtext("p", "")})
    source_notes.sort(key=lambda note: note["start"])
    if not source_notes:
        raise ValueError("VSQX 段落没有音符。")
    if any(left["end"] > right["start"] for left, right in zip(source_notes, source_notes[1:])):
        raise ValueError("不支持含有重叠音符的 VSQX。")
    if text is not None:
        if not isinstance(text, str):
            raise ValueError("覆盖歌词必须是当前语言的文本。")
        units = text_units(text, language)
        if len(units) != len(source_notes):
            unit_name = {"zh": "汉字", "ja": "假名拍", "en": "英语词"}[language]
            raise ValueError(f"覆盖文本的{unit_name}数量须等于音符数量（{len(source_notes)}）。")
    else:
        lyrics = [note["lyric"] for note in source_notes]
        text = " ".join(lyrics)
        units = []
        for lyric in lyrics:
            unit = {"lyric": lyric, "reading": lyric, "language": language}
            if language == "ja" and lyric == "ー":
                from languages import _long_vowel
                actual = _long_vowel(units[-1]["reading"]) if units else None
                if actual is None:
                    raise ValueError("VSQX 的日语独立长音缺少可确定母音的前一拍；请提供完整原文覆盖或先修正歌词。")
                unit.update(lyric=actual, reading=actual, mora_kind="long", source_text=lyric)
            if language != "zh":
                try:
                    parsed = text_units(unit["lyric"], language)
                except ValueError:
                    parsed = []
                if len(parsed) == 1:
                    unit = {**parsed[0], **{k: v for k, v in unit.items() if k in ("mora_kind", "source_text")}}
            units.append(unit)
        if language == "ja":
            text = " ".join(unit["lyric"] for unit in units)
    first_tick, end_tick = source_notes[0]["start"], source_notes[-1]["end"]
    tick_rate = bpm * resolution / 60
    notes = [{**unit, "lyric": unit["lyric"], "language": language,
              "pinyin": note["lyric"] if language == "zh" else unit.get("reading", unit["lyric"]), "tone": None,
              "start": round((note["start"] - first_tick) / tick_rate, 6),
              "end": round((note["end"] - first_tick) / tick_rate, 6), "key": note["key"],
              "source_lyric": note["lyric"], "source_phoneme": note["phoneme"],
              "source_tick_on": note["start"], "source_tick_off": note["end"]}
             for unit, note in zip(units, source_notes)]
    events, pbs_events, pit_count = {}, [], 0
    for controller in part.findall("cc"):
        value = controller.find("v")
        if value is None or value.get("id") not in ("P", "S"):
            continue
        tick = _integer(controller, "t")
        try:
            amount = int(value.text)
        except (TypeError, ValueError) as exc:
            raise ValueError("VSQX PIT/PBS 控制值无效。") from exc
        name = value.get("id")
        if tick < 0 or (name == "P" and not -8192 <= amount <= 8191) or (name == "S" and not 0 <= amount <= 24):
            raise ValueError("VSQX PIT/PBS 控制值超出支持范围。")
        events.setdefault(tick, {})[name] = amount
        if name == "P":
            pit_count += 1
        else:
            pbs_events.append({"source_tick": tick, "tick": tick - first_tick,
                               "time": round((tick - first_tick) / tick_rate, 6), "value": amount})
    pbs_events.sort(key=lambda event: event["source_tick"])
    # PBS changes affect the held PIT, so both controller timelines must be sampled.
    ticks = sorted(set(events) | {note[edge] for note in source_notes for edge in ("start", "end")})
    starts = [note["start"] for note in source_notes]
    pbs, pit, curve = 2, 0, []
    for tick in ticks:
        changes = events.get(tick, {})
        pbs, pit = changes.get("S", pbs), changes.get("P", pit)
        if first_tick <= tick <= end_tick:
            note = source_notes[bisect.bisect_right(starts, tick) - 1]
            curve.append({"time": round((tick - first_tick) / tick_rate, 6),
                          "pitch": round(note["key"] + pit * pbs / 8192, 6)})
    values = [point["pitch"] for point in curve]
    prefix_ticks = pre_measure * resolution * numerator * 4 / denominator
    offset_ticks = part_tick + first_tick - prefix_ticks
    source_offset = offset_ticks / tick_rate
    warnings = ["仅转换源文件音符与 PIT/PBS；音色、力度、颤音和合成器发音效果需要在 ACE 中另行复核。",
                f"首音符已移至第 0 秒；源工程位置为 {source_offset:.6f} 秒（已扣除 {pre_measure} 个预备小节）。"]
    if pbs_events and min(event["source_tick"] for event in pbs_events) > first_tick:
        warnings.append("首音符起点的 PBS 尚未设置，初始音高按默认 PBS=2 还原；后续 PBS 事件保留在原 tick。")
    stats = {"note_count": len(notes), "frame_count": len(curve), "voiced_frames": len(curve),
             "voiced_ratio": 1.0, "pitch_min": round(min(values), 3), "pitch_max": round(max(values), 3),
             "pitch_median": round(statistics.median(values), 3), "pitch_method": "vsqx_pit_pbs",
             "pipeline_version": "vsqx-exact-v1", "note_pitch_mode": "source_notes",
             "source_resolution": resolution, "source_pit_count": pit_count,
             "source_pbs_count": len(pbs_events)}
    return {"mode": "vsqx", "language": language, "text": text, "bpm": bpm, "notes": notes, "curve": curve,
            "duration": round((end_tick - first_tick) / tick_rate, 6), "warnings": warnings,
            "alignment_source": "source_vsqx", "source_path": str(source_path.resolve()),
            "source_part_tick": part_tick, "source_first_note_tick": first_tick,
            "source_offset_ticks": offset_ticks, "source_offset_seconds": round(source_offset, 6),
            "source_pre_measure": pre_measure, "source_time_signature": [numerator, denominator],
            "source_pbs_events": pbs_events, "stats": stats}
