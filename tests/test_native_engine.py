import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import native_engine


def request(action, payload):
    body = json.dumps({'action': action, 'payload': payload}).encode()
    return struct.pack('>I', len(body)) + body


class NativeEngineTests(unittest.TestCase):
    def test_pipe_keeps_working_after_invalid_project_and_exports_svp(self):
        with tempfile.TemporaryDirectory() as data:
            valid = {'language': 'en', 'title': 'English demo', 'text': 'Hello there.'}
            response = subprocess.run([sys.executable, str(ROOT / 'native_engine.py')],
                                      input=(request('analyze', {'text': ''}) + request('analyze', valid)
                                             + request('export', {'document': valid, 'target': 'synthv'})),
                                      capture_output=True, check=True, timeout=30,
                                      env={**os.environ, 'VVTALK_DATA_DIR': data}).stdout
            decoded, offset = [], 0
            while offset < len(response):
                size, = struct.unpack_from('>I', response, offset)
                offset += 4
                decoded.append(json.loads(response[offset:offset + size]))
                offset += size
            error, analyzed, exported = decoded
            self.assertIn('error', error)
            self.assertEqual(analyzed['value']['result']['language'], 'en')
            self.assertEqual(len(analyzed['value']['result']['notes']), 2)
            files = exported['value']['files']
            self.assertEqual(len(files), 1)
            self.assertTrue(Path(files[0]['path']).is_file())
            self.assertEqual(Path(files[0]['path']).suffix, '.svp')

    def test_full_text_edit_preserves_timing_of_unchanged_sentence(self):
        draft = native_engine.analyze_workbench({'text': '你好。再见。'})['document']
        kept = draft['sections'][1]
        kept['characters'][0]['duration_override_ms'] = 480
        draft['text'] = '早上好。再见。'
        rebuilt = native_engine.analyze_workbench(draft)['document']
        self.assertEqual(rebuilt['sections'][1]['id'], kept['id'])
        self.assertEqual(rebuilt['sections'][1]['characters'][0]['duration_ms'], 480)
        self.assertEqual(rebuilt['sections'][0]['text'], '早上好。')

    def test_native_project_reopens_with_legacy_shape(self):
        draft = native_engine.analyze_workbench({'language': 'ja', 'text': 'こんにちは。'})['document']
        saved = native_engine.project({'document': draft, 'title': '例'})
        self.assertEqual(saved['format'], 'vvtalk-studio')
        reopened = native_engine.open_project({'project': saved})
        self.assertEqual(reopened['result']['language'], 'ja')
        self.assertEqual(reopened['result']['curve'], saved['result']['curve'])


if __name__ == '__main__':
    unittest.main()
