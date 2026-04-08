# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec para Warzone Audio Enhancer
# Genera: dist/WarzoneAudioEnhancer.exe

import certifi

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Empaquetar la interfaz web dentro del .exe
        ('index.html', '.'),
        # Certificados SSL para urllib (check_for_updates) — ruta dinámica
        (certifi.where(), 'certifi'),
    ],
    hiddenimports=[
        # pywebview (ventana de escritorio)
        'webview',
        'webview.platforms',
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',
        'webview.platforms.mshtml',
        'clr',
        # scikit-learn
        'sklearn',
        'sklearn.ensemble',
        'sklearn.ensemble._forest',
        'sklearn.ensemble._gb',
        'sklearn.tree',
        'sklearn.tree._classes',
        'sklearn.tree._utils',
        'sklearn.utils',
        'sklearn.utils._bunch',
        'sklearn.preprocessing',
        'sklearn.metrics',
        'sklearn.metrics._classification',
        # scipy
        'scipy',
        'scipy.signal',
        'scipy.fft',
        'scipy.linalg',
        'scipy.special',
        'scipy.sparse',
        'scipy.sparse.csgraph',
        # librosa
        'librosa',
        'librosa.core',
        'librosa.feature',
        'librosa.effects',
        'librosa.filters',
        'librosa.util',
        'librosa.beat',
        'numba',
        'numba.core',
        'audioread',
        'pooch',
        'decorator',
        'sounddevice',
        'soundfile',
        'cffi',
        # Windows (winreg disponible en Windows nativo)
        'winreg',
        # SSL / HTTPS
        'certifi',
        'ssl',
        # Hotkeys y bandeja del sistema
        'keyboard',
        'pystray',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        # Engine package
        'engine',
        'engine.core',
        'engine.ml',
        'engine.stream',
        'engine.filters',
        'engine.features',
        'engine.devices',
        'engine.config',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='WarzoneAudioEnhancer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # console=False para que no aparezca ventana negra de terminal
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
