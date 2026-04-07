# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec para Warzone Audio Enhancer
# Genera: dist/WarzoneAudioEnhancer.exe

block_cipher = None

a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Empaquetar la interfaz web dentro del .exe
        ('index.html', '.'),
    ],
    hiddenimports=[
        # pywebview (ventana de escritorio)
        'webview',
        'webview.platforms',
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',
        'webview.platforms.mshtml',
        'clr',
        # Flask & SocketIO
        'flask',
        'flask_cors',
        'flask_socketio',
        'engineio',
        'engineio.async_drivers.threading',
        'socketio',
        'eventlet',
        'eventlet.hubs.epolls',
        'eventlet.hubs.kqueue',
        'eventlet.hubs.selects',
        'eventlet.support.greendns',
        'dns',
        'dns.resolver',
        'dns.dnssec',
        'dns.e164',
        'dns.namedict',
        'dns.tsigkeyring',
        'dns.update',
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
