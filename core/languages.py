"""Local reading dictionaries and editable units; no network or acoustic model."""
from __future__ import annotations

import re
import threading
import unicodedata
from functools import lru_cache

from pypinyin import Style, lazy_pinyin

_HAN_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_EN_WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
_PUNCT = set("，。！？；：、,.!?;:…—-（）()【】[]《》〈〉“”‘’\"'·")
_SMALL = set("ゃゅょぁぃぅぇぉゎ")
_VOWELS = set("AA AE AH AO AW AY EH ER EY IH IY OW OY UH UW".split())
_CONSONANTS = set("B CH D DH F G HH JH K L M N NG P R S SH T TH V W Y Z ZH".split())
_JA_LOCK = threading.Lock()
NOTE_METADATA_FIELDS = ("language", "reading", "pinyin", "tone", "text_position", "text_end", "following",
                        "source_text", "word_index", "word_reading", "reading_source", "auto_reading",
                        "pronunciation_override", "accent", "auto_accent", "accent_override", "word_accent",
                        "mora_kind", "mora_index", "word_mora_count", "phonemes", "stress", "stress_override",
                        "syllables", "syllable_count")


def normalize_language(value=None):
    if value is None:
        return "zh"
    if not isinstance(value, str) or value not in ("zh", "ja", "en"):
        raise ValueError("language 必须是 zh、ja 或 en。")
    return value


def _hiragana(value):
    value = unicodedata.normalize("NFKC", value)
    return "".join(chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char for char in value)


def japanese_moras(reading):
    """Long vowels, nasal and geminate each occupy a mora; small kana join."""
    if not isinstance(reading, str) or not reading.strip():
        raise ValueError("日语读音需要非空的平假名或片假名。")
    reading = _hiragana(reading.strip())
    if any(not ("ぁ" <= c <= "ゖ" or c == "ー") for c in reading):
        raise ValueError("日语读音只接受假名和长音符号，不接受汉字或罗马字。")
    output = []
    for char in reading:
        if char in _SMALL:
            if not output or output[-1] in ("っ", "ん", "ー"):
                raise ValueError("拗音或小假名必须接在前一假名之后。")
            output[-1] += char
        else:
            output.append(char)
    return output


def normalize_pronunciation_override(value, language="zh"):
    language = normalize_language(language)
    if value is None:
        return None
    if language == "zh":
        # pronunciation imports this module for non-Chinese host metadata.
        from pronunciation import normalize_pinyin_override
        return normalize_pinyin_override(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("手动读音需要非空文本；自动读音请使用 null。")
    if language == "ja":
        moras = japanese_moras(value)
        if len(moras) != 1:
            raise ValueError("逐拍读音只能填写一拍；改整词读音请使用 word_readings。")
        return moras[0]
    phones = value.strip().upper().split()
    if len(phones) > 80 or not any(p[:-1] in _VOWELS and p[-1:] in ("0", "1", "2") for p in phones):
        raise ValueError("英语读音需使用带 0/1/2 重音的 ARPAbet，如 HH AH0 L OW1。")
    if any(p not in _CONSONANTS and not (p[:-1] in _VOWELS and p[-1:] in ("0", "1", "2")) for p in phones):
        raise ValueError("英语读音含无效 ARPAbet 音素；每个元音需带 0、1 或 2。")
    return " ".join(phones)


def english_syllables(phones):
    """Split at vowel nuclei, keeping a final consonant as the next onset."""
    nuclei = [i for i, phone in enumerate(phones) if phone[:-1] in _VOWELS]
    if not nuclei:
        return []
    # shortcut: onset allocation is a draft, not a full English syllabifier.
    boundaries = [0] + [max(left + 1, right - 1) for left, right in zip(nuclei, nuclei[1:])] + [len(phones)]
    return [{"phonemes": phones[start:end], "stress": int(phones[nucleus][-1]),
             "weight": {0: .9, 1: 1.25, 2: 1.05}[int(phones[nucleus][-1])]}
            for start, end, nucleus in zip(boundaries, boundaries[1:], nuclei)]


@lru_cache(maxsize=1)
def _english_dictionary():
    try:
        import cmudict
    except ImportError as exc:
        raise ValueError("未安装本地 CMUdict 英语读音字典。") from exc
    return cmudict.dict()


@lru_cache(maxsize=1)
def _japanese_tagger():
    try:
        import fugashi
        import unidic_lite
    except ImportError as exc:
        raise ValueError("未安装本地 fugashi / UniDic 日语读音字典。") from exc
    return fugashi.Tagger(f'-d "{unidic_lite.DICDIR}" -r "{unidic_lite.DICDIR}/mecabrc"')


def _chinese_units(text):
    output = []
    for match in _HAN_RUN.finditer(text):
        readings = lazy_pinyin(match.group(), style=Style.TONE3, neutral_tone_with_five=True,
                               errors=lambda value: list(value))
        for offset, (char, reading) in enumerate(zip(match.group(), readings)):
            tone = int(reading[-1]) if reading and reading[-1:] in "12345" else 5
            output.append({"lyric": char, "pinyin": reading, "reading": reading, "tone": tone,
                           "original_tone": tone, "language": "zh", "text_position": match.start() + offset,
                           "text_end": match.start() + offset + 1, "reading_source": "pypinyin"})
    return output


def _english_units(text):
    dictionary = _english_dictionary()
    output = []
    for match in _EN_WORD.finditer(text):
        word = match.group()
        alternatives = dictionary.get(word.lower().replace("’", "'"))
        phones = list(alternatives[0]) if alternatives else []
        syllables = english_syllables(phones)
        output.append({"lyric": word, "source_text": word, "reading": " ".join(phones) if phones else word,
                       "pinyin": " ".join(phones) if phones else word, "phonemes": phones,
                       "syllables": syllables, "stress": [s["stress"] for s in syllables],
                       "syllable_count": len(syllables) or max(1, len(re.findall(r"[aeiouy]+", word.lower()))),
                       "reading_source": "cmudict" if phones else "unknown",
                       "language": "en", "tone": 0, "original_tone": 0,
                       "text_position": match.start(), "text_end": match.end()})
    return output


def _long_vowel(previous):
    endings = {"あ": "あかがさざただなはばぱまゃやらゎわぁ", "い": "いきぎしじちぢにひびぴみりぃ",
               "う": "うくぐすずつづぬふぶぷむゅゆるゔぅ", "え": "えけげせぜてでねへべぺめれぇ",
               "お": "おこごそぞとどのほぼぽもょよろをぉ"}
    return next((vowel for vowel, chars in endings.items() if previous[-1:] in chars), None)


def _japanese_units(text, word_readings):
    if word_readings is not None and not isinstance(word_readings, dict):
        raise ValueError("word_readings 必须按原文字起点索引提供整词假名读音。")
    overrides = word_readings or {}
    used, output, cursor, word_index = set(), [], 0, 0
    with _JA_LOCK:
        for token in _japanese_tagger()(text):
            surface = token.surface
            position = text.find(surface, cursor)
            if position < 0:
                raise ValueError("日语分词与原文位置不一致。")
            cursor = position + len(surface)
            if all(c in _PUNCT or c.isspace() for c in surface):
                continue
            supplied = overrides.get(str(position), overrides.get(position))
            if supplied is not None and (not isinstance(supplied, str) or not supplied.strip()):
                raise ValueError("word_readings 的每项必须是非空假名读音。")
            feature = token.feature
            reading = supplied or getattr(feature, "pron", None) or getattr(feature, "kana", None)
            if not reading or reading == "*":
                if all("ぁ" <= c <= "ヿ" or c == "ー" for c in surface):
                    reading = surface
                else:
                    raise ValueError(f"本地日语字典没有“{surface}”的读音，请通过 word_readings 提供假名。")
            if supplied is not None:
                used.add(str(position))
            moras = japanese_moras(reading)
            accent_text = str(getattr(feature, "aType", ""))
            accent = int(accent_text.split(",")[0]) if re.match(r"^\d+", accent_text) and supplied is None else None
            if accent is not None:
                accent = min(accent, len(moras))
            for i, mora in enumerate(moras):
                kind = "long" if mora == "ー" else "geminate" if mora == "っ" else "nasal" if mora == "ん" else "regular"
                actual = _long_vowel(output[-1]["reading"]) if kind == "long" and i else mora
                if kind == "long" and not i:
                    actual = None
                if not actual:
                    raise ValueError("长音符号之前需要可确定母音的假名。")
                level = int(i == 0 if accent == 1 else i > 0 and (not accent or i < accent))
                output.append({"lyric": mora, "source_text": surface, "reading": actual, "pinyin": actual,
                               "word_reading": _hiragana(reading), "word_index": word_index,
                               "mora_index": i, "word_mora_count": len(moras), "mora_kind": kind,
                               "word_accent": accent, "accent": level, "auto_accent": level,
                               "reading_source": "manual_word" if supplied is not None else "unidic",
                               "language": "ja", "tone": 0, "original_tone": 0,
                               "text_position": position, "text_end": cursor})
            word_index += 1
    if set(map(str, overrides)) - used:
        raise ValueError("word_readings 的索引没有对应到日语词语起点。")
    return output


def text_units(text, language="zh", word_readings=None):
    language = normalize_language(language)
    if word_readings is not None and language != "ja":
        raise ValueError("word_readings 仅用于日语整词读音。")
    if not isinstance(text, str) or not text.strip() or len(text) > 20000:
        raise ValueError("请输入 1–20000 字符的文本。")
    if language == "en":
        invalid = re.sub(_EN_WORD, "", text)
        if any(c not in _PUNCT and not c.isspace() for c in invalid):
            raise ValueError("英语文本只支持英文字词和标点，请先展开数字或切换语言。")
        output = _english_units(text)
    elif language == "ja":
        if any(not (c in _PUNCT or c in "々〆" or c.isspace() or "ぁ" <= c <= "ヿ" or "\u3400" <= c <= "\u9fff"
                    or "\uff66" <= c <= "\uff9f" or c.isdigit()) for c in text):
            raise ValueError("日语文本只支持日语汉字、假名、数字和标点。")
        output = _japanese_units(text, word_readings)
    else:
        if any(not (_HAN_RUN.fullmatch(c) or c in _PUNCT or c.isspace()) for c in text):
            raise ValueError("中文文本只支持中文和标点。")
        output = _chinese_units(text)
    if not output:
        raise ValueError("文本至少需要一个可发音单元。")
    for i, unit in enumerate(output):
        next_start = output[i + 1]["text_position"] if i + 1 < len(output) else len(text)
        unit["following"] = text[unit["text_end"]:next_start] if next_start >= unit["text_end"] else ""
    return output


def apply_unit_overrides(units, supplied):
    if supplied is None:
        return
    if not isinstance(supplied, list) or len(supplied) != len(units):
        raise ValueError("unit_overrides 必须与发音单元数量一致。")
    for index, (unit, entry) in enumerate(zip(units, supplied)):
        if not isinstance(entry, dict):
            raise ValueError("unit_overrides 中每项必须是对象。")
        language = unit["language"]
        if entry.get("language") is not None and normalize_language(entry["language"]) != language:
            raise ValueError("逐单元覆盖的 language 与文本语言不一致。")
        if language == "zh" and entry.get("pronunciation_override") is not None:
            raise ValueError("中文手动读音请使用 pinyin_override。")
        reading = normalize_pronunciation_override(entry.get("pronunciation_override"), language)
        unit["auto_reading"] = unit["reading"]
        if reading is not None:
            unit.update(pronunciation_override=reading, reading=reading, pinyin=reading)
            unit["reading_source"] = "manual"
        accent = entry.get("accent_override")
        stress = entry.get("stress_override")
        if language == "ja":
            if reading is not None:
                kind = "long" if reading == "ー" else "geminate" if reading == "っ" else "nasal" if reading == "ん" else "regular"
                unit["mora_kind"] = kind
                if kind == "long":
                    previous = units[index - 1] if index else None
                    actual = _long_vowel(previous["reading"]) if previous else None
                    if actual is None:
                        raise ValueError("手动长音之前需要可确定母音的假名。")
                    unit.update(reading=actual, pinyin=actual)
            if stress is not None:
                raise ValueError("日语逐拍使用 accent_override，不使用英语 stress_override。")
            if accent is not None:
                if isinstance(accent, bool) or not isinstance(accent, int) or accent not in (0, 1):
                    raise ValueError("日语 accent_override 必须为空值、0（低）或 1（高）。")
                unit.update(accent_override=accent, accent=accent)
        elif language == "en":
            if accent is not None:
                raise ValueError("英语使用 stress_override，不使用日语 accent_override。")
            phones = reading.split() if reading is not None else list(unit["phonemes"])
            nuclei = [i for i, p in enumerate(phones) if p[:-1] in _VOWELS]
            if stress is not None:
                if not isinstance(stress, list) or not nuclei or len(stress) != len(nuclei) or any(
                        isinstance(x, bool) or not isinstance(x, int) or x not in (0, 1, 2) for x in stress):
                    raise ValueError("stress_override 必须逐音节提供 0/1/2，数量与有效读音的元音数一致。")
                for i, value in zip(nuclei, stress):
                    phones[i] = phones[i][:-1] + str(value)
                unit["stress_override"] = list(stress)
            unit.update(phonemes=phones, syllables=english_syllables(phones),
                        stress=[int(phones[i][-1]) for i in nuclei],
                        syllable_count=len(nuclei) or unit["syllable_count"])
            if phones:
                unit.update(reading=" ".join(phones), pinyin=" ".join(phones))
        elif accent is not None or stress is not None:
            raise ValueError("中文使用拼音声调，不使用日英重音覆盖。")


def rebuild_note_metadata(result):
    """Rebuild Japanese/English reading edits without changing reference F0 or timing."""
    language = normalize_language(result.get("language"))
    notes = result.get("notes")
    if not isinstance(notes, list):
        raise ValueError("需要有效 notes 才能重建读音。")
    if language == "zh":
        # Mandarin sandhi and pinyin overrides remain with the existing engine.
        return [{} for _ in notes]
    units = text_units(result.get("text"), language, result.get("word_readings"))
    if len(units) != len(notes) or any(unit["lyric"] != note.get("lyric") for unit, note in zip(units, notes)):
        raise ValueError("工程歌词与原文的发音单元不一致，无法重建日英读音。")
    apply_unit_overrides(units, notes)
    return [{**{key: unit[key] for key in NOTE_METADATA_FIELDS if key in unit},
             **{key: unit.get(key) for key in ("pronunciation_override", "accent_override", "stress_override")}}
            for unit in units]
