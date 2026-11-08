"""Build the Windows executable or the macOS application bundle."""
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH)
VERSION = '1.1.2'
native_engine = sys.platform == 'darwin' and os.environ.get('VVTALK_NATIVE_ENGINE') == '1'
datas = [(str(root / 'templates'), 'templates'), (str(root / 'plugins'), 'plugins'),
         (str(root / 'core/ace_language_cache.json'), 'core')]
if not native_engine:
    datas += [(str(root / 'static'), 'static'), (str(root / 'docs'), 'docs')]
datas += collect_data_files('pypinyin')
datas += collect_data_files('unidic_lite') + collect_data_files('cmudict')
datas += copy_metadata('cmudict', recursive=True)
fugashi_datas, fugashi_binaries, fugashi_hidden = collect_all('fugashi')
datas += fugashi_datas
hidden = fugashi_hidden + ['pronunciation', 'ace_render', 'languages']
if not native_engine:
    hidden += collect_submodules('webview') + ['selfcheck']
entry = 'native_engine.py' if native_engine else 'app.py'
analysis = Analysis([str(root / entry)], pathex=[str(root), str(root / 'core')],
                    binaries=fugashi_binaries, datas=datas, hiddenimports=hidden,
                    hookspath=[], hooksconfig={}, runtime_hooks=[],
                    excludes=['tkinter', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'cefpython3', 'scipy', 'matplotlib', 'pytest'],
                    noarchive=False)
pyz = PYZ(analysis.pure)
icon = root / ('app.icns' if sys.platform == 'darwin' else 'app.ico')
if native_engine:
    exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True,
              name='VvTalkEngine', console=True, upx=False)
    collect = COLLECT(exe, analysis.binaries, analysis.datas, [], upx=False, name='VvTalkEngine')
    app = BUNDLE(collect, name='VvTalkEngine.app', bundle_identifier='studio.vvtalk.native.engine',
                 info_plist={'LSBackgroundOnly': True, 'LSMinimumSystemVersion': '14.0'})
elif sys.platform == 'darwin':
    # A .app bundle must be a directory; onedir keeps startup fast and lets
    # codesign seal the whole bundle without onefile extraction each launch.
    exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True,
              name='VvTalkStudio', debug=False, bootloader_ignore_signals=False,
              strip=False, upx=False, console=False, disable_windowed_traceback=False,
              icon=str(icon))
    collect = COLLECT(exe, analysis.binaries, analysis.datas, [],
                      strip=False, upx=False, name='VvTalkStudio')
    app = BUNDLE(collect, name='VvTalkStudio.app', icon=str(icon),
                 bundle_identifier='studio.vvtalk.app',
                 info_plist={'CFBundleDisplayName': 'VvTalk Studio',
                             'CFBundleShortVersionString': VERSION,
                             'CFBundleVersion': VERSION,
                             'CFBundleName': 'VvTalk Studio',
                             'LSMinimumSystemVersion': '12.0',
                             'LSApplicationCategoryType': 'public.app-category.music',
                             'NSHighResolutionCapable': True,
                             'NSMicrophoneUsageDescription': '用于录制参考示读音频；也可以改为上传 WAV 文件。',
                             'NSHumanReadableCopyright': 'GPL-3.0-or-later'})
else:
    exe = EXE(pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
              name='VvTalkStudio', debug=False, bootloader_ignore_signals=False,
              strip=False, upx=False, console=False, disable_windowed_traceback=False,
              icon=str(icon))
