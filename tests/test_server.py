import base64
import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = server.DATA, server.OUTPUTS, server.UPLOADS
        server.DATA = Path(self.temp.name)
        server.OUTPUTS, server.UPLOADS = server.DATA / 'outputs', server.DATA / 'uploads'
        self.http = server.create_server()
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        server.DATA, server.OUTPUTS, server.UPLOADS = self.old
        self.temp.cleanup()

    def post(self, path, payload, origin=None):
        request = urllib.request.Request(self.url + path, json.dumps(payload).encode(),
                                         {'Content-Type': 'application/json', **({'Origin': origin} if origin else {})})
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    def test_document_edits_save_and_reload_preserve_manual_timing(self):
        document = self.post('/api/analyze', {'text': '重重重。你好。'})['document']
        edited = document['sections'][0]['characters'][1]
        edited.update(duration_override_ms=480, pause_override_ms=150, pinyin_override='chong2')
        rebuilt = self.post('/api/analyze', document)['document']
        self.assertEqual(rebuilt['sections'][0]['characters'][1]['duration_ms'], 480)
        self.assertEqual(rebuilt['sections'][0]['characters'][1]['pinyin'], 'chong2')
        saved = self.post('/api/save-document', {'document': rebuilt})
        reread = json.loads(Path(saved['path']).read_text(encoding='utf-8'))
        self.assertEqual(reread['document']['text'], document['text'])
        self.assertEqual(reread['document']['sections'][0]['characters'][1]['pause_after_ms'], 150)

    def test_foreign_origin_and_path_traversal_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post('/api/analyze', {'text': '你好。'}, 'https://example.com')
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(ValueError):
            server.owned_upload('../secrets.txt')
        with self.assertRaises(ValueError):
            server.open_folder(str(Path.home()))

    def test_selected_engine_export_has_only_its_project_file(self):
        document = self.post('/api/analyze', {'text': '你好。'})['document']
        for target, extension in [('ace', '.acep'), ('synthv', '.svp'), ('vocaloid5', '.vsqx'), ('vocaloid6', '.vsqx')]:
            exported = self.post('/api/export', {'document': document, 'target': target})
            actual = [path for path in Path(exported['folder']).rglob('*') if path.is_file()]
            self.assertEqual(len(actual), 1)
            self.assertEqual(len(exported['files']), 1)
            self.assertEqual(actual[0].suffix, extension)
        with self.assertRaises(urllib.error.HTTPError):
            self.post('/api/export', {'document': document, 'target': 'all'})

    def test_synthv_script_copy_creates_no_export_files(self):
        document = self.post('/api/analyze', {'text': '你好。'})['document']
        before = set(server.DATA.rglob('*'))
        copied = self.post('/api/synthv-script', {'document': document})
        self.assertEqual(copied['data']['format'], 'vvtalkstudio-sv2')
        self.assertEqual(len(copied['data']['notes']), 2)
        self.assertEqual(before, set(server.DATA.rglob('*')))

    def test_redirected_data_root_keeps_strict_file_ownership(self):
        logical = server.DATA / 'logical'
        physical = server.DATA / 'physical'
        physical.mkdir()
        old = server.DATA, server.OUTPUTS, server.UPLOADS, server._initialized_data
        original_resolve = Path.resolve

        def redirected_resolve(path, *args, **kwargs):
            if path.parent == logical and path.name.startswith('.path-check-'):
                return physical / path.name
            return original_resolve(path, *args, **kwargs)

        try:
            server.DATA = logical
            server.OUTPUTS, server.UPLOADS = logical / 'outputs', logical / 'uploads'
            with patch.object(Path, 'resolve', redirected_resolve):
                server.initialize()
            self.assertEqual(server.DATA, physical)
            saved = server.save_document({'document': server.analyze_document({'text': '你好。'})['document']})
            self.assertTrue(Path(saved['path']).is_relative_to(physical))
            self.assertFalse(list(logical.glob('.path-check-*')))
            outside = logical / 'outside.json'
            outside.write_text('{}')
            with self.assertRaises(ValueError):
                server.public_file(outside)
        finally:
            server.DATA, server.OUTPUTS, server.UPLOADS, server._initialized_data = old

    def test_data_subdirectory_cannot_resolve_outside_owned_root(self):
        original_resolve = Path.resolve
        outputs = server.OUTPUTS
        with tempfile.TemporaryDirectory() as unrelated:
            outside = Path(unrelated)

            def escaped_resolve(path, *args, **kwargs):
                if path == outputs:
                    return outside
                return original_resolve(path, *args, **kwargs)

            with patch.object(Path, 'resolve', escaped_resolve):
                with self.assertRaisesRegex(ValueError, '输出与上传目录'):
                    server.initialize()

    def test_probe_collision_preserves_existing_file(self):
        existing = server.DATA / '.path-check-existing'
        existing.write_text('preserve this file')
        with patch.object(server.uuid, 'uuid4') as token, patch.object(server, '_initialized_data', None):
            token.return_value.hex = 'existing'
            with self.assertRaises(FileExistsError):
                server.initialize()
        self.assertEqual(existing.read_text(), 'preserve this file')

    def test_range_response_and_upload_extension(self):
        uploaded = self.post('/api/upload', {'name': '对齐.csv', 'kind': 'alignment', 'data': base64.b64encode(b'lyric,start,end\n').decode()})
        request = urllib.request.Request(self.url + uploaded['url'], headers={'Range': 'bytes=0-4'})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b'lyric')
        with self.assertRaises(urllib.error.HTTPError):
            self.post('/api/upload', {'name': 'file.exe', 'kind': 'audio', 'data': 'AAAA'})

    def test_result_validation_does_not_mutate_and_rejects_overlap(self):
        original = server.analyze_document({'text': '你好。'})['result']
        saved = copy.deepcopy(original)
        server.validate_result(original)
        self.assertEqual(original, saved)
        original['notes'][1]['start'] = 0
        with self.assertRaises(ValueError):
            server.validate_result(original)


if __name__ == '__main__':
    unittest.main()
