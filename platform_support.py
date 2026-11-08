"""Operating-system locations and process conventions used by VvTalk Studio.

Windows keeps the 1.1.x behaviour. macOS uses native application locations and
process APIs so the same source tree can run from a checkout, a virtual
environment, or a ``.app`` bundle. Every function resolves its environment at
call time, which keeps ``VVTALK_*`` overrides and tests predictable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = 'VvTalkStudio'
IS_WINDOWS = os.name == 'nt'
IS_MACOS = sys.platform == 'darwin'


def data_dir() -> Path:
    """Return the per-user data directory, honouring ``VVTALK_DATA_DIR``."""
    override = os.environ.get('VVTALK_DATA_DIR')
    return Path(override).expanduser() if override else default_data_dir()


def default_data_dir() -> Path:
    if IS_WINDOWS:
        base = os.environ.get('USERPROFILE') or str(Path.home())
        return Path(base) / 'AppData' / 'Local' / APP_NAME
    if IS_MACOS:
        return Path.home() / 'Library' / 'Application Support' / APP_NAME
    base = os.environ.get('XDG_DATA_HOME')
    return (Path(base).expanduser() if base else Path.home() / '.local' / 'share') / APP_NAME


def try_file_lock(path: Path):
    """Return an open file that owns the lock, or None if a lock cannot be obtained."""
    handle = path.open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0, 2)
            if not handle.tell():
                handle.write(b'\0')
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _first_existing(candidates):
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _home_app(name: str) -> Path:
    return Path.home() / 'Applications' / name


def host_paths() -> dict[str, Path]:
    """Return the editor/engine locations used for the "installed" report."""
    if IS_WINDOWS:
        program_files = Path(os.environ.get('ProgramFiles', r'C:\Program Files'))
        return {
            'ace': program_files / 'ACE Studio' / 'ACE Studio.exe',
            'synthv': program_files / 'Synthesizer V Studio 2 Pro' / 'synthv-studio.exe',
            'vocaloid6': program_files / 'VOCALOID6' / 'Editor' / 'VOCALOID6.exe',
        }
    if IS_MACOS:
        return {
            'ace': _first_existing([Path('/Applications/ACE Studio.app'), _home_app('ACE Studio.app')]),
            'synthv': _first_existing([Path('/Applications/Synthesizer V Studio 2 Pro.app'),
                                       _home_app('Synthesizer V Studio 2 Pro.app')]),
            'vocaloid6': _first_existing([Path('/Applications/VOCALOID6 Editor.app'),
                                          Path('/Applications/VOCALOID6.app'),
                                          _home_app('VOCALOID6 Editor.app')]),
        }
    return {
        'ace': Path('/opt/ACE Studio/ACE Studio.AppImage'),
        'synthv': Path('/opt/Synthesizer V Studio 2 Pro/synthv-studio'),
        'vocaloid6': Path('/opt/VOCALOID6/Editor/VOCALOID6'),
    }


def installed(path) -> bool:
    """Editors are ``.app`` directories on macOS but executables elsewhere."""
    return Path(path).exists()


def ace_cli_candidates() -> list[Path]:
    candidates: list[Path] = []
    override = os.environ.get('VVTALK_ACE_CLI')
    if override:
        candidates.append(Path(override).expanduser())
    if IS_MACOS:
        for bundle in (Path('/Applications/ACE Studio.app'), _home_app('ACE Studio.app')):
            candidates.extend([bundle / 'Contents/Helpers/acestudio-cli',
                               bundle / 'Contents/MacOS/acestudio-cli'])
    elif IS_WINDOWS:
        for base in (os.environ.get('ProgramFiles', r'C:\Program Files'),
                     os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
                     str(Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'Programs')):
            if base:
                candidates.append(Path(base) / 'ACE Studio' / 'acestudio-cli.exe')
    else:
        found = shutil.which('acestudio-cli')
        if found:
            candidates.append(Path(found))
        candidates.extend([Path('/opt/ACE Studio/acestudio-cli'),
                           Path('/usr/local/bin/acestudio-cli')])
    return candidates


def ace_cli_path() -> Path:
    """Return the ACE bridge CLI, or the expected path when it is missing."""
    candidates = ace_cli_candidates()
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def synthv_scripts_dir() -> Path:
    """Return the Synthesizer V Studio 2 user scripts folder."""
    override = os.environ.get('VVTALK_SV_SCRIPTS_DIR')
    if override:
        return Path(override).expanduser()
    if IS_WINDOWS:
        base = Path(os.environ.get('APPDATA') or (Path.home() / 'AppData' / 'Roaming'))
        return base / 'Dreamtonics' / 'Synthesizer V Studio 2' / 'scripts'
    if IS_MACOS:
        return Path.home() / 'Library' / 'Application Support' / 'Dreamtonics' / 'Synthesizer V Studio 2' / 'scripts'
    return Path.home() / '.config' / 'Dreamtonics' / 'Synthesizer V Studio 2' / 'scripts'


def creation_flags() -> int:
    """Hide console windows on Windows; other platforms need no special flag."""
    return int(getattr(subprocess, 'CREATE_NO_WINDOW', 0)) if IS_WINDOWS else 0


def open_path(path) -> None:
    """Open a folder in Explorer, Finder, or the desktop's file manager."""
    target = str(path)
    if IS_WINDOWS:
        os.startfile(target)  # type: ignore[attr-defined]
        return
    command = ['open', target] if IS_MACOS else ['xdg-open', target]
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def pywebview_gui():
    """Select the native webview backend installed with pywebview."""
    if IS_MACOS:
        return 'cocoa'
    if IS_WINDOWS:
        return 'edgechromium'
    return None


def webview_start_options(storage_path) -> dict:
    """Return extra ``webview.start`` arguments supported by each backend."""
    options: dict = {}
    gui = pywebview_gui()
    if gui:
        options['gui'] = gui
    if IS_WINDOWS:
        # WebView2 keeps localStorage and window state in the data directory.
        options.update(private_mode=False, storage_path=str(storage_path))
    elif IS_MACOS:
        # WKWebView ignores storage_path but persists in its default data store
        # unless private mode clears cookies and local storage at every start.
        options.update(private_mode=False)
    return options
