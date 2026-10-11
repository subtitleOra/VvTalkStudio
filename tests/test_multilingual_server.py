import base64
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'core'))
import alignment
import server
from test_reference import recording


class MultilingualServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_result_language_is_validated_without_mutation(self):
        for language, text in [('ja', '今日は、一緒に帰りましょう。'), ('en', 'Hello, are you coming home?')]:
            original = server.analyze_document({'text': text, 'language': language})['result']
            before = copy.deepcopy(original)
            validated = server.validate_result(original)
            self.assertEqual(validated['language'], language)
            self.assertEqual(original, before)
            original['notes'][0]['language'] = 'zh'
            with self.assertRaisesRegex(ValueError, '语言'):
                server.validate_result(original)
        with self.assertRaises(ValueError):
            server.analyze_document({'text': 'Hallo.', 'language': 'de'})

    def test_manual_alignment_checks_words_and_mora_not_han_count(self):
        for language, text, labels in [('en', 'Hello world!', ['HELLO', 'world']), ('ja', 'はな。', ['ハ', 'ナ'])]:
            path = self.root / (language + '.csv')
            path.write_text('lyric,start,end\n' + f'{labels[0]},0,0.8\n{labels[1]},1.1,1.9\n', encoding='utf-8')
            intervals = server.read_alignment(path, text, language)
            self.assertEqual(len(intervals), 2)
            self.assertEqual(intervals[1]['start'], 1.1)
            path.write_text('lyric,start,end\nwrong,0,0.8\nwrong,1.1,1.9\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '不一致'):
                server.read_alignment(path, text, language)

    def test_reference_pitch_preserves_language_and_manual_silence(self):
        sound = recording(self.root / 'test.wav')
        with patch.multiple(server, DATA=self.root, OUTPUTS=self.root / 'outputs', UPLOADS=self.root / 'uploads'):
            audio = server.upload({'name': 'test.wav', 'kind': 'audio', 'data': base64.b64encode(sound.read_bytes()).decode()})
            for language, text, lyrics in [('ja', 'はな。', ['は', 'な']), ('en', 'Hello world!', ['Hello', 'world'])]:
                csv = ('lyric,start,end\n' + f'{lyrics[0]},0,0.8\n{lyrics[1]},1.1,1.9\n').encode()
                marks = server.upload({'name': 'timing.csv', 'kind': 'alignment', 'data': base64.b64encode(csv).decode()})
                response = server.reference({'audio_id': audio['id'], 'alignment_id': marks['id'], 'text': text,
                                             'language': language, 'pitch_mode': 'absolute', 'settings': {'smoothing_ms': 0}})
                result = response['result']
                self.assertEqual(result['language'], language)
                self.assertEqual(result['notes'][1]['start'], 1.1)
                self.assertTrue(all(p['pitch'] is None for p in result['curve'] if .9 < p['time'] < 1))
                saved = server.save_document({'result': result})
                reread = json.loads(Path(saved['path']).read_text(encoding='utf-8'))
                self.assertEqual(reread['result']['language'], language)
                self.assertEqual(reread['result']['curve'], result['curve'])

    def test_non_chinese_mfa_never_uses_mandarin_resources(self):
        with patch.dict('os.environ', {'VVTALK_SOURCE': str(self.root)}, clear=False):
            for language in ('ja', 'en'):
                found = alignment.detect_alignment(language)
                self.assertFalse(found['available'])
                self.assertNotIn('mandarin', found['model'])
                self.assertEqual(found['language'], language)
        lexicon = self.root / 'english.dict'
        lexicon.write_text('hello HH AH0 L OW1\nworld W ER1 L D\n', encoding='utf-8')
        words, tokens = alignment.language_tokens('Hello world!', lexicon, 'en')
        self.assertEqual(words, ['Hello', 'world'])
        self.assertEqual(tokens, ['hello', 'world'])
        with self.assertRaisesRegex(ValueError, '缺少'):
            alignment.language_tokens('Hello friend!', lexicon, 'en')

    def test_reference_word_readings_and_unit_overrides_are_forwarded(self):
        sound = recording(self.root / 'custom.wav')
        with patch.multiple(server, DATA=self.root, OUTPUTS=self.root / 'outputs', UPLOADS=self.root / 'uploads'):
            audio = server.upload({'name': 'custom.wav', 'kind': 'audio', 'data': base64.b64encode(sound.read_bytes()).decode()})
            result = server.reference({'audio_id': audio['id'], 'text': '今日は。', 'language': 'ja',
                                       'word_readings': {'0': 'コンニチ'}, 'unit_overrides': [
                                           {'pronunciation_override': 'カ'}, {}, {}, {}, {}]})['result']
            self.assertEqual(len(result['notes']), 5)
            self.assertEqual(result['word_readings'], {'0': 'コンニチ'})
            self.assertEqual(result['notes'][0]['reading'], 'か')
            server.validate_result(result)


if __name__ == '__main__':
    unittest.main()
