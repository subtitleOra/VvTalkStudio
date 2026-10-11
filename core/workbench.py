"""Editable long-text timelines sharing language units with reference analysis."""

from __future__ import annotations

import math
import re
import uuid

import numpy as np

from engine import _HAN, _characters, _stats, analyze
from pronunciation import normalize_pinyin_override
from languages import apply_unit_overrides, normalize_language, text_units


MAX_CHARACTERS = 10000
MAX_SECTION_CHARACTERS = 120
MAX_DURATION = 3600
MAX_CURVE_POINTS = 1500000
ORDINARY_GAP_MS = 1000 * 2 / 960
DEFAULT_SETTINGS = {"rate": 1.0, "syllable_ms": 210.0, "comma_pause_ms": 180.0,
                    "sentence_pause_ms": 420.0, "paragraph_pause_ms": 700.0,
                    "base_pitch": 61.0, "range_scale": 1.0, "smoothing_ms": 10.0,
                    "bpm": 120.0}
_LIMITS = {"rate": (.25, 4), "syllable_ms": (80, 3000), "comma_pause_ms": (0, 10000),
           "sentence_pause_ms": (0, 10000), "paragraph_pause_ms": (0, 10000),
           "base_pitch": (12, 108), "range_scale": (0, 4), "smoothing_ms": (0, 500),
           "bpm": (20, 400), "pause_after_ms": (0, 30000)}
_SENTENCE_END = set("。！？.!?")
_COMMA = set("，、；：,;:")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _number(value, name, lower, upper):
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是数值。")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数值。") from exc
    if not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f"{name} 必须在 {lower} 至 {upper} 之间。")
    return value


def _settings(supplied, local=False):
    if supplied is None:
        supplied = {}
    if not isinstance(supplied, dict):
        raise ValueError("settings 必须是对象。")
    allowed = (set(DEFAULT_SETTINGS) - {"bpm"}) | {"pause_after_ms"} if local else set(DEFAULT_SETTINGS)
    unknown = set(supplied) - allowed
    if unknown:
        raise ValueError(f"不支持的{'本句' if local else '全局'}设置：{', '.join(sorted(unknown))}。")
    output = {} if local else dict(DEFAULT_SETTINGS)
    for key, value in supplied.items():
        if local and key == "pause_after_ms" and value is None:
            output[key] = None
        else:
            output[key] = _number(value, key, *_LIMITS[key])
    return output


def _identity(supplied, prefix):
    if supplied is None:
        return prefix + uuid.uuid4().hex[:16]
    if not isinstance(supplied, str) or not _ID.fullmatch(supplied):
        raise ValueError("文档和句子 id 只能包含字母、数字、下划线、连字符，最长 80 字符。")
    return supplied


def _split_text(text):
    """Keep every input character, including punctuation, spaces and blank lines."""
    output, start, count, paragraph, section_paragraph = [], 0, 0, 0, 0
    for i, char in enumerate(text):
        if _HAN.fullmatch(char):
            if count >= MAX_SECTION_CHARACTERS:
                output.append({"text": text[start:i], "paragraph": section_paragraph})
                start, count = i, 0
            if count == 0:
                section_paragraph = paragraph
            count += 1
        if char in _SENTENCE_END or char in "\n\r":
            if count:
                output.append({"text": text[start:i + 1], "paragraph": section_paragraph})
                start, count = i + 1, 0
            elif output:
                output[-1]["text"] += text[start:i + 1]
                start = i + 1
            if char == "\n" or char == "\r" and (i + 1 == len(text) or text[i + 1] != "\n"):
                paragraph += 1
    if count:
        output.append({"text": text[start:], "paragraph": section_paragraph})
    elif start < len(text) and output:
        output[-1]["text"] += text[start:]
    return output


def _automatic_pause(following, settings, is_document_end):
    if "\n" in following or "\r" in following:
        return settings["paragraph_pause_ms"]
    if any(char in _SENTENCE_END for char in following):
        return settings["sentence_pause_ms"]
    if any(char in _COMMA for char in following):
        return settings["comma_pause_ms"]
    return settings["sentence_pause_ms"] if is_document_end else ORDINARY_GAP_MS


def _split_language_text(text, units):
    """Split on sentence/paragraph boundaries without breaking a Japanese word."""
    counts = {}
    for unit in units:
        counts[unit["text_position"]] = counts.get(unit["text_position"], 0) + 1
    output, start, count, paragraph, section_paragraph = [], 0, 0, 0, 0
    for i, char in enumerate(text):
        width = counts.get(i, 0)
        if width:
            if count and count + width > MAX_SECTION_CHARACTERS:
                output.append({"text": text[start:i], "paragraph": section_paragraph, "_text_start": start})
                start, count = i, 0
            if not count:
                section_paragraph = paragraph
            count += width
        if char in _SENTENCE_END or char in "\n\r":
            if count:
                output.append({"text": text[start:i + 1], "paragraph": section_paragraph, "_text_start": start})
                start, count = i + 1, 0
            elif output:
                output[-1]["text"] += text[start:i + 1]
                start = i + 1
            if char == "\n" or char == "\r" and (i + 1 == len(text) or text[i + 1] != "\n"):
                paragraph += 1
    if count:
        output.append({"text": text[start:], "paragraph": section_paragraph, "_text_start": start})
    elif start < len(text) and output:
        output[-1]["text"] += text[start:]
    return output


def _overrides(source, syllables, language):
    entries = source.get("characters")
    if entries is None:
        return [{} for _ in syllables], False
    if not isinstance(entries, list):
        raise ValueError("characters 必须是数组。")
    for entry in entries:
        if isinstance(entry, dict) and entry.get("language") is not None and normalize_language(entry["language"]) != language:
            raise ValueError("逐单元编辑 language 与文档语言不一致；请新建对应语言文档。")
    matched = (len(entries) == len(syllables) and all(isinstance(entry, dict)
               and entry.get("lyric") == syllable["lyric"] for entry, syllable in zip(entries, syllables)))
    if not matched:
        # Never transfer an old character's edit to a different character.
        return [{} for _ in syllables], True
    output = []
    for i, entry in enumerate(entries):
        edited = {}
        for field, limits in (("duration_override_ms", (20, 30000)), ("pause_override_ms", (0, 30000))):
            value = entry.get(field)
            edited[field] = None if value is None else _number(value, f"第 {i + 1} 字 {field}", *limits)
        pitch_shift = entry.get("pitch_shift", 0)
        if _number(pitch_shift, "pitch_shift", -48, 48) != 0:
            raise ValueError("暂不支持逐字 pitch_shift；请调整本句基准音高。")
        edited["pinyin_override"] = normalize_pinyin_override(entry.get("pinyin_override")) if language == "zh" else None
        if language != "zh" and entry.get("pinyin_override") is not None:
            raise ValueError("日语和英语使用 pronunciation_override，不使用中文 pinyin_override。")
        for field in ("pronunciation_override", "accent_override", "stress_override"):
            edited[field] = entry.get(field)
        output.append(edited)
    apply_unit_overrides([dict(unit) for unit in syllables], output)
    return output, False


def build_document(payload):
    """Rebuild from text/settings/overrides; supplied generated results are ignored."""
    if not isinstance(payload, dict):
        raise ValueError("请求必须是 JSON 对象。")
    language = normalize_language(payload.get("language"))
    settings = _settings(payload.get("settings"))
    supplied = payload.get("sections")
    if supplied is not None:
        if not isinstance(supplied, list) or not supplied or not all(isinstance(s, dict) for s in supplied):
            raise ValueError("sections 必须是非空句子对象数组。")
        if not all(isinstance(source.get("text"), str) for source in supplied):
            raise ValueError("每个句子必须有 text。")
        combined = "".join(source["text"] for source in supplied)
        text = payload.get("text", combined)
        if text != combined:
            raise ValueError("全文 text 与句子文本连接不一致；请同步修改全文，避免丢失内容。")
        sources = supplied
    else:
        text = payload.get("text", "")
        if language == "zh":
            _characters(text)
            sources = _split_text(text)
        else:
            units = text_units(text, language, payload.get("word_readings"))
            sources = _split_language_text(text, units)
            if payload.get("word_readings") is not None:
                for source in sources:
                    first = source["_text_start"]
                    source["word_readings"] = {str(int(key) - first): value for key, value in payload["word_readings"].items()
                                               if first <= int(key) < first + len(source["text"])}
    if not isinstance(text, str) or len(text) > 20000:
        raise ValueError("全文最多 20000 字符。")
    if language == "zh":
        _characters(text)
    if language != "ja" and payload.get("word_readings") is not None:
        raise ValueError("word_readings 仅用于日语整词读音。")
    prepared = []
    for source in sources:
        if normalize_language(source.get("language", language)) != language:
            raise ValueError("句子 language 与文档语言不一致；请新建对应语言文档。")
        if language != "ja" and source.get("word_readings") is not None:
            raise ValueError("word_readings 仅用于日语整词读音。")
        prepared.append(text_units(source["text"], language, source.get("word_readings")))
    unit_count = sum(map(len, prepared))
    if unit_count > MAX_CHARACTERS:
        raise ValueError("长文本最多支持 10000 个发音单元。")
    title = payload.get("title", "长文本语调")
    if not isinstance(title, str) or len(title) > 200:
        raise ValueError("标题必须是最多 200 字符的文本。")
    document_id = _identity(payload.get("id"), "doc_")
    sections, warnings, ids, offset, paragraph = [], [], set(), 0.0, 0
    for section_index, (source, syllables) in enumerate(zip(sources, prepared)):
        section_text = source["text"]
        if len(syllables) > MAX_SECTION_CHARACTERS:
            raise ValueError("每个句子最多 120 个发音单元；修改长句后请重新分段。")
        section_id = _identity(source.get("id"), "s_")
        if section_id in ids:
            raise ValueError("句子 id 不能重复。")
        ids.add(section_id)
        local = _settings(source.get("settings"), local=True)
        effective = dict(settings)
        effective.update({key: value for key, value in local.items() if key not in ("rate", "pause_after_ms")})
        effective_rate = settings["rate"] * local.get("rate", 1)
        engine_payload = {"mode": "text", "language": language, "text": section_text, "bpm": settings["bpm"], "pause_ms": 0,
                          **{key: effective[key] for key in ("syllable_ms", "base_pitch", "range_scale", "smoothing_ms")}}
        if source.get("word_readings") is not None:
            engine_payload["word_readings"] = source["word_readings"]
        edits, reset = _overrides(source, syllables, language)
        if language == "zh":
            engine_payload["pinyin_overrides"] = [edit.get("pinyin_override") for edit in edits]
        engine_payload["unit_overrides"] = edits
        draft = analyze(engine_payload)
        if reset:
            warnings.append(f"第 {section_index + 1} 句发音单元已变化，已清除不匹配的旧编辑。")
        alignment, characters, position = [], [], 0.0
        for i, (syllable, note, edit) in enumerate(zip(syllables, draft["notes"], edits)):
            duration_override = edit.get("duration_override_ms")
            pause_override = edit.get("pause_override_ms")
            duration_ms = duration_override if duration_override is not None else (
                (note["end"] - note["start"]) * 1000 / effective_rate)
            last = i == len(syllables) - 1
            pause_ms = _automatic_pause(syllable["following"], effective, last and section_index == len(sources) - 1)
            if last and local.get("pause_after_ms") is not None:
                pause_ms = local["pause_after_ms"]
            if pause_override is not None:
                pause_ms = pause_override
            start, end = position, position + duration_ms / 1000
            alignment.append({"lyric": syllable["lyric"], "start": start, "end": end})
            characters.append({"index": i, "lyric": syllable["lyric"], "pinyin": syllable["pinyin"],
                               "auto_pinyin": syllable["pinyin"], "pinyin_override": edit.get("pinyin_override"),
                               "tone": note["tone"], "duration_ms": round(duration_ms, 6),
                               "pause_after_ms": round(pause_ms, 6), "duration_override_ms": duration_override,
                               "pause_override_ms": pause_override, "pitch_shift": 0,
                               "start": round(start, 6), "end": round(end, 6)})
            characters[-1].update(language=language, pronunciation_override=edit.get("pronunciation_override"),
                                  accent_override=edit.get("accent_override"), stress_override=edit.get("stress_override"))
            position = end + pause_ms / 1000
        duration = round(position, 6)
        if duration >= 600:
            raise ValueError("单句连同停顿需短于 600 秒；请拆句或缩短停顿。")
        if offset + duration > MAX_DURATION:
            raise ValueError("长文本总时长最多 1 小时；请分成多个工作台文档。")
        result = analyze({**engine_payload, "alignment": alignment})
        for character, note in zip(characters, result["notes"]):
            character["pinyin"], character["tone"] = note["pinyin"], note["tone"]
            for key in ("reading", "auto_reading", "text_position", "text_end", "following", "source_text",
                        "word_index", "word_reading", "word_accent", "accent", "auto_accent", "mora_kind",
                        "mora_index", "word_mora_count", "phonemes", "syllables", "stress", "syllable_count", "reading_source"):
                if key in note:
                    character[key] = note[key]
            if language != "zh":
                character["auto_pinyin"] = note.get("auto_reading", syllables[character["index"]]["reading"])
        # The engine ends at the last note; the workbench owns the explicit tail pause.
        result["duration"] = duration
        if result["curve"][-1]["time"] < duration:
            result["curve"].append({"time": duration, "pitch": None})
        section_paragraph = source.get("paragraph", paragraph)
        if isinstance(section_paragraph, bool) or not isinstance(section_paragraph, int) or section_paragraph < 0:
            raise ValueError("paragraph 必须是非负整数。")
        sections.append({"id": section_id, "language": language, "text": section_text, "paragraph": section_paragraph,
                         "settings": local, "characters": characters, "result": result,
                         "duration": duration, "offset": round(offset, 6), "effective_rate": effective_rate})
        if source.get("word_readings") is not None:
            sections[-1]["word_readings"] = dict(source["word_readings"])
        offset = round(offset + duration, 6)
        paragraph += len(re.findall(r"\r\n|\r|\n", section_text))
    return {"format": "ace-tts-workbench", "version": 1, "id": document_id, "title": title or "长文本语调",
            "text": text, "language": language, "settings": settings, "bpm": settings["bpm"], "sections": sections,
            "duration": offset, "character_count": unit_count, "section_count": len(sections),
            "warnings": warnings, "pipeline_version": "workbench-v1"}


def flatten_document(document, section_id=None):
    """Produce the old engine result, preserving voiced islands during decimation."""
    if not isinstance(document, dict) or document.get("format") != "ace-tts-workbench" or document.get("version") != 1:
        raise ValueError("不是受支持的 ACE 长文本工作台文档。")
    # Recompute imported/edited JSON instead of trusting embedded notes and curves.
    rebuilt = build_document(document)
    sections = rebuilt["sections"]
    if section_id is not None:
        matches = [section for section in sections if section["id"] == section_id]
        if not matches:
            raise ValueError("找不到所选句子。")
        return matches[0]["result"]
    notes, curve, warnings, text_offset, word_readings = [], [], list(rebuilt["warnings"]), 0, {}
    for section in sections:
        offset, result = section["offset"], section["result"]
        for note in result["notes"]:
            shifted_note = {**note, "start": round(offset + note["start"], 6), "end": round(offset + note["end"], 6)}
            for key in ("text_position", "text_end"):
                if key in note:
                    shifted_note[key] = note[key] + text_offset
            notes.append(shifted_note)
        for point in result["curve"]:
            shifted = {"time": round(offset + point["time"], 6), "pitch": point["pitch"]}
            if curve and curve[-1]["time"] == shifted["time"]:
                curve[-1] = shifted
            else:
                curve.append(shifted)
        warnings.extend(result["warnings"])
        word_readings.update({str(int(key) + text_offset): value for key, value in section.get("word_readings", {}).items()})
        text_offset += len(section["text"])
    stride = 1
    if len(curve) > MAX_CURVE_POINTS:
        transitions = set()
        for i in range(1, len(curve)):
            if (curve[i]["pitch"] is None) != (curve[i - 1]["pitch"] is None):
                transitions.update((i - 1, i))
        budget = MAX_CURVE_POINTS - len(transitions) - 2
        if budget <= 0:
            raise ValueError("音高曲线发声区间过多，请分成多个文档。")
        stride = math.ceil(len(curve) / budget)
        curve = [point for i, point in enumerate(curve)
                 if i % stride == 0 or i in transitions or i == len(curve) - 1]
    values = np.asarray([np.nan if point["pitch"] is None else point["pitch"] for point in curve])
    output = {"mode": "text", "language": rebuilt["language"], "text": rebuilt["text"], "bpm": rebuilt["bpm"], "notes": notes, "curve": curve,
            "duration": rebuilt["duration"], "warnings": list(dict.fromkeys(warnings)),
            "alignment_source": "workbench", "stats": _stats(notes, values, {
                "pipeline_version": "speech-v2", "workbench_version": 1, "note_pitch_mode": "fixed_baseline",
                "frame_step_seconds": .002 * stride, "section_count": len(sections)})}
    if word_readings:
        output["word_readings"] = word_readings
    return output
