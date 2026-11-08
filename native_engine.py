"""Pipe transport for the native macOS workbench. It never opens a listening port."""
from __future__ import annotations

import json
import struct
import sys
import traceback
from difflib import SequenceMatcher
from pathlib import Path

from server import (MAX_BODY, ace_render, analyze_document, do_export, info, ingest_upload,
                    install_script, normalize_language, preview, public_job, reference,
                    snapshot, synthv_script, validate_ace_voice_key)
from pronunciation import vsinger_ace_voices

MAX_RESPONSE = 384 * 1024 * 1024


def import_file(payload):
    path = Path(payload['path'])
    with path.open('rb') as stream:
        raw = stream.read(64 * 1024 * 1024 + 1)
    return ingest_upload({**payload, 'name': path.name}, raw)


def project(payload):
    document, result = snapshot(payload)
    saved = {'format': 'vvtalk-studio', 'version': 1, 'title': payload.get('title') or '语调工程',
             'document': document, 'result': result}
    if payload.get('ace_voice'):
        saved['ace_voice'] = validate_ace_voice_key(payload['ace_voice'])
    return saved


def open_project(payload):
    if path := payload.get('path'):
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('工程文件过大，请分段处理。')
        try:
            saved = json.loads(raw.decode('utf-8-sig'))
        except (ValueError, UnicodeError) as error:
            raise ValueError('无法读取 JSON，请选择 VvTalk 工作台工程。') from error
    else:
        saved = payload['project']
    if not isinstance(saved, dict):
        raise ValueError('工作台工程必须是 JSON 对象。')
    document = saved.get('document')
    if document is not None or 'sections' in saved:
        document = saved if document is None else document
        if not isinstance(document, dict):
            raise ValueError('工程缺少有效的文稿。')
        if saved.get('language') is not None and normalize_language(saved['language']) != normalize_language(document.get('language')):
            raise ValueError('工程与文稿的语言不一致。')
        response = analyze_document(document)
        if saved.get('ace_voice'):
            response['ace_voice'] = validate_ace_voice_key(saved['ace_voice'])
        return response
    result = saved.get('result', saved)
    if not isinstance(result, dict):
        raise ValueError('工程缺少有效的参考曲线。')
    if saved.get('language') is not None and normalize_language(saved['language']) != normalize_language(result.get('language')):
        raise ValueError('工程与参考结果的语言不一致。')
    return project({'result': result, 'title': saved.get('title') or payload.get('title'),
                    'ace_voice': saved.get('ace_voice')})


def analyze_workbench(payload):
    previous = payload.get('sections') or []
    if not previous or payload['text'] == ''.join(section['text'] for section in previous):
        return analyze_document(payload)
    # Editing the whole script can move sentences. Keep edits on unchanged sentences.
    rebuilt = analyze_document({key: value for key, value in payload.items()
                                if key not in ('sections', 'word_readings')})
    sections = rebuilt['document']['sections']
    matches = SequenceMatcher(a=[section['text'] for section in previous],
                              b=[section['text'] for section in sections], autojunk=False)
    for old, new, count in matches.get_matching_blocks():
        for offset in range(count):
            original, fresh = previous[old + offset], sections[new + offset]
            sections[new + offset] = {**original, 'paragraph': fresh['paragraph']}
    return analyze_document(rebuilt['document'])


ACTIONS = {
    'info': lambda _: info(),
    'voices': lambda payload: {'voices': vsinger_ace_voices()},
    'analyze': analyze_workbench,
    'open': open_project,
    'save': project,
    'export': do_export,
    'import': import_file,
    'reference': reference,
    'preview': preview,
    'job': lambda payload: public_job(payload['id']),
    'synthv': synthv_script,
    'install': install_script,
}


def main():
    stream_in, stream_out = sys.stdin.buffer, sys.stdout.buffer
    sys.stdout = sys.stderr
    try:
        while header := stream_in.read(4):
            if len(header) != 4:
                break
            size, = struct.unpack('>I', header)
            if not 0 < size <= MAX_BODY:
                break
            raw = stream_in.read(size)
            if len(raw) != size:
                break
            try:
                request = json.loads(raw)
                result = ACTIONS[request['action']](request.get('payload') or {})
                data = json.dumps({'value': result}, ensure_ascii=False, allow_nan=False).encode()
                if len(data) > MAX_RESPONSE:
                    raise ValueError('工程数据过大，请分段处理。')
            except Exception as error:
                if not isinstance(error, (ValueError, TypeError, KeyError, OSError)):
                    traceback.print_exc()
                data = json.dumps({'error': str(error) or '操作失败。'}, ensure_ascii=False).encode()
            stream_out.write(struct.pack('>I', len(data)))
            stream_out.write(data)
            stream_out.flush()
    except BrokenPipeError:
        pass
    finally:
        # Let an active render finish restoring the user's original ACE project.
        with ace_render.RENDER_LOCK:
            pass


if __name__ == '__main__':
    main()
