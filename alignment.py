"""Invoke the user's existing MFA installation in an isolated job directory."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import uuid
import zipfile
from pathlib import Path

import parselmouth
from praatio import textgrid
from pypinyin import Style, lazy_pinyin
from languages import normalize_language, text_units, apply_unit_overrides

_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_MAX_SECONDS = 180
_MAX_CHARACTERS = 2000


def detect_alignment(language='zh'):
    language = normalize_language(language)
    source = Path(os.environ.get("VVTALK_SOURCE", str(Path.home() / "Documents/Vocaloid/VvTalk_1.0.1"))).expanduser().resolve()
    environment = source / "misc/src/MiniConda/envs/vvTalkEnv"
    paths = {"python": environment / "python.exe", "script": environment / "Scripts/mfa-script.py",
             "dictionary": source / "misc/mfa/mfa_model_v20.dict", "model": source / "misc/mfa/mandarin_mfa.zip"}
    if language != 'zh':
        prefix = 'VVTALK_MFA_' + language.upper()
        paths['dictionary'] = Path(os.environ.get(prefix + '_DICTIONARY', str(source / 'misc/mfa' / (language + '.dict')))).expanduser().resolve()
        paths['model'] = Path(os.environ.get(prefix + '_MODEL', str(source / 'misc/mfa' / (language + '.zip')))).expanduser().resolve()
    missing = [name for name, path in paths.items() if not path.is_file()]
    if not missing:
        try:
            with zipfile.ZipFile(paths["model"]) as archive:
                if not archive.namelist():
                    missing.append("model-content")
        except (OSError, zipfile.BadZipFile):
            missing.append("model-archive")
    names = {'zh': '普通话', 'ja': '日语逐拍', 'en': '英语逐词'}
    message = (f"发现本机 MFA 与{names[language]}资源；自动对齐将在独立工作目录运行。" if not missing else
               "未找到完整的 VvTalk MFA 安装；请用 VVTALK_SOURCE 指向已有 VvTalk_1.0.1 目录，或上传逐字 CSV/TextGrid。")
    if missing and language != 'zh':
        message = f"未配置{names[language]} MFA 资源；请上传{'逐拍' if language == 'ja' else '逐词'} CSV/TextGrid，或明确选择均分草稿。"
    return {"available": not missing, "language": language, "source": str(source), "environment": str(environment),
            **{key: str(value) for key, value in paths.items()}, "missing": missing,
            "method": "mfa-local", "message": message}


def language_tokens(text, dictionary, language, word_readings=None, unit_overrides=None):
    if language == 'zh':
        if word_readings is not None or unit_overrides is not None:
            raise ValueError('普通话自动对齐使用原文拼音，请在提取后编辑读音。')
        return pinyin_tokens(text, dictionary)
    units = text_units(text, language, word_readings)
    if unit_overrides is not None:
        apply_unit_overrides(units, unit_overrides)
    if not 1 <= len(units) <= _MAX_CHARACTERS:
        raise ValueError(f'自动对齐需要 1 至 {_MAX_CHARACTERS} 个调教单位。')
    with Path(dictionary).open('r', encoding='utf-8-sig') as stream:
        vocabulary = {line.split()[0].casefold(): line.split()[0] for line in stream if line.strip() and not line.startswith('#')}
    tokens = [unit['reading'] if language == 'ja' else unit['lyric'].replace('’', "'") for unit in units]
    unknown = [token for token in tokens if token.casefold() not in vocabulary]
    if unknown:
        raise ValueError('对应语言的 MFA 字典缺少这些调教单位：' + '、'.join(dict.fromkeys(unknown)) + '。请上传人工 CSV/TextGrid。日语自动对齐需要与逐拍读音匹配的字典。')
    return [unit['lyric'] for unit in units], [vocabulary[token.casefold()] for token in tokens]


def pinyin_tokens(text, dictionary):
    if not isinstance(text, str):
        raise ValueError("自动对齐需要中文台词。")
    characters = _HAN.findall(text)
    if not 1 <= len(characters) <= _MAX_CHARACTERS:
        raise ValueError(f"自动对齐需要 1 至 {_MAX_CHARACTERS} 个汉字。")
    # Joining characters keeps phrase readings; punctuation never becomes a word.
    tokens = lazy_pinyin("".join(characters), style=Style.TONE3, neutral_tone_with_five=True,
                         errors=lambda value: list(value))
    tokens = [token.lower().replace("ü", "v") for token in tokens]
    if len(tokens) != len(characters):
        raise ValueError("无法建立一字一音节的拼音台词。")
    with Path(dictionary).open("r", encoding="utf-8-sig") as stream:
        vocabulary = {line.split()[0] for line in stream if line.strip() and not line.startswith("#")}
    unknown = [token for token in tokens if token not in vocabulary]
    if unknown:
        raise ValueError("本机 MFA 字典不含这些读音：" + "、".join(dict.fromkeys(unknown)) + "。请上传人工逐字 CSV/TextGrid。")
    return characters, tokens


def read_word_intervals(path, characters, tokens, duration):
    try:
        grid = textgrid.openTextgrid(str(path), includeEmptyIntervals=True)
    except Exception as error:
        raise ValueError("MFA 输出的 TextGrid 无法读取。") from error
    word_tiers = [name for name in grid.tierNames if name.lower() == "words" or name.lower().endswith(" - words")]
    if len(word_tiers) != 1:
        raise ValueError("MFA 输出缺少唯一的 words 字层，未进行时间均分。")
    entries = [(float(start), float(end), str(label).strip())
               for start, end, label in grid.getTier(word_tiers[0]).entries if str(label).strip()]
    if len(entries) != len(characters):
        raise ValueError(f"MFA 对齐得到 {len(entries)} 个字，台词有 {len(characters)} 个字；请检查台词与录音或上传标注，未进行时间均分。")
    intervals, previous_end = [], 0.0
    for char, token, (start, end, label) in zip(characters, tokens, entries):
        if label != token or not math.isfinite(start) or not math.isfinite(end) or start < previous_end - 1e-7 or start < 0 or end <= start or end > duration + 1e-4:
            raise ValueError("MFA 输出的读音或时间顺序与台词不一致；请复核台词或上传标注，未进行时间均分。")
        intervals.append({"lyric": char, "start": round(start, 6), "end": round(end, 6)})
        previous_end = end
    return intervals


def align_audio(audio: Path, text: str, workdir: Path, language='zh', word_readings=None, unit_overrides=None) -> list[dict]:
    language = normalize_language(language)
    configuration = detect_alignment(language)
    if not configuration["available"]:
        raise ValueError(configuration["message"])
    audio = Path(audio).resolve()
    if not audio.is_file():
        raise ValueError("需要已上传的本地音频。")
    characters, tokens = language_tokens(text, configuration["dictionary"], language, word_readings, unit_overrides)
    try:
        sound = parselmouth.Sound(str(audio))
        duration = float(sound.duration)
        if not .1 <= duration <= _MAX_SECONDS:
            raise ValueError(f"自动对齐一次支持 0.1 至 {_MAX_SECONDS} 秒录音，请先分段。")
        if sound.n_channels > 1:
            sound = sound.convert_to_mono()
        sound = sound.resample(16000)
    except parselmouth.PraatError as error:
        raise ValueError("录音无法解码为 MFA 的 16 kHz 单声道输入。") from error
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    job = workdir / ("mfa-" + uuid.uuid4().hex[:12])
    corpus, output, temporary, data = (job / name for name in ("corpus", "output", "temporary", "mfa-data"))
    for directory in (corpus, output, temporary, data):
        directory.mkdir(parents=True)
    sound.save(str(corpus / "speech.wav"), parselmouth.SoundFileFormat.WAV)
    (corpus / "speech.lab").write_text(" ".join(tokens), encoding="utf-8")
    environment = Path(configuration["environment"])
    child_environment = dict(os.environ)
    dll_paths = [environment, environment / "Library/bin", environment / "Library/usr/bin", environment / "Scripts"]
    child_environment["PATH"] = os.pathsep.join(map(str, dll_paths)) + os.pathsep + child_environment.get("PATH", "")
    child_environment.update(MFA_ROOT_DIR=str(data), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    arguments = [configuration["python"], configuration["script"], "align", str(corpus), configuration["dictionary"],
                 configuration["model"], str(output), "-t", str(temporary), "--disable_mp", "-j", "1"]
    log_path = job / "mfa.log"
    try:
        with log_path.open("w", encoding="utf-8") as stream:
            completed = subprocess.run(arguments, cwd=job, env=child_environment, stdout=stream, stderr=subprocess.STDOUT,
                                       timeout=240, shell=False, check=False,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"MFA 自动字界未完成；请上传逐字 CSV/TextGrid。诊断日志：{log_path}") from error
    if completed.returncode != 0:
        summary = log_path.read_text(encoding="utf-8", errors="replace")[-1200:].strip()
        raise ValueError(f"本机 MFA 自动字界失败，未退回均分时间。诊断日志：{log_path}\n{summary}")
    candidates = list(output.rglob("speech.TextGrid"))
    if len(candidates) != 1:
        raise ValueError(f"MFA 未生成唯一的逐字 TextGrid；未退回均分时间。日志：{log_path}")
    intervals = read_word_intervals(candidates[0], characters, tokens, duration)
    (job / "字界.json").write_text(json.dumps({"method": "mfa-local", "language": language, "text": text, "alignment": intervals,
                                              "duration": duration, "textgrid": str(candidates[0])},
                                             ensure_ascii=False, indent=2), encoding="utf-8")
    return intervals
