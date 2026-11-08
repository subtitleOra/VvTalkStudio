"""Package only public source, licenses, generated examples and a tested build."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
MACOS = sys.platform == 'darwin'
os.environ['VVTALK_DATA_DIR'] = str(ROOT / '.qa' / 'release-build-data')
import server

SOURCE_FILES = [
    '.gitignore', '.gitattributes', 'app.py', 'server.py', 'adapters.py',
    'alignment.py', 'selfcheck.py', 'platform_support.py', 'native_engine.py',
    'requirements.txt', 'requirements-lock.txt', 'requirements-qq.txt', 'qq_bot.py',
    'VvTalkStudio.spec', 'build.ps1', 'build.sh', 'package_release.py',
    'sign-release.ps1', 'sign-release-macos.sh',
    'Start-VvTalk.cmd', 'Start-VvTalk.command', 'Stop-VvTalk.cmd',
    'Stop-VvTalk.ps1', 'Stop-VvTalk.command', 'app.ico', 'app.icns',
    'README.md', 'LICENSE', 'LICENSE-NOTICE.md',
]
SOURCE_DIRS = ['core', 'static', 'templates', 'plugins', 'tests', 'docs', 'macOS']


def public_files():
    paths = [ROOT / name for name in SOURCE_FILES]
    for name in SOURCE_DIRS:
        paths.extend(path for path in sorted((ROOT / name).rglob('*'))
                     if path.is_file() and not {'__pycache__', 'xcuserdata', '.DS_Store'}.intersection(path.parts)
                     and path.suffix not in {'.pyc', '.xcuserstate'})
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
    if not executable.exists():
        raise FileNotFoundError(executable)
    if MACOS and executable.suffix != '.app':
        raise ValueError('macOS 发行需要 PyInstaller 生成的 VvTalkStudio.app。')
    if MACOS:
        with (executable / 'Contents' / 'Info.plist').open('rb') as stream:
            if plistlib.load(stream).get('CFBundleIdentifier') == 'studio.vvtalk.native':
                raise ValueError('此脚本生成旧版发行结构。原生版的本地构建产物为 dist/VvTalkStudioNative.app。')
    if not MACOS and not executable.is_file():
        raise ValueError('Windows 发行需要 VvTalkStudio.exe。')
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    source_paths = public_files()
    source = dist / f'VvTalkStudio-{server.VERSION}-source.zip'
    archive(source_paths, source, ROOT)
    release = ROOT / 'release' / f'VvTalkStudio-{server.VERSION}'
    # A fresh directory prevents stale user files from entering a public archive.
    release.mkdir(parents=True, exist_ok=False)
    if MACOS:
        shutil.copytree(executable, release / 'VvTalkStudio.app', symlinks=True)
        for name in ['Start-VvTalk.command', 'Stop-VvTalk.command', 'sign-release-macos.sh',
                     'README.md', 'LICENSE', 'LICENSE-NOTICE.md']:
            shutil.copy2(ROOT / name, release / name)
    else:
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
    if MACOS:
        portable = dist / f'VvTalkStudio-{server.VERSION}-macOS-{platform.machine()}.zip'
        # ditto preserves bundle symlinks and executable bits.
        subprocess.run(['ditto', '-c', '-k', '--norsrc', '--noextattr', '--keepParent',
                        str(release), str(portable)], check=True)
        checksum_inputs = [portable, source]
    else:
        portable = dist / f'VvTalkStudio-{server.VERSION}-Windows-x64.zip'
        archive(sorted(path for path in release.rglob('*') if path.is_file()), portable, release.parent)
        checksum_inputs = [portable, source]
    checksum_path = dist / 'SHA256SUMS.txt'
    checksum_path.write_text(''.join(digest(path) + '  ' + path.name + '\n'
                                      for path in checksum_inputs), encoding='ascii')
    artifacts = [{'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest(path)}
                 for path in checksum_inputs + [checksum_path]]
    if not MACOS:
        artifacts.insert(0, {'path': str(executable), 'bytes': executable.stat().st_size,
                             'sha256': digest(executable)})
    manifest = {
        'version': server.VERSION, 'public_package': True,
        'platform': 'macOS-' + platform.machine() if MACOS else 'Windows-x64',
        'portable_directory': str(release),
        'source_files': [{'path': path.relative_to(ROOT).as_posix(), 'sha256': digest(path)}
                         for path in source_paths],
        'artifacts': artifacts,
    }
    (dist / 'release-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'version': server.VERSION, 'source_files': len(source_paths),
                      'artifacts': manifest['artifacts']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True,
                        help='VvTalkStudio.exe (Windows) or VvTalkStudio.app (macOS)')
    main(parser.parse_args().exe)
