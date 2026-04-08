# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

# Incluir todos los archivos de datos de sklearn (CSS, JS, etc.)
sklearn_datas = collect_data_files('sklearn', includes=['**/*.css', '**/*.js', '**/*.html'])

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('index.html', '.'), ('engine', 'engine')] + sklearn_datas,
    hiddenimports=['sklearn.ensemble._gb', 'sklearn.ensemble._forest', 'sklearn.tree', 'pystray', 'PIL', 'certifi'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WarzoneAudioEnhancer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
