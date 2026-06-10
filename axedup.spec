# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for AxEdUp desktop app.  Cross-platform: Linux, Windows, macOS.

Build with:
    pyinstaller axedup.spec

Output (Linux/Windows): dist/axedup/axedup[.exe]  (onedir mode)
Output (macOS):         dist/AxEdUp.app             (app bundle)
"""
import re as _re
import sys as _sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH)

# Read version from source so the macOS bundle info_plist stays in sync
_VERSION = _re.search(
    r'__version__\s*=\s*["\']([^"\']+)["\']',
    (ROOT / 'axedup' / '__init__.py').read_text(),
).group(1)

# ── Data files ────────────────────────────────────────────────────────────────
datas = []

# Alembic migration scripts (needed for first-run DB setup)
datas += [(str(ROOT / 'axedup' / 'models' / 'migrations'), 'axedup/models/migrations')]

# alembic.ini (bundled for reference)
datas += [(str(ROOT / 'alembic.ini'), '.')]

# Sport presets and LUTs
datas += [(str(ROOT / 'axedup' / 'presets'), 'axedup/presets')]

# imageio-ffmpeg bundled binary
datas += collect_data_files('imageio_ffmpeg')

# NiceGUI web assets
datas += collect_data_files('nicegui')

# ── Hidden imports ────────────────────────────────────────────────────────────
hiddenimports = []

# pywebview backend — platform-specific
if _sys.platform == 'win32':
    hiddenimports += ['webview.platforms.edgechromium', 'webview.platforms.winforms']
elif _sys.platform == 'darwin':
    hiddenimports += ['webview.platforms.cocoa']
else:
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

# ── Icon ──────────────────────────────────────────────────────────────────────
if _sys.platform == 'win32':
    _icon_path = ROOT / 'packaging' / 'axedup.ico'
elif _sys.platform == 'darwin':
    _icon_path = ROOT / 'packaging' / 'axedup.icns'
else:
    _icon_path = None

_icon = str(_icon_path) if _icon_path and _icon_path.exists() else None

# ── UPX — skip on Windows (AV false-positive risk) ───────────────────────────
_upx = _sys.platform != 'win32'

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
    upx=_upx,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=_upx,
    upx_exclude=[],
    name='axedup',
)

# macOS: wrap COLLECT output in a .app bundle
if _sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='AxEdUp.app',
        icon=_icon,
        bundle_identifier='org.vinodkd.axedup',
        info_plist={
            'CFBundleName': 'AxEdUp',
            'CFBundleDisplayName': 'AxEdUp',
            'CFBundleShortVersionString': _VERSION,
            'CFBundleVersion': _VERSION,
            'NSHighResolutionCapable': True,
            'LSBackgroundOnly': False,
        },
    )
