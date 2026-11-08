import base64
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qq_bot
import server


def mention(group='TEST_GROUP', text='你好'):
    return {'id': 'incoming-message', 'group_openid': group, 'content': '<@!robot> ' + text,
            'author': {'member_openid': 'member'}}


class QQGroupBotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api = AsyncMock()
        self.api.request.return_value = {'id': 'outgoing-message'}
        self.chat = AsyncMock()
        self.chat.reply.return_value = '你好呀，群友。'
        self.bot = qq_bot.GroupBot(self.api, self.chat, {'TEST_GROUP'}, ace_project=Path('idle.acep'))

    async def test_only_mentions_in_allowed_groups_reach_model(self):
        await self.bot.on_message('GROUP_MESSAGE_CREATE', mention())
        await self.bot.on_message(qq_bot.GROUP_EVENT, mention('OTHER_GROUP'))
        await self.bot.on_message(qq_bot.GROUP_EVENT, {**mention(), 'author': {'bot': True}})
        self.chat.reply.assert_not_awaited()
        self.api.request.assert_not_awaited()

        await self.bot.on_message(qq_bot.GROUP_EVENT, mention())
        self.assertEqual(self.chat.reply.await_args.args[0], '你好')
        self.api.request.assert_awaited_once_with(
            'POST', '/v2/groups/TEST_GROUP/messages',
            {'msg_type': 0, 'content': '你好呀，群友。', 'msg_id': 'incoming-message', 'msg_seq': 1},
            timeout=10,
        )

    async def test_voice_upload_is_followed_by_one_passive_media_reply(self):
        self.api.request.side_effect = [{'file_info': 'uploaded-voice'}, {'id': 'outgoing-voice'}]
        audio = b'\x02#!SILK_V3\x01\x00\x00'
        with patch('qq_bot.render_voice', return_value=audio) as render:
            await self.bot.on_message(qq_bot.GROUP_EVENT, mention(text='/语音 打个招呼'))
        render.assert_called_once_with('你好呀，群友。', Path('idle.acep'))
        upload, send = [call.args for call in self.api.request.await_args_list]
        self.assertEqual(upload[1], '/v2/groups/TEST_GROUP/files')
        self.assertFalse(upload[2]['srv_send_msg'])
        self.assertEqual(upload[2]['file_type'], 3)
        self.assertEqual(base64.b64decode(upload[2]['file_data']), audio)
        self.assertEqual(send[1], '/v2/groups/TEST_GROUP/messages')
        self.assertEqual(send[2], {'msg_type': 7, 'content': ' ', 'msg_id': 'incoming-message',
                                   'msg_seq': 1, 'media': {'file_info': 'uploaded-voice'}})

    async def test_render_failure_falls_back_to_text_and_group_is_rate_limited(self):
        with patch('qq_bot.render_voice', side_effect=ValueError('local private path')):
            await self.bot.on_message(qq_bot.GROUP_EVENT, mention(text='/语音 你好'))
        await self.bot.on_message(qq_bot.GROUP_EVENT, {**mention(), 'id': 'too-soon'})
        self.api.request.assert_awaited_once()
        payload = self.api.request.await_args.args[2]
        self.assertEqual(payload['msg_type'], 0)
        self.assertEqual(payload['content'], '语音暂不可用，先回文字：你好呀，群友。')


class QQVoiceRenderTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('pilk'), 'Install requirements-qq.txt to exercise SILK encoding')
    def test_encoder_produces_playable_tencent_silk(self):
        import pilk

        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / 'fixture.wav'
            with wave.open(str(wav), 'wb') as output:
                output.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
                output.writeframes(b'\x00\x00' * 8820)
            self.assertTrue(qq_bot.encode_voice(wav).startswith(b'\x02#!SILK_V3'))
            self.assertEqual(pilk.get_duration(str(wav.with_suffix('.silk'))), 200)

    def test_voice_restores_configured_project_and_deletes_scratch_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            idle = Path(tmp) / 'idle.acep'
            idle.touch()
            current = idle
            generated = None

            def ace(*args, timeout):
                nonlocal current, generated
                if args[:2] == ('project', 'dirty'):
                    return {'dirty': False, 'projectPath': str(current)}
                if args[:2] == ('project', 'open'):
                    current = Path(args[2])
                    return {}
                if args[:2] == ('export', 'audio'):
                    generated = Path(args[3])
                    with wave.open(str(generated), 'wb') as wav:
                        wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                        wav.writeframes(b'\x01\x00' * 2400)
                    return {'jobId': 'fixture'}
                if args[:2] == ('job', 'get'):
                    return {'lifecycle': 'succeeded'}
                self.fail(f'unexpected ACE call: {args[:2]}')

            def encode(path):
                self.assertEqual(current, idle)
                self.assertTrue(path.is_file())
                return b'silk fixture'

            with (patch.object(server.ace_render.platform_support, 'default_data_dir', return_value=Path(tmp)),
                  patch.object(server.ace_render, 'cli', side_effect=ace),
                  patch('qq_bot.encode_voice', side_effect=encode)):
                self.assertEqual(qq_bot.render_voice('你好。', idle), b'silk fixture')
                self.assertEqual(current, idle)
                self.assertFalse(generated.parent.exists())

                current = Path(tmp) / 'different-project.acep'
                with self.assertRaisesRegex(ValueError, '专用工程'):
                    qq_bot.render_voice('你好。', idle)
                self.assertEqual(current.name, 'different-project.acep')


if __name__ == '__main__':
    unittest.main()
