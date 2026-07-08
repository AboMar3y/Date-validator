# build.spec
#
# PyInstaller spec file for packaging Date Range Validator as a standalone
# Windows executable. Build with:
#
#     pyinstaller build.spec
#
# The output .exe will be in dist/DateRangeValidator/.
#
# Tesseract bundling: set the TESSERACT_BUNDLE_DIR environment variable to
# a Tesseract-OCR install directory (e.g. "C:\Program Files\Tesseract-OCR")
# before running pyinstaller, and that entire folder — binary, DLLs, and
# language data — will be copied into the build alongside the app. Paired
# with config.py's auto-detection of a bundled Tesseract, this produces a
# .exe that needs zero separate installs on the machine that runs it. This
# is exactly what .github/workflows/build-windows-exe.yml does. Leave the
# variable unset for a lighter build that expects Tesseract already
# installed on the target machine (see README.md).

# -*- mode: python ; coding: utf-8 -*-

import os

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'easyocr',
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DateRangeValidator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # no terminal window; this is a GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # point this at a .ico file for a custom taskbar icon
)

# Optionally bundle an entire Tesseract-OCR installation into the build
# (see the module docstring above for how this gets triggered).
_extra_trees = []
_tesseract_dir = os.environ.get('TESSERACT_BUNDLE_DIR', '')
if _tesseract_dir and os.path.isdir(_tesseract_dir):
    _extra_trees.append(Tree(_tesseract_dir, prefix='Tesseract-OCR'))

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    *_extra_trees,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DateRangeValidator',
)
