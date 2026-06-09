# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for AxEdUp desktop app.

Build with:
    pyinstaller axedup.spec

Output: dist/axedup/axedup  (onedir mode)
"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)

# ── Data files ────────────────────────────────────────────────────────────────
datas = []

# Alembic migration scripts (needed for first-run DB setup)
datas += [(str(ROOT / 'axedup' / 'models' / 'migrations'), 'axedup/models/migrations')]

# alembic.ini (read by main.py in dev mode; bundled for reference)
datas += [(str(ROOT / 'alembic.ini'), '.')]

# Sport presets and LUTs
datas += [(str(ROOT / 'axedup' / 'presets'), 'axedup/presets')]

# imageio-ffmpeg bundled binary (collect_data_files handles path discovery)
datas += collect_data_files('imageio_ffmpeg')

# NiceGUI web assets (hook-nicegui.py in hooks-contrib does this too, but be explicit)
datas += collect_data_files('nicegui')

# ── Hidden imports ────────────────────────────────────────────────────────────
hiddenimports = []

# pywebview GTK backend (Linux)
hiddenimports += ['webview.platforms.gtk']

# NiceGUI dynamic module loading
hiddenimports += collect_submodules('nicegui')

# Alembic migration env imports
hiddenimports += ['alembic.runtime.migration', 'alembic.operations', 'alembic.script']

# SQLAlchemy dialects
hiddenimports += ['sqlalchemy.dialects.sqlite']

# CV2 and scenedetect
hiddenimports += ['cv2', 'scenedetect', 'scenedetect.backends', 'scenedetect.backends.opencv']

# pkg_resources / setuptools runtime
hiddenimports += ['appdirs', 'pkg_resources', 'pkg_resources.extern']

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / 'axedup' / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'notebook', 'IPython',
        'pandas', 'scipy', 'PIL', 'pytest',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='axedup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # no terminal window; errors go to ~/.cache/axedup/axedup.log
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='axedup',
)
