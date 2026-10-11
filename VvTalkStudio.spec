from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH)
datas = [(str(root / 'static'), 'static'), (str(root / 'templates'), 'templates'),
         (str(root / 'plugins'), 'plugins'), (str(root / 'docs'), 'docs'),
         (str(root / 'core/ace_language_cache.json'), 'core')]
datas += collect_data_files('pypinyin')
datas += collect_data_files('unidic_lite') + collect_data_files('cmudict')
datas += copy_metadata('cmudict', recursive=True)
fugashi_datas, fugashi_binaries, fugashi_hidden = collect_all('fugashi')
datas += fugashi_datas
hidden = collect_submodules('webview') + fugashi_hidden + ['selfcheck', 'pronunciation', 'ace_render', 'languages']
analysis = Analysis([str(root / 'app.py')], pathex=[str(root), str(root / 'core')],
                    binaries=fugashi_binaries, datas=datas, hiddenimports=hidden,
                    hookspath=[], hooksconfig={}, runtime_hooks=[],
                    excludes=['tkinter', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'cefpython3', 'scipy', 'matplotlib', 'pytest'],
                    noarchive=False)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
          name='VvTalkStudio', debug=False, bootloader_ignore_signals=False,
          strip=False, upx=False, console=False, disable_windowed_traceback=False,
          icon=str(root / 'app.ico'))
