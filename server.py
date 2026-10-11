"""Offline, loopback-only prosody workbench. No vendor models are distributed."""
from __future__ import annotations

import base64
import csv
import io
import json
import math
import mimetypes
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / 'core'))
from engine import analyze
from languages import normalize_language, normalize_pronunciation_override, text_units, japanese_moras, rebuild_note_metadata, apply_unit_overrides
from workbench import build_document, flatten_document
from import_vsqx import read_vsqx
from adapters import export_project, install_synthv_script, synthv_payload
from alignment import detect_alignment, align_audio
import ace_render
import parselmouth
from praatio import textgrid

VERSION = '1.1.2'
DATA = Path(os.environ.get('VVTALK_DATA_DIR', str(Path(os.environ.get('USERPROFILE', Path.home())) / 'AppData' / 'Local' / 'VvTalkStudio'))).resolve()
OUTPUTS = DATA / 'outputs'
UPLOADS = DATA / 'uploads'
TEMPLATE = ROOT / 'templates' / 'speech_template.acep'
SV_SCRIPT_DIR = Path.home() / 'AppData/Roaming/Dreamtonics/Synthesizer V Studio 2/scripts'
MAX_BODY = 92 * 1024 * 1024
HOST_PATHS = {'ace': Path(r'C:\Program Files\ACE Studio\ACE Studio.exe'),
              'synthv': Path(r'C:\Program Files\Synthesizer V Studio 2 Pro\synthv-studio.exe'),
              'vocaloid6': Path(r'C:\Program Files\VOCALOID6\Editor\VOCALOID6.exe')}
FILES: dict[str, Path] = {}
FILE_LOCK = threading.Lock()
DATA_LOCK = threading.Lock()
_initialized_data: Path | None = None


def initialize():
    global DATA, OUTPUTS, UPLOADS, _initialized_data
    with DATA_LOCK:
        if _initialized_data != DATA:
            DATA.mkdir(parents=True, exist_ok=True)
            # Windows app virtualization may resolve existing folders to their
            # logical path but newly written files to a redirected physical path.
            # Anchor all ownership checks to the actual destination of a write.
            probe = DATA / ('.path-check-' + uuid.uuid4().hex)
            probe_created = False
            try:
                with probe.open('xb'):
                    probe_created = True
                actual_data = probe.resolve(strict=True).parent
            finally:
                if probe_created:
                    probe.unlink(missing_ok=True)
            DATA = actual_data
            OUTPUTS, UPLOADS = DATA / 'outputs', DATA / 'uploads'
        OUTPUTS.mkdir(parents=True, exist_ok=True)
        UPLOADS.mkdir(parents=True, exist_ok=True)
        outputs, uploads = OUTPUTS.resolve(strict=True), UPLOADS.resolve(strict=True)
        if not outputs.is_relative_to(DATA) or not uploads.is_relative_to(DATA):
            raise ValueError('输出与上传目录必须位于本工具的数据目录中。')
        OUTPUTS, UPLOADS = outputs, uploads
        _initialized_data = DATA


def public_file(path: Path, format=None):
    path = path.resolve()
    if not path.is_relative_to(DATA) or not path.is_file():
        raise ValueError('文件不在本工具的数据目录。')
    ident = uuid.uuid4().hex
    with FILE_LOCK:
        FILES[ident] = path
    return {'name': path.name, 'path': str(path), 'format': format or path.suffix.lstrip('.'),
            'url': '/api/file?id=' + ident}


def directory():
    initialize()
    path = OUTPUTS / (datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8])
    path.mkdir()
    return path


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def validate_result(result):
    if not isinstance(result, dict):
        raise ValueError('需要有效的语调工程。')
    # Copy untrusted JSON: validation must never change the user's saved document.
    result = json.loads(json.dumps(result, allow_nan=False))
    try:
        language = normalize_language(result.get('language'))
        bpm, duration = float(result['bpm']), float(result['duration'])
        notes, curve = result['notes'], result['curve']
        if not math.isfinite(bpm) or not 20 <= bpm <= 400 or not math.isfinite(duration) or not 0 < duration <= 3600:
            raise ValueError('速度或时长超出范围。')
        if not isinstance(notes, list) or not 1 <= len(notes) <= 10000 or not isinstance(curve, list) or not 1 <= len(curve) <= 1500000:
            raise ValueError('音符或曲线数量无效。')
        if any(not isinstance(note, dict) for note in notes) or any(not isinstance(point, dict) for point in curve):
            raise ValueError('音符和曲线采样必须是 JSON 对象。')
        for note, metadata in zip(notes, rebuild_note_metadata(result)):
            note.update(metadata)
        previous_end, previous_time, voiced = 0, -1, 0
        for note in notes:
            start, end, key = float(note['start']), float(note['end']), float(note['key'])
            if not all(math.isfinite(v) for v in (start, end, key)) or start < previous_end - 1e-7 or start < 0 or end <= start or end > duration + 1e-6 or not 0 <= key <= 127 or not key.is_integer():
                raise ValueError('音符必须有序、无重叠，并使用有效整数 MIDI 音高。')
            if normalize_language(note.get('language', language)) != language:
                raise ValueError('音符语言与工程语言不一致。')
            lyric = note.get('lyric')
            valid = isinstance(lyric, str) and bool(lyric) and len(lyric) <= 80
            if language == 'zh':
                valid = valid and bool(re.fullmatch(r'[\u3400-\u4dbf\u4e00-\u9fff]', lyric))
            elif language == 'ja':
                valid = valid and bool(re.fullmatch(r'[ぁ-ゖァ-ヺー]+', lyric)) and len(japanese_moras(lyric)) == 1
            else:
                valid = valid and bool(re.fullmatch(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*", lyric))
            if not valid:
                raise ValueError('每个音符需要对应语言的一个字、一个日语拍或一个英语词。')
            if note.get('pronunciation_override'):
                normalize_pronunciation_override(note['pronunciation_override'], language)
            if note.get('accent_override') is not None and (language != 'ja' or type(note['accent_override']) is not int or note['accent_override'] not in (0, 1)):
                raise ValueError('日语高低覆盖需要 0 或 1。')
            if note.get('stress_override') is not None:
                stress = note['stress_override']
                if language != 'en' or not isinstance(stress, list) or not stress or any(type(value) is not int or value not in (0, 1, 2) for value in stress):
                    raise ValueError('英语重音覆盖需要由 0、1、2 组成的音节数组。')
                if note.get('syllable_count') and len(stress) != note['syllable_count']:
                    raise ValueError('英语重音覆盖与音节数量不一致。')
            note.update(start=start, end=end, key=int(key), language=language)
            previous_end = end
        for point in curve:
            t, p = float(point['time']), point.get('pitch')
            if not math.isfinite(t) or t < previous_time or t < 0 or t > duration + 1e-6:
                raise ValueError('曲线时间必须有序且位于工程时长内。')
            if p is not None:
                p = float(p)
                if not math.isfinite(p) or not -48 <= p <= 175:
                    raise ValueError('曲线音高超出支持范围。')
                voiced += 1
            point.update(time=t, pitch=p)
            previous_time = t
        if not voiced:
            raise ValueError('没有可导出的有声音高。')
        result.update(bpm=bpm, duration=duration, language=language)
        return result
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError('工程缺少有效的 notes、curve、bpm 或 duration。') from error


def snapshot(payload):
    if payload.get('document') is not None:
        document = build_document(payload['document'])
        return document, validate_result(flatten_document(document))
    return None, validate_result(payload.get('result'))


def analyze_document(payload):
    document = build_document(payload)
    return {'document': document, 'result': flatten_document(document)}


def save_document(payload):
    document, result = snapshot(payload)
    folder = directory()
    path = folder / '语调工程.vvtalk.json'
    write_json(path, {'format': 'vvtalk-studio', 'version': 1, 'title': payload.get('title') or (document or {}).get('title', '语调工程'),
                      'document': document, 'result': result})
    return {'path': str(path), 'folder': str(folder), **public_file(path)}


def do_export(payload):
    document, result = snapshot(payload)
    target = payload.get('target', 'ace')
    if target not in {'ace', 'synthv', 'vocaloid5', 'vocaloid6'}:
        raise ValueError('请选择支持的目标引擎。')
    folder = directory()
    exported = export_project(result, document, folder, target, TEMPLATE)
    warnings = list(dict.fromkeys(result.get('warnings', []) + exported.get('warnings', [])))
    files = [public_file(p) for p in sorted(folder.rglob('*')) if p.is_file()]
    if len(files) != 1:
        raise ValueError('导出应生成所选引擎的一个工程文件。')
    return {'folder': str(folder), 'files': files, 'warnings': warnings}


def synthv_script(payload):
    _, result = snapshot(payload)
    return {'data': synthv_payload(result), 'warnings': result.get('warnings', [])}


def owned_upload(ident):
    if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}\.[A-Za-z0-9]+', ident):
        raise ValueError('上传标识无效，请重新选择文件。')
    source = (UPLOADS / ident).resolve()
    if source.parent != UPLOADS or not source.is_file():
        raise ValueError('上传文件已不存在。')
    return source


def upload(payload):
    initialize()
    name = str(payload.get('name', ''))
    extension = Path(name).suffix.lower()
    kind = payload.get('kind')
    allowed = {'audio': {'.wav', '.flac', '.aif', '.aiff'}, 'alignment': {'.csv', '.textgrid'}, 'vsqx': {'.vsqx'}}
    if kind not in allowed or extension not in allowed[kind]:
        raise ValueError('参考音频请选择 WAV/FLAC/AIFF；标注请选择 CSV/TextGrid；工程请选择 VSQX4。')
    try:
        raw = base64.b64decode(payload.get('data', ''), validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError('上传数据无效。') from error
    if not 0 < len(raw) <= 64 * 1024 * 1024:
        raise ValueError('上传文件需大于零，且不超过 64 MB。')
    ident = uuid.uuid4().hex + extension
    source = UPLOADS / ident
    source.write_bytes(raw)
    response = {'id': ident, 'name': name, **public_file(source)}
    if kind == 'vsqx':
        result = validate_result(read_vsqx(source, payload.get('text') or None, language=normalize_language(payload.get('language'))))
        response.update(result=result, text=result['text'], document=None)
    elif kind == 'audio':
        try:
            sound = parselmouth.Sound(str(source))
            if not .1 <= sound.duration <= 180:
                raise ValueError('示读音频长度需在 0.1–180 秒之间；请先分段。')
            response['duration'] = sound.duration
        except parselmouth.PraatError as error:
            raise ValueError('音频无法解码，请转成普通 PCM WAV。') from error
    return response


def read_alignment(source, text, language='zh', word_readings=None, unit_overrides=None):
    language = normalize_language(language)
    units = text_units(text, language, word_readings)
    if unit_overrides is not None:
        apply_unit_overrides(units, unit_overrides)
    chars = [unit['lyric'] for unit in units]
    if source.suffix.lower() == '.csv':
        rows = list(csv.DictReader(io.StringIO(source.read_text(encoding='utf-8-sig'))))
        try:
            intervals = [(float(row['start']), float(row['end']), (row.get('lyric') or '').strip()) for row in rows]
        except (KeyError, ValueError) as error:
            raise ValueError('CSV 需要 start,end 列，单位是秒；lyric 可选。') from error
    else:
        try:
            grid = textgrid.openTextgrid(str(source), includeEmptyIntervals=True)
            candidates = []
            for tier_name in grid.tierNames:
                entries = grid.getTier(tier_name).entries
                valid = [(float(s), float(e), str(label).strip()) for s, e, label in entries
                         if str(label).strip().lower() not in {'', 'sil', 'silence', 'sp', 'spn', 'con', '1', '2', '-', '='}]
                if len(valid) == len(chars):
                    candidates.append((tier_name.lower() not in {'grid', 'syllables', 'syllable', 'words'}, valid))
            if not candidates:
                raise ValueError('标注中没有与调教单位数量一致的区间层（中文逐字、日语逐拍、英语逐词）。')
            intervals = min(candidates, key=lambda x: x[0])[1]
        except (ValueError, TypeError) as error:
            raise ValueError('TextGrid 需要逐字、逐拍或逐词 IntervalTier 标注，不能使用 PointTier 或整句层。') from error
        except Exception as error:
            raise ValueError('TextGrid 无法读取，请从 Praat 重新保存。') from error
    if len(intervals) != len(chars):
        raise ValueError(f'标注有 {len(intervals)} 个区间，文本有 {len(chars)} 个调教单位。')
    for unit, (_, _, label) in zip(units, intervals):
        if language == 'zh':
            mismatch = re.search(r'[\u3400-\u4dbf\u4e00-\u9fff]', label) and label != unit['lyric']
        elif language == 'ja':
            # Accept hiragana/katakana labels, but reject labels for another mora.
            kana = lambda value: ''.join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ヶ' else c for c in value)
            mismatch = bool(label) and kana(label) not in {kana(unit['lyric']), kana(unit.get('reading', ''))}
        else:
            mismatch = bool(label) and label.casefold().replace('’', "'") != unit['lyric'].casefold().replace('’', "'")
        if mismatch:
            raise ValueError(f'标注中的“{label}”与台词中的“{unit["lyric"]}”不一致。')
    return [{'lyric': char, 'start': s, 'end': e} for char, (s, e, _) in zip(chars, intervals)]


def reference(payload):
    source = owned_upload(payload.get('audio_id'))
    text = payload.get('text', '')
    language = normalize_language(payload.get('language'))
    settings = payload.get('settings') or {}
    supplied = {key: settings[key] for key in ('base_pitch', 'range_scale', 'smoothing_ms', 'bpm') if key in settings}
    supplied.update(mode='reference', text=text, language=language, audio_path=str(source), fmin=payload.get('fmin', 75),
                    fmax=payload.get('fmax', 600), pitch_mode=payload.get('pitch_mode', 'absolute'))
    for key in ('word_readings', 'unit_overrides'):
        if key in payload:
            supplied[key] = payload[key]
    if payload.get('alignment_id'):
        supplied['alignment'] = read_alignment(owned_upload(payload['alignment_id']), text, language,
                                               payload.get('word_readings'), payload.get('unit_overrides'))
    elif payload.get('alignment_mode') == 'auto':
        supplied['alignment'] = align_audio(source, text, DATA / 'alignment-jobs', language=language,
                                           word_readings=payload.get('word_readings'), unit_overrides=payload.get('unit_overrides'))
    result = validate_result(analyze(supplied))
    if payload.get('alignment_mode') == 'auto' and not payload.get('alignment_id'):
        result['alignment_source'] = 'mfa-local'
        result['warnings'].append('时间区间由对应语言的本机 MFA 强制对齐生成；请对照原录音复核边界与读音。')
    # Saved results contain the extracted curve, not a machine-specific upload path.
    result.pop('audio_path', None)
    return {'document': None, 'result': result, 'source': {'audio_id': payload.get('audio_id')}}


def info():
    initialize()
    try:
        state = ace_render.cli('project', 'info', timeout=5)
        ace = {'connected': True, 'project': state}
    except ValueError as error:
        ace = {'connected': False, 'message': str(error)}
    hosts = {key: {'installed': path.is_file(), 'path': str(path)} for key, path in HOST_PATHS.items()}
    return {'version': VERSION, 'pid': os.getpid(), 'targets': ['synthv', 'ace', 'vocaloid5', 'vocaloid6'], 'ace': ace,
            'hosts': hosts, 'languages': ['zh', 'ja', 'en'], 'alignment': detect_alignment(),
            'alignment_by_language': {language: detect_alignment(language) for language in ('zh', 'ja', 'en')},
            'data_dir': str(DATA), 'plugins_dir': str(ROOT / 'plugins')}


def preview(payload):
    document, result = snapshot(payload)
    if document and payload.get('section_id'):
        result = validate_result(flatten_document(document, payload['section_id']))
        document = None
    folder = directory()
    export_project(result, document, folder, 'ace', TEMPLATE)
    candidates = list(folder.rglob('*.acep'))
    if len(candidates) != 1:
        raise ValueError('未生成有效的 ACE 工程。')
    return ace_render.start_render({'duration': result['duration']},
                                   {'directory': str(folder), 'files': {'acep': str(candidates[0])}})


def public_job(ident):
    job = ace_render.public_job(ident)
    if job.get('status') == 'succeeded':
        media = public_file(ace_render.audio_path(ident))
        job.update(audio_url=media['url'], audio_download=media['url'] + '&download=1',
                   url=media['url'], path=media['path'])
    return job


def open_folder(folder):
    path = Path(str(folder)).resolve()
    if not path.is_relative_to(DATA) or not path.is_dir():
        raise ValueError('只能打开本工具保存的输出目录。')
    if os.name == 'nt':
        os.startfile(str(path))
    return {'success': True, 'folder': str(path)}


def install_script(payload):
    folder = Path(payload['folder']) if payload.get('folder') else SV_SCRIPT_DIR
    if not folder.is_dir():
        raise ValueError('未找到 SV2 的 scripts 文件夹。请先在 SV2 中选择「脚本 → 打开脚本文件夹」，或使用随包安装脚本指定目录。')
    return install_synthv_script(folder)


class Handler(BaseHTTPRequestHandler):
    server_version = 'VvTalkStudio/' + VERSION

    def log_message(self, *args):
        pass

    def origin_ok(self):
        host = f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') != host:
            return False
        origin = self.headers.get('Origin')
        return origin is None or origin == 'http://' + host

    def respond(self, value, status=200):
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_file(self, path, download=False):
        size, start, end = path.stat().st_size, 0, path.stat().st_size - 1
        range_header = self.headers.get('Range')
        partial = False
        if range_header:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', range_header)
            if not match or not any(match.groups()):
                self.respond({'error': '无效的范围请求。'}, 416)
                return
            if not match[1]:
                start = max(0, size - int(match[2]))
            else:
                start = int(match[1])
                end = min(end, int(match[2])) if match[2] else end
            if start > end or start >= size:
                self.respond({'error': '范围超出文件长度。'}, 416)
                return
            partial = True
        self.send_response(206 if partial else 200)
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if partial:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        if download:
            from urllib.parse import quote
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(path.name))
        self.end_headers()
        with path.open('rb') as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = stream.read(min(256 * 1024, remaining))
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self):
        if not self.origin_ok():
            return self.respond({'error': '只允许本机工作台访问。'}, 403)
        parsed = urlparse(self.path)
        try:
            if parsed.path == '/api/info':
                return self.respond(info())
            if parsed.path == '/api/job':
                return self.respond(public_job(parse_qs(parsed.query).get('id', [''])[0]))
            if parsed.path == '/api/file':
                ident = parse_qs(parsed.query).get('id', [''])[0]
                source = FILES.get(ident)
                if not source or not source.is_file():
                    return self.respond({'error': '文件已移动或服务已重启，请重新生成。'}, 404)
                return self.send_file(source, 'download' in parse_qs(parsed.query))
            names = {'/': 'index.html', '/index.html': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
            if parsed.path in names:
                return self.send_file(ROOT / 'static' / names[parsed.path])
            return self.respond({'error': '找不到页面。'}, 404)
        except (ValueError, OSError) as error:
            return self.respond({'error': str(error)}, 400)

    def do_POST(self):
        if not self.origin_ok() or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.respond({'error': '只接受本机页面的 JSON 请求。'}, 403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY:
                raise ValueError('请求为空或超过 92 MB。')
            payload = json.loads(self.rfile.read(length), parse_constant=lambda value: (_ for _ in ()).throw(ValueError('不能使用非有限数值。')))
            if not isinstance(payload, dict):
                raise ValueError('请求必须是 JSON 对象。')
            actions = {'/api/analyze': analyze_document, '/api/save-document': save_document,
                       '/api/export': do_export, '/api/synthv-script': synthv_script,
                       '/api/upload': upload, '/api/reference': reference,
                       '/api/preview': preview,
                       '/api/open-folder': lambda p: open_folder(p.get('folder')),
                       '/api/install-script': install_script}
            action = actions.get(urlparse(self.path).path)
            if action is None:
                return self.respond({'error': '找不到操作。'}, 404)
            return self.respond(action(payload))
        except (ValueError, TypeError, KeyError, OSError, parselmouth.PraatError) as error:
            return self.respond({'error': str(error)}, 400)
        except Exception as error:
            # Keep unexpected faults visible without terminating other requests.
            import traceback
            initialize()
            with (DATA / 'error.log').open('a', encoding='utf-8') as log:
                traceback.print_exc(file=log)
            return self.respond({'error': '操作失败：' + str(error)}, 500)


def create_server(port=0):
    initialize()
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)
