"""Validate editable readings; read ACE dictionaries without changing projects."""

from __future__ import annotations

import json
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from pypinyin.constants import PINYIN_DICT
from pypinyin.contrib.tone_convert import to_normal


ACE_CLI = r"C:\Program Files\ACE Studio\acestudio-cli.exe"
_PINYIN = re.compile(r"^[a-zv]{1,7}[1-5]$")
_VALID_BASES = frozenset(to_normal(reading, v_to_u=False).lower().replace("ü", "v")
                         for readings in PINYIN_DICT.values() for reading in readings.split(","))
_PHONE = re.compile(r"^[A-Za-z0-9_+\-]+$")
ACE_LANGUAGE_NAMES = {"zh": "Chinese", "ja": "Japanese", "en": "English"}
ACE_LANGUAGE_CODES = {"zh": "CHN", "ja": "JPN", "en": "ENG"}


@lru_cache(maxsize=1)
def _ace_snapshot():
    """Use the bundled, read-only verified dictionary snapshot while ACE is closed."""
    candidates = [Path(__file__).with_name("ace_language_cache.json"),
                  Path(__file__).parent / "core" / "ace_language_cache.json"]
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError("ACE 离线语言缓存损坏，请重新安装完整程序。") from exc
            if isinstance(data, dict) and data.get("schema") == 1:
                return data
    raise ValueError("缺少 ACE 离线语言缓存，请使用包含 core/ace_language_cache.json 的完整程序。")


def normalize_pinyin_override(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("手动拼音必须为空值或带声调数字的拼音，如 chong2、hang2、lv4。")
    normalized = value.strip().lower().replace("ü", "v")
    if not _PINYIN.fullmatch(normalized) or normalized[:-1] not in _VALID_BASES:
        raise ValueError(f"手动拼音“{value[:40]}”无效；请填写一个有效音节和 1–5 的声调数字，如 chong2、lv4。")
    return normalized


def ace_read(arguments, message):
    """Only read-only CLI commands are used by this module."""
    try:
        completed = subprocess.run([ACE_CLI, "--json", *arguments], capture_output=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   timeout=15, check=False, shell=False,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(message) from exc
    if completed.returncode != 0:
        raise ValueError(message)
    try:
        response = json.loads(completed.stdout.lstrip("\ufeff"))
    except (ValueError, AttributeError) as exc:
        raise ValueError("ACE 只读接口返回了无效 JSON，未生成工程。") from exc
    if not isinstance(response, dict):
        raise ValueError("ACE 只读接口返回了无效数据，未生成工程。")
    return response


def _resolved_syllable(response, reading):
    syllables = response.get("syllables") if isinstance(response, dict) else None
    if not isinstance(syllables, list) or len(syllables) != 1 or not isinstance(syllables[0], dict):
        raise ValueError("ACE 发音字典未返回一个有效音节，未写入发音。")
    syllable = syllables[0]
    phones = syllable.get("phonemes")
    if syllable.get("resolved") is not True or not isinstance(phones, list) or not phones or not all(
            isinstance(phone, str) and _PHONE.fullmatch(phone) for phone in phones):
        raise ValueError(f"ACE 发音字典无法解析“{reading}”；请改用该语言支持的读音。")
    return " ".join(phones)


@lru_cache(maxsize=512)
def ace_syllable_for_pinyin(value):
    """Keep the original Chinese export contract and CLI argument spelling."""
    normalized = normalize_pinyin_override(value)
    if normalized is None:
        raise ValueError("ACE 发音解析需要手动拼音。")
    message = (f"手动拼音“{normalized}”的 ACEP 导出需要连接 ACE Studio 的发音字典；"
               "请确认 ACE Studio 已运行并启用外部代理访问。分析和 JSON 保存仍可离线使用。")
    response = ace_read(["phoneme", "g2p", "--language", "Chinese", "--grapheme", normalized], message)
    return _resolved_syllable(response, normalized)


@lru_cache(maxsize=512)
def ace_syllable_for_reading(value, language):
    from languages import normalize_language, normalize_pronunciation_override
    language = normalize_language(language)
    if language == "zh":
        return ace_syllable_for_pinyin(value)
    if language != "ja":
        raise ValueError("英语原生发音应按音节提供 ARPAbet，而不是将整词当成单个音节。")
    reading = normalize_pronunciation_override(value, language)
    if reading is None:
        raise ValueError("日语 ACE 导出需要有效的假名拍。")
    syllable = _ace_snapshot().get("japanese_moras", {}).get(reading)
    if not isinstance(syllable, str) or not syllable or not all(_PHONE.fullmatch(p) for p in syllable.split()):
        raise ValueError(f"日语假名拍“{reading}”不在已验证的 ACE 离线发音字典中；请改用兼容的假名读音。")
    return syllable


@lru_cache(maxsize=3)
def ace_inventory(language):
    response = _ace_snapshot().get("inventories", {}).get(language, {})
    consonants, vowels = response.get("consonants"), response.get("vowels")
    if not isinstance(consonants, list) or not isinstance(vowels, list) or not vowels:
        raise ValueError("ACE 的语言音素表尚未就绪，未写入发音。")
    return frozenset(consonants), frozenset(vowels)


def ace_english_syllable(phonemes):
    """Stress belongs to the source prosody; ACE's native symbols omit digits."""
    if not isinstance(phonemes, list) or not phonemes:
        raise ValueError("英语 ACEP 导出需要可解析的音节音素。")
    phones = [re.sub(r"[012]$", "", str(phone)).lower() for phone in phonemes]
    consonants, vowels = ace_inventory("en")
    if any(phone not in consonants | vowels for phone in phones):
        raise ValueError("英语读音包含 ACE 当前音素表不支持的符号；未写入发音。")
    vowel_positions = [index for index, phone in enumerate(phones) if phone in vowels]
    if not vowel_positions or any(phone not in vowels for phone in phones[vowel_positions[0]:vowel_positions[-1] + 1]):
        raise ValueError("ACE 每个音符需要一个连续元音段；请将英语多音节词拆为音节。")
    return " ".join(phones)


@lru_cache(maxsize=3)
def ace_voice_for_language(language):
    """Return the compatible native voice verified when the offline cache was made."""
    from languages import normalize_language
    language = normalize_language(language)
    voice = _ace_snapshot().get("voices", {}).get(language)
    if (not isinstance(voice, dict) or not re.fullmatch(r"singer:\d+", str(voice.get("ref", ""))) or
            isinstance(voice.get("id"), bool) or not isinstance(voice.get("id"), int) or
            voice.get("ref") != "singer:" + str(voice["id"]) or
            isinstance(voice.get("seed_code"), bool) or not isinstance(voice.get("seed_code"), int) or
            voice["seed_code"] < 0 or
            voice.get("seed_ref") != "seed:" + str(voice["seed_code"])):
        raise ValueError(f"缺少 {ACE_LANGUAGE_NAMES[language]} ACE 离线兼容声库信息，请更新完整程序。")
    return dict(voice)


def inspect_ace_voice_for_language(language):
    """Optional read-only refresh; exporting does not call the running editor."""
    from languages import normalize_language
    language = normalize_language(language)
    name = ACE_LANGUAGE_NAMES[language]
    message = f"{name} ACEP 导出需要读取本机可用声库；请启动 ACE Studio 并开启外部代理访问。"
    models = ace_read(["voice", "synth-models"], message).get("models", [])
    models = [model for model in models if isinstance(model, dict) and not model.get("timbreOnly")
              and name in model.get("supportedLanguages", [])]
    models.sort(key=lambda model: ({13: 0, 12: 1, 1: 2}.get(model.get("id"), 3), model.get("id", 0)))
    for model in models:
        seeds = ace_read(["voice", "seeds", "--model", model["name"], "--community", "true"], message).get("seeds", [])
        response = ace_read(["sound-source", "list", "--kind", "voice", "--origin", "premade",
                             "--model", model["name"], "--language", name], message)
        for source in response.get("soundSources", []):
            if (isinstance(source, dict) and source.get("nativeLanguage") == name and
                    name in source.get("supportedLanguages", []) and
                    re.fullmatch(r"singer:\d+", str(source.get("ref", "")))):
                candidates = [seed for seed in seeds if seed.get("name") == source["name"]]
                if len(candidates) != 1:
                    continue
                seed = candidates[0]
                return {"id": int(source["id"]), "ref": source["ref"], "name": source["name"],
                        "seed_code": int(seed["code"]), "seed_ref": seed["ref"],
                        "model_id": int(model["id"]), "model_name": model["name"],
                        "native_language": name, "supported_languages": model["supportedLanguages"]}
    raise ValueError(f"未找到支持 {name} 的本机原生声库与模型；请在 ACE 中添加兼容声库。")
