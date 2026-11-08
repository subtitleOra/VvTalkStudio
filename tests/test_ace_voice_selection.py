import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_engine
import server
from native_acep import read_acep
from pronunciation import available_ace_voices


def ace_inventory(arguments, _message):
    if arguments == ['voice', 'synth-models']:
        return {'models': [{'id': 13, 'name': 'Verse24', 'supportedLanguages': ['Chinese', 'Japanese']}]}
    if arguments[:2] == ['voice', 'seeds']:
        return {'seeds': [{'name': '测试声库', 'code': 42, 'ref': 'seed:42'},
                          {'name': '重复声库', 'code': 7, 'ref': 'seed:7'},
                          {'name': '重复声库', 'code': 8, 'ref': 'seed:8'}]}
    return {'soundSources': [
        {'id': 99, 'ref': 'singer:99', 'name': '测试声库', 'nativeLanguage': 'Chinese',
         'supportedLanguages': ['Chinese']},
        {'id': 100, 'ref': 'singer:100', 'name': '重复声库', 'supportedLanguages': ['Chinese']},
    ]}


class ACEVoiceSelectionTests(unittest.TestCase):
    def test_selected_voice_is_revalidated_exported_and_saved(self):
        with tempfile.TemporaryDirectory() as directory, patch('pronunciation.ace_read', side_effect=ace_inventory):
            voices = available_ace_voices('zh')
            self.assertEqual([v['key'] for v in voices], ['13:99:42'])
            draft = native_engine.analyze_workbench({'text': '你好。'})['document']
            saved = native_engine.project({'document': draft, 'ace_voice': voices[0]['key']})
            self.assertEqual(native_engine.open_project({'project': saved})['ace_voice'], '13:99:42')

            with (patch.object(server, 'DATA', Path(directory)),
                  patch.object(server, '_initialized_data', None)):
                output = server.do_export({'document': draft, 'target': 'ace', 'ace_voice': '13:99:42'})
                track = read_acep(Path(output['files'][0]['path']))['tracks'][0]
                singer = track['singers'][0]['singer']
                self.assertEqual((singer['id'], singer['router'], singer['composition'][0]['code']), (99, 13, 42))
                with self.assertRaisesRegex(ValueError, '不可用'):
                    server.do_export({'document': draft, 'target': 'ace', 'ace_voice': '13:100:7'})

    def test_reference_project_retains_voice_selection(self):
        result = native_engine.analyze_workbench({'text': '你好。'})['result']
        saved = native_engine.project({'result': result, 'ace_voice': '13:99:42'})
        self.assertEqual(native_engine.open_project({'project': saved})['ace_voice'], '13:99:42')

    def test_preview_uses_selected_voice(self):
        with tempfile.TemporaryDirectory() as directory, patch('pronunciation.ace_read', side_effect=ace_inventory):
            draft = native_engine.analyze_workbench({'text': '你好。'})['document']

            def start_render(_document, exported, **_options):
                track = read_acep(Path(exported['files']['acep']))['tracks'][0]
                singer = track['singers'][0]['singer']
                self.assertEqual((singer['id'], singer['composition'][0]['code']), (99, 42))
                return {'id': 'test-job'}

            with patch.object(server.ace_render, 'start_render', side_effect=start_render):
                job = server.preview({'document': draft, 'ace_voice': '13:99:42'}, folder=Path(directory))
            self.assertEqual(job['id'], 'test-job')


if __name__ == '__main__':
    unittest.main()
