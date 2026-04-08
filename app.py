"""
Warzone Audio Enhancer - Aplicación de escritorio
Pywebview nativo: Python expone funciones directamente a JS.
Sin Flask, sin localhost, sin puertos.
"""

import sys
import os

# Resolver ruta del módulo tanto en desarrollo como dentro del .exe
_src = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _src)

# Cuando se ejecuta desde el .exe, apuntar certifi al cacert.pem empaquetado
if getattr(sys, 'frozen', False):
    _certifi_path = os.path.join(sys._MEIPASS, 'certifi', 'cacert.pem')
    if os.path.exists(_certifi_path):
        os.environ['SSL_CERT_FILE'] = _certifi_path
        os.environ['REQUESTS_CA_BUNDLE'] = _certifi_path

from audio_engine import AudioEngine, list_audio_devices, detect_audio_software
import webview

# ─── Ventana global (se asigna después de create_window) ─────────────────────
_window = None


def _push_js(call: str):
    """Envía JavaScript a la UI desde cualquier hilo."""
    global _window
    if _window:
        try:
            _window.evaluate_js(call)
        except Exception:
            pass


# ─── Callbacks del engine → UI ───────────────────────────────────────────────
def on_level(level):
    _push_js(f"onAudioLevel({level:.5f})")


def on_prediction(pred, conf):
    _push_js(f"onPrediction('{pred}', {conf:.4f})")


def on_status(msg):
    safe = msg.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')
    _push_js(f'onStatus("{safe}")')


# ─── Motor de audio ──────────────────────────────────────────────────────────
engine = AudioEngine()
engine.on_level_update      = on_level
engine.on_prediction_update = on_prediction
engine.on_status_update     = on_status


# ─── API expuesta a JavaScript (window.pywebview.api.*) ──────────────────────
class Api:

    def get_devices(self):
        return list_audio_devices()

    def software_scan(self):
        return detect_audio_software()

    def start_engine(self, input_device=None, output_device=None):
        inp = int(input_device) if input_device is not None else None
        out = int(output_device) if output_device is not None else None
        success, err = engine.start(input_device=inp, output_device=out)
        return {'success': success, 'running': engine.running, 'error': err}

    def stop_engine(self):
        engine.stop()
        return {'success': True, 'running': False}

    def get_status(self):
        mine, enemy = engine.get_sample_count()
        return {
            'running':        engine.running,
            'model_trained':  engine.model_trained,
            'training_mode':  engine.training_mode,
            'training_label': engine.training_label,
            'samples':        {'mine': mine, 'enemy': enemy},
            'gains':          engine.gains,
            'last_prediction': engine.last_prediction,
            'confidence':     round(engine.prediction_confidence * 100, 1),
        }

    def set_gains(self, gains):
        for key, val in gains.items():
            if key in engine.gains:
                engine.gains[key] = float(val)
        return {'gains': engine.gains}

    def set_noise_config(self, config):
        engine.set_noise_config(config)
        return {'ok': True}

    def set_buffer_size(self, size):
        engine.set_buffer_size(int(size))
        return {'block_size': engine.block_size}

    def start_training(self, label):
        engine.set_training_mode(True, label)
        return {'training': True, 'label': label}

    def stop_training(self):
        engine.set_training_mode(False)
        return {'training': False}

    def train_model(self):
        success = engine.train_model()
        mine, enemy = engine.get_sample_count()
        return {
            'success':       success,
            'samples':       {'mine': mine, 'enemy': enemy},
            'model_trained': engine.model_trained,
        }

    def clear_samples(self):
        engine.clear_samples()
        return {'cleared': True}

    def get_samples(self):
        mine, enemy = engine.get_sample_count()
        return {'mine': mine, 'enemy': enemy}

    def get_version(self):
        return {'version': VERSION}

    def check_for_updates(self):
        import urllib.request, json as _json, ssl
        try:
            # Build SSL context using certifi's CA bundle (works inside PyInstaller exe)
            try:
                import certifi
                ctx = ssl.create_default_context(cafile=certifi.where())
            except Exception:
                ctx = ssl.create_default_context()
            url = 'https://api.github.com/repos/mojotuning/Anki-Audio-boost/releases/latest'
            req = urllib.request.Request(url, headers={'User-Agent': 'WarzoneAudioEnhancer'})
            with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
                data = _json.loads(resp.read().decode())
            latest = data.get('tag_name', '').lstrip('v')
            release_url = data.get('html_url', 'https://github.com/mojotuning/Anki-Audio-boost/releases')
            exe_url = release_url
            for asset in data.get('assets', []):
                if asset.get('name', '').endswith('.exe'):
                    exe_url = asset['browser_download_url']
                    break
            def _ver_tuple(v):
                try:
                    return tuple(int(x) for x in v.split('.'))
                except Exception:
                    return (0,)
            up_to_date = _ver_tuple(VERSION) >= _ver_tuple(latest)
            return {
                'current': VERSION,
                'latest': latest,
                'up_to_date': up_to_date,
                'download_url': exe_url,
            }
        except Exception as exc:
            return {'error': str(exc), 'current': VERSION}

    def open_url(self, url):
        import webbrowser
        webbrowser.open(url)
        return True

    def install_update(self, download_url):
        """Descarga el nuevo exe, crea un bat que reemplaza el exe actual y relanza."""
        import threading
        # Validar que la URL es de GitHub para evitar descargar de fuentes externas
        if not download_url.startswith('https://github.com/') and \
           not download_url.startswith('https://objects.githubusercontent.com/'):
            return {'error': 'URL de descarga no válida'}
        threading.Thread(target=self._download_and_install, args=(download_url,), daemon=True).start()
        return {'started': True}

    def _download_and_install(self, download_url):
        import urllib.request, ssl, tempfile, subprocess, time
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = ssl.create_default_context()

        if not getattr(sys, 'frozen', False):
            _push_js('onUpdateProgress({"status":"error","msg":"Auto-update solo funciona desde el .exe instalado, no en modo dev"})')
            return

        current_exe = sys.executable
        tmp_dir = tempfile.mkdtemp(prefix='wze_update_')
        tmp_exe = os.path.join(tmp_dir, 'WarzoneAudioEnhancer_new.exe')

        try:
            _push_js('onUpdateProgress({"status":"downloading","progress":0})')
            req = urllib.request.Request(download_url, headers={'User-Agent': 'WarzoneAudioEnhancer'})
            with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                total = int(resp.headers.get('Content-Length', 0))
                downloaded = 0
                with open(tmp_exe, 'wb') as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = min(int(downloaded * 100 / total), 99)
                            _push_js(f'onUpdateProgress({{"status":"downloading","progress":{pct}}})')

            _push_js('onUpdateProgress({"status":"installing","progress":100})')
            time.sleep(0.5)

            # Bat: espera 2s (para que el proceso cierre), copia el nuevo exe, relanza
            bat_path = os.path.join(tmp_dir, 'updater.bat')
            bat = (
                '@echo off\r\n'
                'ping -n 3 127.0.0.1 > nul\r\n'
                f'copy /y "{tmp_exe}" "{current_exe}"\r\n'
                f'start "" "{current_exe}"\r\n'
            )
            with open(bat_path, 'w') as f:
                f.write(bat)

            subprocess.Popen(
                ['cmd', '/c', bat_path],
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                close_fds=True,
            )

            time.sleep(0.5)
            engine.stop()
            os._exit(0)

        except Exception as exc:
            err = str(exc).replace('"', "'").replace('\n', ' ')
            _push_js(f'onUpdateProgress({{"status":"error","msg":"{err}"}})')


VERSION = '1.4.2'

# ─── Entrypoint ──────────────────────────────────────────────────────────────
def _html_path():
    base = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'index.html')


def _on_closing():
    engine.stop()


def _msgbox(title, msg, style=0x00 | 0x40):
    import ctypes
    ctypes.windll.user32.MessageBoxW(0, msg, title, style)

def _msgbox_yesno(title, msg):
    import ctypes
    return ctypes.windll.user32.MessageBoxW(0, msg, title, 0x04 | 0x20) == 6  # IDYES


def _silent_install(url, prefix, args, ok_codes=(0,)):
    """Descarga url a temp y ejecuta con args. Devuelve (ok, error_str)."""
    import urllib.request, ssl, tempfile, subprocess
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    tmp = tempfile.mktemp(suffix='.exe', prefix=prefix)
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'WarzoneAudioEnhancer'})
        with urllib.request.urlopen(req, timeout=180, context=ctx) as r:
            with open(tmp, 'wb') as f:
                f.write(r.read())
        result = subprocess.run([tmp] + args, timeout=300, creationflags=0x08000000)
        return result.returncode in ok_codes, f'exit code {result.returncode}'
    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


def _install_webview2():
    if not _msgbox_yesno(
        'Warzone Audio Enhancer — Componente requerido',
        'Warzone Audio Enhancer necesita instalar\n'
        'Microsoft WebView2 Runtime para funcionar.\n\n'
        '• Componente oficial de Microsoft (gratuito)\n'
        '• Se instala automáticamente — solo una vez\n'
        '• Puede tardar 1-2 minutos\n\n'
        '¿Instalar ahora?'
    ):
        sys.exit(0)
    ok, err = _silent_install(
        'https://go.microsoft.com/fwlink/p/?LinkId=2124703',
        'wze_wv2_', ['/silent', '/install'],
        ok_codes=(0, 1638, 2147747880)
    )
    if ok:
        _msgbox('Warzone Audio Enhancer', '✓ WebView2 instalado.\n\nEl programa se reiniciará ahora.')
        import subprocess
        subprocess.Popen([sys.executable] + sys.argv[1:])
        os._exit(0)
    else:
        _msgbox('Warzone Audio Enhancer — Error',
                f'Error instalando WebView2:\n{err}\n\nInstala manualmente:\nhttps://aka.ms/webview2',
                0x00 | 0x10)
        sys.exit(1)


def _install_dotnet():
    if not _msgbox_yesno(
        'Warzone Audio Enhancer — Componente requerido',
        'Warzone Audio Enhancer necesita instalar\n'
        'Microsoft .NET 8 Desktop Runtime para funcionar.\n\n'
        '• Componente oficial de Microsoft (gratuito)\n'
        '• Se instala automáticamente — solo una vez\n'
        '• Puede tardar 2-3 minutos\n\n'
        '¿Instalar ahora?'
    ):
        sys.exit(0)
    # .NET 8 Desktop Runtime x64 — instalador offline
    ok, err = _silent_install(
        'https://aka.ms/dotnet/8.0/windowsdesktop-runtime-win-x64.exe',
        'wze_dotnet_', ['/install', '/quiet', '/norestart'],
        ok_codes=(0, 1641, 3010)  # 1641=restart pending, 3010=success restart needed
    )
    if ok:
        _msgbox('Warzone Audio Enhancer', '✓ .NET Runtime instalado.\n\nEl programa se reiniciará ahora.')
        import subprocess
        subprocess.Popen([sys.executable] + sys.argv[1:])
        os._exit(0)
    else:
        _msgbox('Warzone Audio Enhancer — Error',
                f'Error instalando .NET Runtime:\n{err}\n\n'
                'Instala manualmente:\nhttps://aka.ms/dotnet/8.0/windowsdesktop-runtime-win-x64.exe',
                0x00 | 0x10)
        sys.exit(1)


if __name__ == '__main__':
    api = Api()
    _window = webview.create_window(
        title='Warzone Audio Enhancer',
        url=_html_path(),
        js_api=api,
        width=1140,
        height=860,
        min_size=(900, 650),
        background_color='#050a08',
        text_select=False,
        zoomable=False,
    )
    _window.events.closing += _on_closing
    try:
        webview.start(http_server=True, debug=False)
    except FileNotFoundError as e:
        if 'WebView2' in str(e):
            _install_webview2()
        else:
            raise
    except RuntimeError as e:
        if 'NET runtime' in str(e) or 'netfx' in str(e).lower() or 'dotnet' in str(e).lower():
            _install_dotnet()
        else:
            raise
    except OSError as e:
        # ClrLoader.dll fallo — mismo problema de .NET
        if 'ClrLoader' in str(e) or 'clr' in str(e).lower():
            _install_dotnet()
        else:
            raise

