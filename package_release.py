"""Package only public source, licenses, generated examples and a tested EXE."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent
os.environ['VVTALK_DATA_DIR'] = str(ROOT / '.qa' / 'release-build-data')
import server

SOURCE_FILES = [
    '.gitignore', '.gitattributes', 'app.py', 'server.py', 'adapters.py',
    'alignment.py', 'selfcheck.py', 'requirements.txt', 'requirements-lock.txt',
    'VvTalkStudio.spec', 'build.ps1', 'package_release.py', 'sign-release.ps1',
    'Start-VvTalk.cmd', 'Stop-VvTalk.cmd', 'Stop-VvTalk.ps1', 'app.ico',
    'README.md', 'LICENSE', 'LICENSE-NOTICE.md',
]
SOURCE_DIRS = ['core', 'static', 'templates', 'plugins', 'tests', 'docs']


def public_files():
    paths = [ROOT / name for name in SOURCE_FILES]
    for name in SOURCE_DIRS:
        paths.extend(path for path in sorted((ROOT / name).rglob('*'))
                     if path.is_file() and '__pycache__' not in path.parts
                     and path.suffix != '.pyc')
    if any(not path.is_file() for path in paths):
        raise FileNotFoundError('A required public source file is missing.')
    return paths


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def archive(paths, destination, base):
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as stream:
        for path in paths:
            stream.write(path, path.relative_to(base).as_posix())


def main(executable):
    executable = Path(executable).resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    source_paths = public_files()
    source = dist / f'VvTalkStudio-{server.VERSION}-source.zip'
    archive(source_paths, source, ROOT)
    release = ROOT / 'release' / f'VvTalkStudio-{server.VERSION}'
    # A fresh directory prevents stale user files from entering a public archive.
    release.mkdir(parents=True, exist_ok=False)
    shutil.copy2(executable, release / 'VvTalkStudio.exe')
    for name in ['Start-VvTalk.cmd', 'Stop-VvTalk.cmd', 'Stop-VvTalk.ps1',
                 'README.md', 'LICENSE', 'LICENSE-NOTICE.md']:
        shutil.copy2(ROOT / name, release / name)
    for name in ['docs', 'plugins']:
        shutil.copytree(ROOT / name, release / name)
    shutil.copy2(source, release / source.name)
    for language, title, text in [
        ('zh', '中文文字语调', '今天，我们一起回家吧。明天再见。'),
        ('ja', '日语文字语调', '今日は、一緒に帰りましょう。'),
        ('en', '英语文字语调', 'Hello, are you coming home?'),
    ]:
        document = server.analyze_document({'title': title, 'text': text, 'language': language})
        for target in ['ace', 'synthv', 'vocaloid5', 'vocaloid6']:
            exported = server.do_export({'document': document['document'], 'target': target})
            shutil.copytree(exported['folder'], release / 'Examples' / title / target)
    portable = dist / f'VvTalkStudio-{server.VERSION}-Windows-x64.zip'
    archive(sorted(path for path in release.rglob('*') if path.is_file()), portable, release.parent)
    checksum_path = dist / 'SHA256SUMS.txt'
    checksum_path.write_text(''.join(digest(path) + '  ' + path.name + '\n'
                                      for path in [portable, source]), encoding='ascii')
    manifest = {
        'version': server.VERSION, 'public_package': True,
        'portable_directory': str(release),
        'source_files': [{'path': path.relative_to(ROOT).as_posix(), 'sha256': digest(path)}
                         for path in source_paths],
        'artifacts': [{'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest(path)}
                      for path in [executable, source, portable, checksum_path]],
    }
    (dist / 'release-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'version': server.VERSION, 'source_files': len(source_paths),
                      'artifacts': manifest['artifacts']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    main(parser.parse_args().exe)
