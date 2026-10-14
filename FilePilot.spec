# Build on Windows with: python -m PyInstaller --noconfirm FilePilot.spec
from pathlib import Path

project = Path(SPECPATH)
a = Analysis(
    [str(project / 'run.py')], pathex=[str(project / 'src')],
    binaries=[], datas=[(str(project / 'LICENSE'), '.'), (str(project / 'README.md'), '.'),
                       (str(project / 'THIRD_PARTY.md'), '.'), (str(project / 'third_party'), 'third_party'),
                       (str(project / 'src' / 'filepilot' / 'assets'), 'filepilot/assets')],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'numpy', 'scipy', 'pandas', 'matplotlib', 'IPython', 'tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='FilePilot', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False, icon=str(project / 'src' / 'filepilot' / 'assets' / 'filepilot.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='FilePilot')
