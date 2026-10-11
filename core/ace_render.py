"""Guarded ACE audio jobs for the local long-text workbench."""
from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
import wave
from pathlib import Path

CLI = Path(r'C:\Program Files\ACE Studio\acestudio-cli.exe')
ROOT = Path(__file__).resolve().parent
JOBS: dict[str, dict] = {}
RENDER_LOCK = threading.Lock()


def cli(*args, timeout=60):
    if not CLI.is_file():
        raise ValueError('未找到 ACE Studio CLI。')
    response = subprocess.run([str(CLI), '--json', *map(str, args)], capture_output=True,
                              timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    output = response.stdout.decode('utf-8', 'replace').strip()
    if response.returncode:
        detail = response.stderr.decode('utf-8', 'replace').strip() or output
        if 'UNSAVED_CHANGES' in detail:
            raise ValueError('ACE 当前工程有未保存改动，请先在 ACE 保存，再开始试听。')
        if 'bridge not reachable' in detail or 'not reachable' in detail:
            raise ValueError('请先启动 ACE Studio，并开启 External Agent Access，再合成试听。')
        raise ValueError(detail[-1500:] or 'ACE 命令执行失败。')
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        raise ValueError('ACE 返回了无法读取的结果。') from error


def _same_path(left, right):
    return bool(left) and Path(left).resolve() == Path(right).resolve()


def start_render(document, exported):
    """The caller has built and exported a validated immutable document snapshot."""
    if not RENDER_LOCK.acquire(blocking=False):
        raise ValueError('已有一项 ACE 合成任务进行中，请等待完成。')
    try:
        state = cli('project', 'dirty')
        if state.get('dirty'):
            raise ValueError('ACE 当前工程有未保存改动，请先在 ACE 保存，再开始试听。')
        ident = uuid.uuid4().hex
        job = {'id': ident, 'status': 'running', 'progress': 0.0,
               'message': '正在加载语调工程…', 'directory': exported['directory'],
               'files': exported['files'], 'started_at': time.time(),
               'duration': document['duration']}
        JOBS[ident] = job
        threading.Thread(target=_render, args=(job, state.get('projectPath'), document, exported),
                         daemon=True).start()
        return public_job(ident)
    except Exception:
        RENDER_LOCK.release()
        raise


def public_job(ident):
    if ident not in JOBS:
        raise ValueError('合成任务不存在；服务重启后请重新生成。')
    return {key: value for key, value in JOBS[ident].copy().items() if not key.startswith('_')}


def _render(job, original_path, document, exported):
    target = Path(exported['files']['acep'])
    audio = target.parent / '配音.wav'
    ace_job = None
    try:
        cli('project', 'open', target, timeout=120)
        launch = cli('export', 'audio', '--path', audio, '--from', '0s',
                     '--to', f"{document['duration'] + .15:.6f}s", '--format', 'wav',
                     '--sample-rate', '44100', '--channels', '1', '--without-effects', 'true')
        ace_job = launch['jobId']
        job.update(message='ACE 正在合成配音…', ace_job_id=ace_job)
        deadline = time.monotonic() + max(600, document['duration'] * 4)
        while True:
            state = cli('job', 'get', ace_job, timeout=30)
            lifecycle = state.get('lifecycle')
            progress = state.get('progress')
            if isinstance(progress, (int, float)):
                job['progress'] = max(0, min(1, progress))
            if lifecycle == 'succeeded':
                break
            if lifecycle in {'failed', 'cancelled', 'canceled'}:
                raise ValueError('ACE 合成未完成：' + json.dumps(state, ensure_ascii=False)[-1000:])
            if time.monotonic() >= deadline:
                cli('job', 'cancel', ace_job)
                raise ValueError('合成超过等待时限，任务已取消；请分段试听或检查 ACE。')
            time.sleep(1.2)
        with wave.open(str(audio), 'rb') as stream:
            frames, rate = stream.getnframes(), stream.getframerate()
            if frames <= 0 or rate <= 0:
                raise ValueError('ACE 输出了空音频。')
            job['audio_duration'] = frames / rate
        job['files'] = dict(job['files'], wav=str(audio))
        job['audio_url'] = '/api/workbench/audio?id=' + job['id']
        job['audio_download'] = '/api/workbench/audio?id=' + job['id'] + '&download=1'
        job.update(status='succeeded', progress=1.0, message='配音已生成，可播放或下载 WAV。')
    except Exception as error:
        job.update(status='failed', message=str(error))
    finally:
        # Restore a saved previous project only if the user has not edited or switched.
        if original_path and not _same_path(original_path, target):
            try:
                current = cli('project', 'dirty')
                if not current.get('dirty') and _same_path(current.get('projectPath'), target):
                    cli('project', 'open', original_path, timeout=120)
                    job['restored_project'] = original_path
            except Exception as error:
                job['restore_message'] = '原工程自动恢复未完成：' + str(error)
        job['finished_at'] = time.time()
        try:
            (target.parent / '合成记录.json').write_text(
                json.dumps(public_job(job['id']), ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError as error:
            job['record_message'] = '合成记录保存失败：' + str(error)
        finally:
            RENDER_LOCK.release()


def audio_path(ident):
    job = JOBS.get(ident)
    if not job or job.get('status') != 'succeeded':
        raise ValueError('音频尚未生成。')
    source = Path(job['files']['wav'])
    if not source.is_file():
        raise ValueError('音频文件已移动。')
    return source
