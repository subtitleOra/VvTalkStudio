"""Exercise frozen dependencies and each independent native project export."""
import json
from pathlib import Path
import server


def run():
    from native_acep import read_acep
    languages = {}
    for language, text in [('zh', '今天，我们一起回家吧。明天再见。'),
                           ('ja', '今日は、一緒に帰りましょう。'),
                           ('en', 'Hello, are you coming home?')]:
        response = server.analyze_document({'title': '打包验证', 'text': text, 'language': language})
        result, document = response['result'], response['document']
        exports = {}
        for target, extension in [('ace', '.acep'), ('synthv', '.svp'),
                                  ('vocaloid5', '.vsqx'), ('vocaloid6', '.vsqx')]:
            exported = server.do_export({'document': document, 'target': target})
            folder = Path(exported['folder'])
            files = [path for path in folder.rglob('*') if path.is_file()]
            assert len(files) == len(exported['files']) == 1 and files[0].suffix == extension
            if target == 'ace':
                native = read_acep(files[0])
                patterns = native['tracks'][0]['patterns']
                notes = [note for pattern in patterns for note in pattern['notes']]
                assert notes and all(note['language'] == {'zh': 'CHN', 'ja': 'JPN', 'en': 'ENG'}[language] for note in notes)
                assert all(pattern['parameters']['pitchDelta'] for pattern in patterns)
                native_notes = len(notes)
            elif target == 'synthv':
                native = json.loads(files[0].read_text(encoding='utf-8').rstrip('\0'))
                assert native['tracks']
            else:
                native = server.validate_result(server.read_vsqx(files[0], language=language))
                assert native['language'] == language and len(native['notes']) == len(result['notes'])
            exports[target] = str(files[0])
        copied = server.synthv_script({'document': document})
        assert copied['data']['language'] == language and copied['data']['segments']
        languages[language] = {'units': len(result['notes']), 'native_ace_notes': native_notes,
                               'pitch_points': len(result['curve']), 'exports': exports}
    return {'passed': True, 'version': server.VERSION, 'languages': languages,
            'single_project_per_export': True, 'formats': ['.acep', '.svp', '.vsqx']}
