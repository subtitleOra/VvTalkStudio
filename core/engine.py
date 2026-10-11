"""Local dictionary prosody drafts; seconds internally, MIDI semitones for F0."""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import parselmouth

from pronunciation import normalize_pinyin_override
from languages import apply_unit_overrides, normalize_language, text_units


_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_PUNCTUATION = set("，。！？；：、,.!?;:…—-（）()【】[]《》〈〉“”‘’\"'·")
_SENTENCE_END = set("。！？.!?\n\r")
_TEXT_FRAME_STEP = .002
_TEXT_NOTE_GAP = 2 / 960
_MANUAL_JOIN_LIMIT = .04


def _number(payload, name, default, lower, upper):
    value = payload.get(name, default)
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是数值。")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数值。") from exc
    if not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f"{name} 必须在 {lower} 至 {upper} 之间。")
    return value


def _characters(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("请输入中文句子。")
    if len(text) > 20000:
        raise ValueError("单次最多处理 20000 个字符。")
    invalid = [c for c in text if not _HAN.fullmatch(c) and c not in _PUNCTUATION and not c.isspace()]
    if invalid:
        raise ValueError(f"文本仅支持中文和标点；请先把英文字母、数字或其他符号改为中文：{''.join(dict.fromkeys(invalid))[:30]}")
    chars = [c for c in text if _HAN.fullmatch(c)]
    if not chars:
        raise ValueError("文本至少需要一个中文字。")
    return chars


def _syllables(text):
    return text_units(text, "zh")


def _pinyin_overrides(syllables, payload):
    supplied = payload.get("pinyin_overrides")
    if supplied is None:
        return
    if not isinstance(supplied, list) or len(supplied) != len(syllables):
        raise ValueError("pinyin_overrides 必须与汉字数量一致；自动读音请填 null。")
    for syllable, value in zip(syllables, supplied):
        normalized = normalize_pinyin_override(value)
        if normalized is not None:
            syllable.update(auto_pinyin=syllable["pinyin"], pinyin_override=normalized,
                            pinyin=normalized, tone=int(normalized[-1]), original_tone=int(normalized[-1]))


def _sandhi(syllables, timings=None):
    changes = 0
    for i, syllable in enumerate(syllables):
        if syllable.get("pinyin_override") is not None:
            continue
        if i + 1 >= len(syllables) or _phrase_break(syllable):
            continue
        if timings is not None and timings[i + 1][0] - timings[i][1] > _MANUAL_JOIN_LIMIT:
            continue
        next_tone = syllables[i + 1]["original_tone"]
        tone = syllable["tone"]
        if tone == 3 and next_tone == 3:
            syllable["tone"] = 2
        elif syllable["lyric"] == "不" and next_tone == 4:
            syllable["tone"] = 2
        elif syllable["lyric"] == "一" and not (i and syllables[i - 1]["lyric"] == "第"):
            if next_tone == 4:
                syllable["tone"] = 2
            elif next_tone in (1, 2, 3):
                syllable["tone"] = 4
        if syllable["tone"] != tone:
            changes += 1
    return changes


def _smooth(values, smoothing_ms, step):
    """Moving average on each voiced island separately; never fill an unvoiced gap."""
    output = np.array(values, dtype=float, copy=True)
    width = max(1, int(round(smoothing_ms / 1000 / step)))
    if width % 2 == 0:
        width += 1
    valid = np.isfinite(output)
    edges = np.diff(np.r_[False, valid, False].astype(int))
    for begin, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        segment = output[begin:end]
        local_width = min(width, 2 * (len(segment) // 2) + 1)
        if local_width > 1:
            pad = local_width // 2
            output[begin:end] = np.convolve(np.pad(segment, (pad, pad), mode="edge"),
                                            np.ones(local_width) / local_width, mode="valid")
    return output


def _transform(values, shift, scale, smoothing_ms, step, center=None):
    values = np.array(values, dtype=float, copy=True)
    valid = np.isfinite(values)
    if np.any(valid):
        center = float(np.median(values[valid])) if center is None else center
        values[valid] = center + (values[valid] - center) * scale + shift
    return _smooth(values, smoothing_ms, step)


def _curve(times, values, duration):
    result = [{"time": round(float(time), 6), "pitch": round(float(value), 6) if math.isfinite(value) else None}
              for time, value in zip(times, values)]
    if not result or result[0]["time"] > 0:
        result.insert(0, {"time": 0.0, "pitch": None})
    if result[-1]["time"] < duration:
        result.append({"time": round(duration, 6), "pitch": None})
    return result


def _stats(notes, values, extra=None):
    valid = np.asarray(values)[np.isfinite(values)]
    result = {"note_count": len(notes), "frame_count": len(values), "voiced_frames": len(valid),
              "voiced_ratio": round(len(valid) / max(1, len(values)), 4),
              "pitch_min": round(float(np.min(valid)), 3) if len(valid) else None,
              "pitch_max": round(float(np.max(valid)), 3) if len(valid) else None,
              "pitch_median": round(float(np.median(valid)), 3) if len(valid) else None}
    result.update(extra or {})
    return result


def _note(syllable, start, end, key):
    note = {"lyric": syllable["lyric"], "pinyin": syllable["pinyin"], "tone": syllable["tone"],
            "start": round(start, 6), "end": round(end, 6), "key": max(0, min(127, int(round(key))))}
    note.update(language=syllable.get("language", "zh"), reading=syllable["pinyin"])
    for field in ("text_position", "text_end", "following", "source_text", "word_index", "word_reading",
                  "reading_source", "auto_reading", "pronunciation_override", "accent", "auto_accent",
                  "accent_override", "word_accent", "mora_kind", "mora_index", "word_mora_count",
                  "phonemes", "stress", "stress_override", "syllables", "syllable_count"):
        if field in syllable:
            note[field] = syllable[field]
    if syllable.get("pinyin_override") is not None:
        note.update(auto_pinyin=syllable["auto_pinyin"], pinyin_override=syllable["pinyin_override"])
    return note


def _phrase_break(syllable):
    return any(c in _PUNCTUATION or c in "\n\r" for c in syllable["following"])


def _speech_shape(tone, final):
    """Offsets around one common note, with the range carried by the F0 curve.

    VvTalk's VSQX examples use a constant note and roughly 13--16 semitones
    of pitch-bend range. These independent templates follow that representation;
    they are an editable Mandarin speech draft, rather than a TTS model.
    """
    shapes = {
        1: ([0, .25, .75, 1], [2.7, 2.9, 2.7, 2.5]),
        2: ([0, .20, .85, 1], [-5.4, -5.4, 1.6, 1.6]),
        4: ([0, .12, .35, .78, 1], [3.8, 4.2, 1.0, -8.5, -8.5]),
        5: ([0, .30, 1], [-2.0, -2.4, -4.0]),
    }
    if tone == 3:
        # A medial third tone stays low; a phrase-final one can make the full dip.
        return ([0, .12, .52, .64, .93, 1], [.4, .4, -10.2, -10.2, 1.8, 1.8]) if final else (
            [0, .15, .60, .80, 1], [-3.5, -3.5, -10.2, -10.2, -7.5])
    return shapes[tone]


def _speech_contours(syllables, timings, times, base):
    """Draw each tone, then join short note gaps without inventing unvoiced frames."""
    values = np.full(len(times), np.nan)
    def phrase_final(i):
        return (_phrase_break(syllables[i]) or i == len(syllables) - 1
                or timings[i + 1][0] - timings[i][1] > _MANUAL_JOIN_LIMIT)

    phrase_positions = []
    phrase_begin = 0
    for i, syllable in enumerate(syllables):
        if phrase_final(i):
            phrase_positions.extend((j - phrase_begin, i - phrase_begin) for j in range(phrase_begin, i + 1))
            phrase_begin = i + 1

    def contour(i, sample_times):
        syllable = syllables[i]
        start, end = timings[i]
        progress = np.clip((np.asarray(sample_times) - start) / (end - start), 0, 1)
        final = phrase_final(i)
        xp, fp = _speech_shape(syllable["tone"], final)
        phrase_index, phrase_last = phrase_positions[i]
        phrase_fall = -.8 * phrase_index / max(1, phrase_last)
        result = base + phrase_fall + np.interp(progress, xp, fp)
        if final:
            if "？" in syllable["following"] or "?" in syllable["following"]:
                result += 2.6 * progress ** 2
            else:
                result -= .45 * progress ** 3
        return result

    for i, (start, end) in enumerate(timings):
        mask = (times >= start) & (times <= end)
        values[mask] = contour(i, times[mask])

    for i in range(len(timings) - 1):
        left_start, left_end = timings[i]
        right_start, right_end = timings[i + 1]
        if _phrase_break(syllables[i]) or right_start - left_end > _MANUAL_JOIN_LIMIT:
            continue
        # Tone 1 gets 60 ms to enter/leave its plateau. Other tones keep their
        # core peaks/valleys and connect over shorter, continuous transitions.
        tail = .06 if syllables[i]["tone"] == 1 else .03
        head = .06 if syllables[i + 1]["tone"] == 1 else .02 if syllables[i + 1]["tone"] == 4 else .035
        join_start = left_end - min(tail, (left_end - left_start) * .25)
        join_end = right_start + min(head, (right_end - right_start) * .30)
        mask = (times >= join_start) & (times <= join_end)
        u = (times[mask] - join_start) / (join_end - join_start)
        ease = u * u * (3 - 2 * u)
        left_pitch = float(contour(i, join_start))
        right_pitch = float(contour(i + 1, join_end))
        values[mask] = left_pitch + (right_pitch - left_pitch) * ease
    return values


def _multilingual_contours(units, timings, times, base, language):
    """A dictionary-informed editable draft; no Mandarin tone templates."""
    values = np.full(len(times), np.nan)
    phrase_start = 0
    for i, (unit, (start, end)) in enumerate(zip(units, timings)):
        mask = (times >= start) & (times <= end)
        final = i == len(units) - 1 or _phrase_break(unit) or timings[i + 1][0] - end > _MANUAL_JOIN_LIMIT
        if language == "ja" and unit.get("mora_kind") == "geminate":
            if final:
                phrase_start = i + 1
            continue
        progress = np.clip((times[mask] - start) / (end - start), 0, 1)
        fall = -.10 * (i - phrase_start) if language == "ja" else -.18 * (i - phrase_start)
        if language == "ja":
            contour = np.full(len(progress), base + fall + (1.1 if unit["accent"] else -1.1))
        else:
            syllables = unit["syllables"] or [{"stress": 0, "weight": 1} for _ in range(unit["syllable_count"])]
            total = sum(s["weight"] for s in syllables)
            xp, fp, position = [0], [-.6], 0.0
            for syllable in syllables:
                width = syllable["weight"] / total
                xp.append(position + width * .52)
                fp.append({0: -.2, 1: 1.8, 2: .8}[syllable["stress"]])
                position += width
            xp.append(1)
            fp.append(-.7)
            contour = base + fall + np.interp(progress, xp, fp)
        if final:
            contour += (2.6 * progress ** 3 if "?" in unit["following"] or "？" in unit["following"]
                        else -.65 * progress ** 3)
            phrase_start = i + 1
        values[mask] = contour
    for i in range(len(units) - 1):
        left_end, right_start = timings[i][1], timings[i + 1][0]
        if _phrase_break(units[i]) or right_start - left_end > _MANUAL_JOIN_LIMIT:
            continue
        if language == "ja" and (units[i].get("mora_kind") == "geminate" or units[i + 1].get("mora_kind") == "geminate"):
            continue
        left = max(timings[i][0], left_end - .018)
        right = min(timings[i + 1][1], right_start + .018)
        li, ri = np.searchsorted(times, [left, right])
        if ri < len(times) and np.isfinite(values[li]) and np.isfinite(values[ri]):
            mask = (times >= left) & (times <= right)
            u = (times[mask] - left) / (right - left)
            values[mask] = values[li] + (values[ri] - values[li]) * (u * u * (3 - 2 * u))
    return values


def _text_analysis(payload, text, bpm, shift, scale, smoothing_ms):
    language = normalize_language(payload.get("language"))
    base = _number(payload, "base_pitch", 60, 12, 108)
    syllable_duration = _number(payload, "syllable_ms", 210, 80, 3000) / 1000
    pause = _number(payload, "pause_ms", 220, 0, 3000) / 1000
    syllables = text_units(text, language, payload.get("word_readings"))
    if language == "zh":
        _pinyin_overrides(syllables, payload)
    apply_unit_overrides(syllables, payload.get("unit_overrides"))
    if payload.get("alignment") is not None:
        timings, alignment_source, _ = _alignment(payload, syllables, np.array([]), np.array([]), 600)
        position = float(timings[-1][1])
        changes = _sandhi(syllables, timings) if language == "zh" else 0
    else:
        changes = _sandhi(syllables) if language == "zh" else 0
        alignment_source = "heuristic_text"
        timings, position = [], 0.0
        duration_factors = {1: 1.0, 2: 1.02, 3: 1.16, 4: .92, 5: .75}
        for i, syllable in enumerate(syllables):
            initial = i == 0 or _phrase_break(syllables[i - 1])
            final = i == len(syllables) - 1 or _phrase_break(syllable)
            emphasis = 1.1 if initial or final else 1.0
            if language == "zh":
                factor = duration_factors[syllable["tone"]]
            elif language == "ja":
                factor = {"geminate": .85, "nasal": 1.0, "long": 1.0, "regular": 1.0}[syllable["mora_kind"]]
            else:
                factor = sum(s["weight"] for s in syllable["syllables"]) or syllable["syllable_count"]
                if syllable["lyric"].lower() in ("a", "an", "the", "to", "of", "and", "is", "are", "in"):
                    factor *= .8
            start, end = position, position + syllable_duration * factor * emphasis
            timings.append((start, end))
            following = syllable["following"]
            multiplier = 2 if any(c in _SENTENCE_END for c in following) else 1 if any(c in _PUNCTUATION for c in following) else 0
            position = end + (pause * multiplier if multiplier else _TEXT_NOTE_GAP if not final else 0)
    step = _TEXT_FRAME_STEP
    times = np.arange(0, position, step)
    values = (_speech_contours(syllables, timings, times, base) if language == "zh" else
              _multilingual_contours(syllables, timings, times, base, language))
    values = _transform(values, shift, scale, smoothing_ms, step, center=base)
    notes = [_note(syllable, start, end, base + shift) for syllable, (start, end) in zip(syllables, timings)]
    output = {"mode": "text", "language": language, "text": text, "bpm": bpm, "notes": notes, "curve": _curve(times, values, position),
            "duration": round(position, 6), "warnings": ["文本模式采用声调模板与简化的三声、一、不变调规则；句法、重音、多音字和说话节奏需要手工复核。", "音符使用固定基准，语调由连续曲线承担；请用所选引擎的原生工程或精确音高脚本试听。"],
            "alignment_source": alignment_source, "stats": _stats(notes, values, {"sandhi_changes": changes,
            "pitch_method": "mandarin_speech_templates", "frame_step_seconds": step,
            "pipeline_version": "speech-v2", "note_pitch_mode": "fixed_baseline", "baseline_pitch": notes[0]["key"]})}
    if language != "zh":
        output["warnings"] = (["日语采用 UniDic 本地读音与词典アクセント、逐拍句调草稿；连读重音、音高和字典读音需复核。"]
                              if language == "ja" else ["英语采用 CMUdict 本地词内重音与简化句调；异读词、姓名和语境重音需复核。"])
        output["warnings"].append("自动文本语调可编辑，不保证母语朗读自然度；请使用对应语言声库试听。")
        if any(s["reading_source"] == "unknown" for s in syllables):
            output["warnings"].append("本地英语字典未收录：" + ", ".join(s["lyric"] for s in syllables if s["reading_source"] == "unknown")
                                      + "；保留原词并生成节奏草稿，请手动填写 ARPAbet 读音。")
        output["stats"]["pitch_method"] = "japanese_dictionary_accent" if language == "ja" else "english_dictionary_stress"
    if payload.get("word_readings") is not None:
        output["word_readings"] = dict(payload["word_readings"])
    return output


def _alignment(payload, syllables, times, values, duration):
    supplied = payload.get("alignment")
    if supplied is not None:
        if not isinstance(supplied, list) or len(supplied) != len(syllables):
            raise ValueError("对齐记录数必须与发音单元数一致；每个单元需要独立的 start/end。")
        output, previous_end = [], 0.0
        for i, (entry, syllable) in enumerate(zip(supplied, syllables)):
            if not isinstance(entry, dict) or entry.get("lyric") != syllable["lyric"]:
                raise ValueError(f"第 {i + 1} 条对齐歌词必须是“{syllable['lyric']}”。")
            try:
                start, end = float(entry["start"]), float(entry["end"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"第 {i + 1} 条对齐缺少有效 start/end。") from exc
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or start < previous_end - 1e-8 or end <= start or end > duration + 1e-6:
                raise ValueError(f"第 {i + 1} 条对齐时间无效：需有序、无重叠且位于录音时长内。")
            output.append((start, end))
            previous_end = end
        return output, "manual", []
    voiced = times[np.isfinite(values)]
    if len(voiced) == 0:
        raise ValueError("录音中未检出可靠的发声音高；请使用清晰的单人语音，或调整最低/最高基频。")
    begin, end = max(0.0, float(voiced[0]) - .005), min(duration, float(voiced[-1]) + .005)
    boundaries = np.linspace(begin, end, len(syllables) + 1)
    return list(zip(boundaries[:-1], boundaries[1:])), "equal_initial", ["没有提供逐字对齐：这里只按检测到的整体发声范围等分时间，不能视为自动语音对齐。请编辑逐字时间表或提供逐字 TextGrid 后复核。"]


def _reference_analysis(payload, text, bpm, shift, scale, smoothing_ms):
    audio_path = payload.get("audio_path")
    if not isinstance(audio_path, str) or not Path(audio_path).is_absolute() or not Path(audio_path).is_file():
        raise ValueError("reference 模式需要存在的绝对路径 audio_path。")
    fmin = _number(payload, "fmin", 75, 30, 1000)
    fmax = _number(payload, "fmax", 600, 60, 2500)
    if fmax <= fmin:
        raise ValueError("最高基频 fmax 必须高于最低基频 fmin。")
    pitch_mode = payload.get("pitch_mode", "absolute")
    if pitch_mode not in ("absolute", "relative"):
        raise ValueError("pitch_mode 必须是 absolute 或 relative。")
    base = _number(payload, "base_pitch", 60, 12, 108)
    try:
        sound = parselmouth.Sound(audio_path)
        if sound.n_channels > 1:
            sound = sound.convert_to_mono()
        duration = float(sound.duration)
        if duration > 1800:
            raise ValueError("单次最多处理 30 分钟录音。")
        if duration < 3 / fmin:
            raise ValueError("录音太短，无法进行基频分析。")
        step = .002
        pitch = sound.to_pitch_ac(time_step=step, pitch_floor=fmin, pitch_ceiling=fmax,
                                  silence_threshold=.03, voicing_threshold=.45)
    except parselmouth.PraatError as exc:
        raise ValueError(f"无法读取或分析录音：{exc}") from exc
    times = pitch.xs()
    frequency = pitch.selected_array["frequency"]
    values = np.full(len(frequency), np.nan)
    voiced = frequency > 0
    values[voiced] = 69 + 12 * np.log2(frequency[voiced] / 440)
    source_median = float(np.median(values[voiced])) if np.any(voiced) else None
    relative_shift = base - source_median if pitch_mode == "relative" and source_median is not None else 0
    values = _transform(values, shift + relative_shift, scale, smoothing_ms, step, center=source_median)
    language = normalize_language(payload.get("language"))
    syllables = text_units(text, language, payload.get("word_readings"))
    apply_unit_overrides(syllables, payload.get("unit_overrides"))
    timings, source, warnings = _alignment(payload, syllables, times, values, duration)
    global_valid = values[np.isfinite(values)]
    fallback = float(np.median(global_valid)) if len(global_valid) else base + shift
    notes, empty_lyrics = [], []
    for syllable, (start, end) in zip(syllables, timings):
        segment = values[(times >= start) & (times < end)]
        valid = segment[np.isfinite(segment)]
        if not len(valid):
            empty_lyrics.append(syllable["lyric"])
        notes.append(_note(syllable, start, end, base + shift if pitch_mode == "relative" else fallback))
    if empty_lyrics:
        warnings.append(f"这些字的区间没有可靠 F0，请复核录音和逐字时间：{''.join(empty_lyrics)}。")
    warnings.extend(["清音和静音保留为空值；伴奏、多人声和噪音可能造成倍频或半频错误，需复核。", "录音起点和停顿保留在原时间轴；请打开原生 ACEP 工程试听，并复核清音段的发音。"])
    output = {"mode": "reference", "language": language, "text": text, "bpm": bpm, "notes": notes,
            "pitch_mode": pitch_mode, "reference_source_median": round(source_median, 6) if source_median is not None else None,
            "curve": _curve(times, values, duration), "duration": round(duration, 6), "warnings": warnings,
            "alignment_source": source, "stats": _stats(notes, values, {"pitch_method": "praat_autocorrelation",
            "frame_step_seconds": step, "fmin_hz": fmin, "fmax_hz": fmax,
            "pipeline_version": "speech-v2", "note_pitch_mode": "fixed_baseline", "baseline_pitch": notes[0]["key"]})}
    if payload.get("word_readings") is not None:
        output["word_readings"] = dict(payload["word_readings"])
    return output


def analyze(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("请求必须是 JSON 对象。")
    text = payload.get("text", "")
    language = normalize_language(payload.get("language"))
    if language == "zh":
        _characters(text)
    else:
        text_units(text, language, payload.get("word_readings"))
    mode = payload.get("mode", "text")
    bpm = _number(payload, "bpm", 120, 20, 400)
    shift = _number(payload, "shift_semitones", 0, -48, 48)
    scale = _number(payload, "range_scale", 1, 0, 4)
    smoothing = _number(payload, "smoothing_ms", 10, 0, 500)
    if mode == "text":
        return _text_analysis(payload, text, bpm, shift, scale, smoothing)
    if mode == "reference":
        if payload.get("pinyin_overrides") is not None:
            raise ValueError("手动拼音目前仅支持文本和长文本工作台模式。")
        return _reference_analysis(payload, text, bpm, shift, scale, smoothing)
    raise ValueError("mode 必须是 text 或 reference。")


def build_ufdata(result: dict) -> dict:
    """UFData uses PPQN 480. The pitch values are absolute MIDI semitones."""
    bpm = _number(result, "bpm", 120, 20, 400)
    tick_rate = bpm * 480 / 60
    notes, previous_off, previous_end = [], 0, 0.0
    for i, note in enumerate(result.get("notes", [])):
        start, end = float(note["start"]), float(note["end"])
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or start < previous_end - 1e-8:
            raise ValueError("导出音符时间无效。")
        tick_on = round(start * tick_rate)
        tick_off = max(tick_on + 1, round(end * tick_rate))
        if tick_on < previous_off:
            raise ValueError("导出音符重叠；请先调整逐字时间。")
        key = int(note["key"])
        if not 0 <= key <= 127:
            raise ValueError("导出音符音高需在 MIDI 0 至 127 之间。")
        notes.append({"key": key, "lyric": str(note["lyric"]), "tickOn": tick_on, "tickOff": tick_off,
                      "ace_lang": "CHN"})
        previous_off = tick_off
        previous_end = end
    pitch_by_tick = {}
    for point in result.get("curve", []):
        time = float(point["time"])
        value = point.get("pitch")
        if not math.isfinite(time) or time < 0 or (value is not None and not math.isfinite(float(value))):
            raise ValueError("导出音高曲线含有无效值。")
        pitch_by_tick[round(time * tick_rate)] = None if value is None else float(value)
    ticks = sorted(pitch_by_tick)
    return {"formatVersion": 1, "project": {"name": "ACE 语调草稿", "measurePrefix": 0,
            "tracks": [{"name": "中文语调", "notes": notes,
                        "pitch": {"ticks": ticks, "values": [pitch_by_tick[tick] for tick in ticks], "isAbsolute": True}}],
            "timeSignatures": [{"measurePosition": 0, "numerator": 4, "denominator": 4}],
            "tempos": [{"tickPosition": 0, "bpm": bpm}]}}
