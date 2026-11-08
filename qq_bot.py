"""Optional source-mode QQ group bot for VvTalk Studio."""
from __future__ import annotations

import argparse
import asyncio
import base64
from collections import deque
import logging
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlsplit

LOG = logging.getLogger('vvtalk.qq')
GROUP_EVENT = 'GROUP_AT_MESSAGE_CREATE'
MAX_PROMPT = 600
MAX_REPLY = 180
MAX_VOICE_TEXT = 72
GROUP_INTERVAL = 5
VOICE_INTERVAL = 30
MENTION = re.compile(r'<@!?[^>]+>|<qqbot-at-[^>]+>', re.IGNORECASE)
VOICE_COMMAND = re.compile(r'^/语音(?:\s+|$)')
GROUP_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')


def encode_voice(wav: Path) -> bytes:
    import numpy as np
    import parselmouth
    import pilk

    sound = parselmouth.Sound(str(wav))
    if not 0 < sound.duration <= 30:
        raise ValueError('QQ 语音须在 30 秒内。')
    if sound.n_channels != 1:
        sound = sound.convert_to_mono()
    sample_rate = 24000
    samples = sound.resample(sample_rate, 50).values[0]
    samples = np.rint(np.clip(samples * 32768, -32768, 32767)).astype('<i2')
    pcm, silk = wav.with_suffix('.pcm'), wav.with_suffix('.silk')
    pcm.write_bytes(samples.tobytes())
    pilk.encode(str(pcm), str(silk), pcm_rate=sample_rate, tencent=True)
    encoded = silk.read_bytes()
    if not encoded.startswith(b'\x02#!SILK_V3') or pilk.get_duration(str(silk)) <= 0:
        raise ValueError('未生成有效的 QQ SILK 语音。')
    return encoded


def render_voice(text: str, project: Path) -> bytes:
    import server
    from server import ace_render

    if not HAN.search(text):
        raise ValueError('当前语音回复需要中文文稿。')
    with tempfile.TemporaryDirectory(prefix='vvtalk-qq-') as directory:
        payload = {'document': {'language': 'zh', 'text': text[:MAX_VOICE_TEXT]}}
        if voice := os.environ.get('VVTALK_QQ_ACE_VOICE', '').strip():
            payload['ace_voice'] = voice
        job = server.preview(payload,
                             folder=Path(directory), expected_project=project, render_timeout=75)
        ident = job['id']
        # Wait for ACE to restore its idle project and finish writing before deleting the scratch folder.
        with ace_render.RENDER_LOCK:
            try:
                completed = ace_render.public_job(ident)
                if completed['status'] != 'succeeded' or not completed.get('restored_project'):
                    raise ValueError('ACE 合成或专用工程恢复失败。')
                return encode_voice(ace_render.audio_path(ident))
            finally:
                ace_render.JOBS.pop(ident, None)


class ChatModel:
    def __init__(self, http, endpoint: str, model: str, key: str):
        self.http = http
        self.endpoint = endpoint
        self.model = model
        self.headers = {'Authorization': f'Bearer {key}'} if key else {}

    async def reply(self, prompt: str, history: deque, *, voice: bool) -> str:
        instruction = (
            '你是一个自称机器人的 QQ 群聊搭子。用轻松自然的简体中文答复，'
            '只输出准备发到群里的正文，不要链接、Markdown、艾特或角色标签。'
        )
        if voice:
            instruction += '答复会用于中文合成语音，请用一句短句，最多七十个字，数字用汉字。'
        response = await self.http.post(
            self.endpoint, headers=self.headers, timeout=20,
            json={
                'model': self.model,
                'messages': [
                    {'role': 'system', 'content': instruction},
                    *history,
                    {'role': 'user', 'content': prompt},
                ],
                'max_tokens': 250,
            },
        )
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        if not isinstance(content, str):
            raise ValueError('AI 返回了无效的文字回复。')
        plain = ' '.join(MENTION.sub('', content).replace('@', '＠').split())
        plain = plain[:MAX_VOICE_TEXT if voice else MAX_REPLY]
        if not plain:
            raise ValueError('AI 返回了空回复。')
        return plain


class GroupBot:
    def __init__(self, api, chat, groups: set[str], *, ace_project: Path | None = None, discover=False):
        self.api = api
        self.chat = chat
        self.groups = groups
        self.ace_project = ace_project
        self.discover = discover
        self.discovered: set[str] = set()
        self.history: dict[str, deque] = {}
        self.busy: set[str] = set()
        self.last_reply: dict[str, float] = {}
        self.last_voice: dict[str, float] = {}
        self.voice_lock = asyncio.Lock()

    async def on_message(self, event_type: str, raw: dict) -> None:
        if event_type != GROUP_EVENT:
            return
        group, message = raw.get('group_openid'), raw.get('id')
        if not isinstance(group, str) or not GROUP_ID.fullmatch(group) or not isinstance(message, str) or not message:
            return
        author = raw.get('author')
        if isinstance(author, dict) and author.get('bot'):
            return
        if self.discover:
            if group not in self.discovered:
                self.discovered.add(group)
                print(f'群 OpenID: {group}', flush=True)
            return
        if group not in self.groups or group in self.busy:
            return
        content = raw.get('content')
        if not isinstance(content, str) or raw.get('message_type', 0) not in (0, None):
            return
        now = time.monotonic()
        if now - self.last_reply.get(group, float('-inf')) < GROUP_INTERVAL:
            return
        self.busy.add(group)
        try:
            await self.reply(group, message, MENTION.sub('', content).strip())
        except Exception as error:
            # Keep group messages and provider responses out of diagnostic logs.
            LOG.warning('QQ 回复发送失败 (%s)。', type(error).__name__)
        finally:
            self.last_reply[group] = time.monotonic()
            self.busy.remove(group)

    async def reply(self, group: str, message: str, content: str) -> None:
        command = VOICE_COMMAND.match(content)
        prompt = content[command.end():].strip() if command else content
        if not prompt:
            await self.send(group, message, '发一句话就能聊天。试试「/语音 用一句话打个招呼」。')
            return
        prompt = prompt[:MAX_PROMPT]
        history = self.history.setdefault(group, deque(maxlen=6))
        try:
            answer = await asyncio.wait_for(self.chat.reply(prompt, history, voice=bool(command)), timeout=25)
        except Exception as error:
            LOG.warning('AI 回复生成失败 (%s)。', type(error).__name__)
            await self.send(group, message, '我这会儿连不上对话模型，稍后再试吧。')
            return

        file_info = await self.prepare_voice(group, answer) if command else None
        await self.send(group, message, answer if not command or file_info else '语音暂不可用，先回文字：' + answer,
                        file_info=file_info)
        history.extend(({'role': 'user', 'content': prompt}, {'role': 'assistant', 'content': answer}))

    async def prepare_voice(self, group: str, text: str) -> str | None:
        now = time.monotonic()
        if (self.ace_project is None or self.voice_lock.locked()
                or now - self.last_voice.get(group, float('-inf')) < VOICE_INTERVAL):
            return None
        async with self.voice_lock:
            self.last_voice[group] = now
            try:
                audio = await asyncio.to_thread(render_voice, text, self.ace_project)
                uploaded = await self.api.request('POST', f'/v2/groups/{group}/files', {
                    'file_type': 3,
                    'file_data': base64.b64encode(audio).decode('ascii'),
                    'srv_send_msg': False,
                }, timeout=20)
                file_info = uploaded.get('file_info')
                if isinstance(file_info, str) and file_info:
                    return file_info
                LOG.warning('QQ 上传未返回语音凭证。')
            except Exception as error:
                LOG.warning('语音合成或上传失败 (%s)。请检查 ACE 专用工程和 QQ 富媒体权限。', type(error).__name__)
            return None

    async def send(self, group: str, message: str, text: str, *, file_info: str | None = None) -> None:
        body = {'msg_type': 0, 'content': text, 'msg_id': message, 'msg_seq': 1}
        if file_info:
            body.update(msg_type=7, content=' ', media={'file_info': file_info})
        result = await self.api.request('POST', f'/v2/groups/{group}/messages', body, timeout=10)
        if not result.get('id'):
            raise RuntimeError('QQ 未返回已发送的消息 ID。')


def env_required(name: str) -> str:
    value = os.environ.get(name, '').strip()
    if not value:
        raise ValueError(f'请在本机设置 {name}。')
    return value


def model_endpoint(base: str) -> str:
    url = urlsplit(base)
    local = url.hostname in {'localhost', '127.0.0.1', '::1'}
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or (url.scheme != 'https' and not (url.scheme == 'http' and local))):
        raise ValueError('VVTALK_AI_BASE_URL 需要 HTTPS 地址或本机 HTTP 地址。')
    return base.rstrip('/') + '/chat/completions'


async def run_bot(discover: bool) -> None:
    app_id, secret = env_required('VVTALK_QQ_APP_ID'), env_required('VVTALK_QQ_APP_SECRET')
    groups, project = set(), None
    if not discover:
        groups = set(re.split(r'[,\s]+', env_required('VVTALK_QQ_GROUPS')))
        if not all(GROUP_ID.fullmatch(group) for group in groups):
            raise ValueError('VVTALK_QQ_GROUPS 请填写逗号分隔的群 OpenID。')
        endpoint = model_endpoint(env_required('VVTALK_AI_BASE_URL'))
        model = env_required('VVTALK_AI_MODEL')
        configured_project = os.environ.get('VVTALK_QQ_ACE_PROJECT', '').strip()
        if configured_project:
            project = Path(configured_project).expanduser().resolve()
            if project.suffix.lower() != '.acep' or not project.is_file():
                raise ValueError('VVTALK_QQ_ACE_PROJECT 需要已保存的 .acep 专用工程。')

    import httpx
    from qqbot_agent_sdk import QQApiClient, QQWebSocket, WSCallbacks

    if project:
        import pilk  # Verify the optional voice dependency before subscribing.

    loop = asyncio.get_running_loop()
    stopped = asyncio.Event()
    session = (None, None)

    def set_session(session_id, sequence):
        nonlocal session
        session = (session_id, sequence)

    def fatal(code, _message):
        LOG.error('QQ 网关已停止，错误码 %s。请核对开放平台权限和凭证。', code)
        loop.call_soon_threadsafe(stopped.set)

    async with httpx.AsyncClient(follow_redirects=False) as http:
        api = QQApiClient(app_id=app_id, client_secret=secret, log_tag='VvTalk')
        api.setup(http)
        chat = None if discover else ChatModel(http, endpoint, model, os.environ.get('VVTALK_AI_API_KEY', ''))
        bot = GroupBot(api, chat, groups, ace_project=project, discover=discover)
        socket = QQWebSocket(WSCallbacks(
            on_message_event=bot.on_message,
            on_connected=lambda: LOG.info('QQ 已连接。%s', '请在目标群 @机器人 获取群 OpenID。' if discover else '等待群内 @机器人。'),
            on_disconnected=lambda: LOG.info('QQ 已断开，等待重连。'),
            on_fatal_error=fatal,
            get_token=api.ensure_token_sync,
            get_session=lambda: session,
            set_session=set_session,
            set_heartbeat_interval=lambda _interval: None,
            clear_token=api.clear_token,
            fail_pending=lambda _reason: None,
            get_gateway_url=api.get_gateway_url_sync,
        ), log_tag='VvTalk')
        gateway = await api.get_gateway_url()
        socket.start(gateway, loop)
        try:
            await stopped.wait()
            raise RuntimeError('QQ 网关停止。')
        finally:
            await socket.async_stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discover-groups', action='store_true', help='只显示 @机器人 的群 OpenID')
    parser.add_argument('--list-voices', action='store_true', help='列出本机支持中文的 ACE 声库及配置标识')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    for name in ('httpx', 'httpcore', 'qqbot_agent_sdk'):
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        if args.list_voices:
            from server import available_ace_voices
            for voice in available_ace_voices('zh'):
                print(f"{voice['key']}  {voice['name']} · {voice['model_name']}")
            return 0
        asyncio.run(run_bot(args.discover_groups))
    except KeyboardInterrupt:
        return 0
    except ImportError:
        LOG.error('请先用当前 Python 安装 requirements-qq.txt 中的依赖。')
        return 1
    except ValueError as error:
        LOG.error('%s', error)
        return 1
    except Exception as error:
        LOG.error('QQ 启动失败 (%s)。请核对凭证、网络、应用权限和 IP 白名单。', type(error).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
