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

# ─── Hotkeys globales F1-F5 ──────────────────────────────────────────────────
try:
    import keyboard as _keyboard
    _KEYBOARD_AVAILABLE = True
except ImportError:
    _KEYBOARD_AVAILABLE = False

_HOTKEY_LABELS = {
    'f1': 'mine_feet',
    'f2': 'mine_guns',
    'f3': 'enemy_feet',
    'f4': 'enemy_guns',
    'f5': 'airstrike',
}
_HOTKEY_STOP_TRAINING = 'f6'
_hotkeys_registered = False


_HOTKEY_NAMES = {
    'mine_feet': 'Mis Pasos', 'mine_guns': 'Mis Disparos',
    'enemy_feet': 'Pasos Ene.', 'enemy_guns': 'Disp. Ene.', 'airstrike': 'Aéreo',
}


def _do_hotkey_training(label):
    """F1-F5: toggle grabación para esta clase."""
    if not engine.running:
        return
    name = _HOTKEY_NAMES.get(label, label)
    if engine.training_mode and engine.training_label == label:
        # Segunda pulsación del mismo hotkey → detener grabación
        engine.set_training_mode(False)
        _push_js('onHotkeyStopTraining()')
    else:
        # Iniciar grabación para esta clase (o cambiar de clase)
        engine.set_training_mode(True, label)
        _push_js(f"onHotkeyStartTraining('{label}')")


def _do_hotkey_stop_training():
    """F6: detener grabación incondicionalmente."""
    if not engine.running:
        return
    if engine.training_mode:
        engine.set_training_mode(False)
        _push_js('onHotkeyStopTraining()')


def _register_hotkeys():
    global _hotkeys_registered
    if not _KEYBOARD_AVAILABLE or _hotkeys_registered:
        return
    for key, label in _HOTKEY_LABELS.items():
        _keyboard.add_hotkey(key, _do_hotkey_training, args=(label,), suppress=False)
    _keyboard.add_hotkey(_HOTKEY_STOP_TRAINING, _do_hotkey_stop_training, suppress=False)
    _hotkeys_registered = True


def _unregister_hotkeys():
    global _hotkeys_registered
    if not _KEYBOARD_AVAILABLE or not _hotkeys_registered:
        return
    for key in _HOTKEY_LABELS:
        try:
            _keyboard.remove_hotkey(key)
        except Exception:
            pass
    try:
        _keyboard.remove_hotkey(_HOTKEY_STOP_TRAINING)
    except Exception:
        pass
    _hotkeys_registered = False

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


def on_review(rid, label, pending_count):
    safe_label = label.replace("'", "\\'")
    _push_js(f"onReviewUpdate({rid}, '{safe_label}', {pending_count})")


# ─── Motor de audio ──────────────────────────────────────────────────────────
engine = AudioEngine()
engine.on_level_update      = on_level
engine.on_prediction_update = on_prediction
engine.on_status_update     = on_status
engine.on_review_update     = on_review


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
        if success:
            _register_hotkeys()
            _update_tray_icon(True)
        return {'success': success, 'running': engine.running, 'error': err}

    def stop_engine(self):
        _unregister_hotkeys()
        stats = engine.get_session_stats()
        engine.stop()
        _update_tray_icon(False)
        return {'success': True, 'running': False, 'session_stats': stats}

    def get_status(self):
        mine, enemy, counts = engine.get_sample_count()
        counts['trained'] = engine.model_trained
        return {
            'running':        engine.running,
            'model_trained':  engine.model_trained,
            'training_mode':  engine.training_mode,
            'training_label': engine.training_label,
            'samples':        counts,
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
        mine, enemy, counts = engine.get_sample_count()
        counts['trained'] = engine.model_trained
        counts['mine']  = mine
        counts['enemy'] = enemy
        return {
            'success':       success,
            'samples':       counts,
            'model_trained': engine.model_trained,
            'accuracy_report': engine.get_accuracy_report() if success else {},
        }

    def clear_samples(self):
        engine.clear_samples()
        return {'cleared': True}

    def get_samples(self):
        mine, enemy, counts = engine.get_sample_count()
        counts['mine']  = mine
        counts['enemy'] = enemy
        return counts

    def set_confidence_threshold(self, value):
        engine.set_confidence_threshold(float(value))
        return {'threshold': engine.confidence_threshold}

    def toggle_bypass(self):
        engine.bypass = not engine.bypass
        return {'bypass': engine.bypass}

    def get_bypass(self):
        return {'bypass': engine.bypass}

    def minimize_to_tray(self):
        """Oculta la ventana principal. El icono en la bandeja permite restaurarla."""
        global _window
        if _window:
            try:
                _window.hide()
            except Exception:
                pass
        return {'ok': True}

    def label_recent(self, label):
        added = engine.label_recent(label)
        if added > 0:
            mine, enemy, counts = engine.get_sample_count()
            counts['trained'] = engine.model_trained
            return {'ok': True, 'added': added, 'samples': counts}
        return {'ok': False, 'added': 0}

    # ─── Revisión de muestras ─────────────────────────────────────────────────

    def get_pending_review(self):
        return engine.get_pending_review()

    def play_sample(self, sample_id):
        return engine.play_sample(int(sample_id))

    def stop_playback(self):
        return engine.stop_playback()

    def confirm_sample(self, sample_id):
        result = engine.confirm_sample(int(sample_id))
        if result.get('added'):
            mine, enemy, counts = engine.get_sample_count()
            counts['trained'] = engine.model_trained
            result['samples'] = counts
        return result

    def reject_sample(self, sample_id):
        return engine.reject_sample(int(sample_id))

    def confirm_all_pending(self, label=None):
        result = engine.confirm_all_pending(label if label else None)
        mine, enemy, counts = engine.get_sample_count()
        counts['trained'] = engine.model_trained
        result['samples'] = counts
        return result

    def reject_all_pending(self, label=None):
        return engine.reject_all_pending(label if label else None)

    # ─── Perfiles de ganancia ─────────────────────────────────────────────────

    def save_profile(self, name):
        ok = engine.save_profile(str(name).strip())
        return {'ok': ok, 'profiles': engine.list_profiles()}

    def load_profile(self, name):
        ok = engine.load_profile(str(name))
        return {'ok': ok, 'gains': engine.gains}

    def delete_profile(self, name):
        ok = engine.delete_profile(str(name))
        return {'ok': ok, 'profiles': engine.list_profiles()}

    def list_profiles(self):
        return engine.list_profiles()

    # ─── Autostart ────────────────────────────────────────────────────────────

    def get_last_devices(self):
        return engine.load_last_devices()

    def autostart(self):
        """Arranca el engine con los últimos dispositivos guardados."""
        devs = engine.load_last_devices()
        if not devs:
            return {'ok': False, 'error': 'No hay dispositivos guardados'}
        inp = devs.get('input')
        out = devs.get('output')
        success, err = engine.start(input_device=inp, output_device=out)
        return {'ok': success, 'running': engine.running, 'error': err,
                'input': inp, 'output': out}

    def get_version(self):
        return {'version': VERSION}

    def check_for_updates(self):
        import json as _json
        ctx = _ssl.create_default_context()
        try:
            url = 'https://api.github.com/repos/mojotuning/Anki-Audio-boost/releases/latest'
            req = _urllib_request.Request(url, headers={'User-Agent': 'WarzoneAudioEnhancer'})
            with _urllib_request.urlopen(req, timeout=8, context=ctx) as resp:
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
        import time
        ctx = _ssl.create_default_context()

        if not getattr(sys, 'frozen', False):
            _push_js('onUpdateProgress({"status":"error","msg":"Auto-update solo funciona desde el .exe instalado, no en modo dev"})')
            return

        current_exe = sys.executable
        tmp_dir = os.path.join(os.environ.get('LOCALAPPDATA', _tempfile.gettempdir()), 'WarzoneAudioEnhancer', 'update')
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_exe = os.path.join(tmp_dir, 'WarzoneAudioEnhancer_new.exe')
        backup_exe = os.path.join(tmp_dir, 'WarzoneAudioEnhancer_backup.exe')

        try:
            _push_js('onUpdateProgress({"status":"downloading","progress":0})')
            req = _urllib_request.Request(download_url, headers={'User-Agent': 'WarzoneAudioEnhancer'})
            with _urllib_request.urlopen(req, timeout=120, context=ctx) as resp:
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

            expected_size = os.path.getsize(tmp_exe)

            _push_js('onUpdateProgress({"status":"installing","progress":100})')
            time.sleep(0.5)

            # VBScript launcher: equivalente a doble-click, inicia el exe en el
            # contexto correcto de escritorio Windows (WScript.Shell.Run).
            # El 'start ""' del bat falla porque el cmd padre tiene CREATE_NO_WINDOW
            # y eso impide que pythonnet/CLR inicialice WinForms correctamente.
            vbs_path = os.path.join(tmp_dir, 'launch.vbs')
            with open(vbs_path, 'w') as _vf:
                _vf.write(f'Set sh = CreateObject("WScript.Shell")\r\n')
                _vf.write(f'sh.Run Chr(34) & "{current_exe}" & Chr(34), 1, False\r\n')

            bat_path = os.path.join(tmp_dir, 'updater.bat')
            bat = (
                '@echo off\r\n'
                'setlocal EnableExtensions EnableDelayedExpansion\r\n'
                'ping -n 6 127.0.0.1 > nul\r\n'
                'mkdir "%LOCALAPPDATA%\\WarzoneAudioEnhancer" 2>nul\r\n'
                'for /d %%D in ("%LOCALAPPDATA%\\WarzoneAudioEnhancer\\_MEI*") do rd /s /q "%%~fD" 2>nul\r\n'
                f'del /f /q "{backup_exe}" 2>nul\r\n'
                f'copy /y "{current_exe}" "{backup_exe}" >nul 2>nul\r\n'
                'set REPLACED=0\r\n'
                'for /l %%I in (1,1,8) do (\r\n'
                f'  copy /y "{tmp_exe}" "{current_exe}" >nul 2>nul\r\n'
                f'  for %%A in ("{current_exe}") do set CURSIZE=%%~zA\r\n'
                f'  if "!CURSIZE!"=="{expected_size}" set REPLACED=1\r\n'
                '  if "!REPLACED!"=="1" goto launch\r\n'
                '  ping -n 3 127.0.0.1 > nul\r\n'
                ')\r\n'
                ':restore\r\n'
                f'copy /y "{backup_exe}" "{current_exe}" >nul 2>nul\r\n'
                'exit /b 1\r\n'
                ':launch\r\n'
                'ping -n 3 127.0.0.1 > nul\r\n'
                f'del /f /q "{tmp_exe}" 2>nul\r\n'
                f'wscript "{vbs_path}"\r\n'
            )
            with open(bat_path, 'w') as f:
                f.write(bat)

            _subprocess.Popen(
                ['cmd', '/c', bat_path],
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                close_fds=True,
            )

            time.sleep(0.5)
            engine.stop()
            _unregister_hotkeys()
            # Destruir la ventana limpiamente para que WebView2 libere el lock
            # en su carpeta de datos de usuario antes de que el nuevo exe arranque.
            # Sin esto, el nuevo exe falla con "Cannot find WebView2.Core.dll"
            # porque la sesión anterior dejó un lock activo.
            if _window:
                try:
                    _window.destroy()
                    time.sleep(1.0)
                except Exception:
                    pass
            os._exit(0)

        except Exception as exc:
            err = str(exc).replace('"', "'").replace('\n', ' ')
            _push_js(f'onUpdateProgress({{"status":"error","msg":"{err}"}})')


    # ─── Comunidad ────────────────────────────────────────────────────────────

    def _gh_api(self, path: str, method: str = 'GET', body=None, token: str = None):
        """Llamada a la API de GitHub. Devuelve (status_code, dict_or_bytes)."""
        import urllib.error, json as _json
        ctx = _ssl.create_default_context()
        url = f'https://api.github.com{path}'
        headers = {
            'User-Agent': 'WarzoneAudioEnhancer',
            'Accept': 'application/vnd.github+json',
        }
        if token:
            headers['Authorization'] = f'Bearer {token}'
        data = _json.dumps(body).encode() if body is not None else None
        req = _urllib_request.Request(url, data=data, headers=headers, method=method)
        try:
            with _urllib_request.urlopen(req, timeout=20, context=ctx) as r:
                raw = r.read()
                try:
                    return r.status, _json.loads(raw)
                except Exception:
                    return r.status, raw
        except urllib.error.HTTPError as e:
            return e.code, {}

    def _get_gh_token(self) -> str:
        """Lee el token de GitHub del credential manager de Windows (igual que git)."""
        try:
            result = _subprocess.run(
                ['git', 'credential', 'fill'],
                input='protocol=https\nhost=github.com\n',
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if line.startswith('password='):
                    return line[9:].strip()
        except Exception:
            pass
        return ''

    def fetch_community_model(self):
        """
        Descarga el modelo comunitario desde GitHub Releases y lo instala localmente.
        No requiere autenticación (release público).
        """
        import pickle
        REPO = 'mojotuning/Anki-Audio-boost'
        BASE = f'https://github.com/{REPO}/releases/latest/download'
        ctx = _ssl.create_default_context()

        def _dl(url):
            req = _urllib_request.Request(url, headers={'User-Agent': 'WarzoneAudioEnhancer'})
            with _urllib_request.urlopen(req, timeout=30, context=ctx) as r:
                return r.read()

        try:
            model_bytes  = _dl(f'{BASE}/community_model.pkl')
            scaler_bytes = _dl(f'{BASE}/community_scaler.pkl')
            meta_raw     = _dl(f'{BASE}/community_meta.json')
        except Exception as e:
            return {'ok': False, 'error': f'No se pudo descargar: {e}'}

        try:
            import json as _json
            meta = _json.loads(meta_raw)
            new_model  = pickle.loads(model_bytes)
            new_scaler = pickle.loads(scaler_bytes)
        except Exception as e:
            return {'ok': False, 'error': f'Archivo corrupto: {e}'}

        # Solo instalar si ya no tenemos modelo propio O si la versión comunitaria
        # tiene más muestras que la local
        local_count = len(engine.training_samples)
        community_count = meta.get('sample_count', 0)

        engine.model         = new_model
        engine.scaler        = new_scaler
        engine.model_trained = True
        engine._save_model()

        return {
            'ok': True,
            'community_samples': community_count,
            'local_samples': local_count,
            'version': meta.get('version', '?'),
            'contributors': meta.get('contributors', 1),
        }

    def publish_to_community(self):
        """
        Sube el modelo entrenado y las muestras a GitHub Releases como activo comunitario.
        Requiere el token de GitHub almacenado en el credential manager.
        Solo funciona si el usuario es el owner del repositorio.
        """
        import json as _json, pickle, base64
        if not engine.model_trained or engine.model is None:
            return {'ok': False, 'error': 'Primero entrena el modelo'}

        token = self._get_gh_token()
        if not token:
            return {'ok': False, 'error': 'No se encontró token de GitHub'}

        REPO  = 'mojotuning/Anki-Audio-boost'
        TAG   = 'community-model'

        # Serializar modelo y scaler
        model_bytes  = pickle.dumps(engine.model)
        scaler_bytes = pickle.dumps(engine.scaler)
        samples_json = engine.get_samples_json().encode()

        mine, enemy, counts = engine.get_sample_count()
        meta = {
            'version':       VERSION,
            'sample_count':  len(engine.training_samples),
            'contributors':  1,   # se incrementa si se fusionan muestras de otros
            'classes':       counts,
        }
        meta_bytes = _json.dumps(meta, ensure_ascii=False).encode()

        # Buscar/crear release con el tag community-model
        status, release = self._gh_api(
            f'/repos/{REPO}/releases/tags/{TAG}', token=token)
        if status == 404:
            # Crear el release
            status, release = self._gh_api(
                f'/repos/{REPO}/releases', method='POST', token=token,
                body={
                    'tag_name':   TAG,
                    'name':       'Community Model',
                    'body':       'Modelo ML comunitario actualizado automáticamente.',
                    'prerelease': True,
                }
            )
        if status not in (200, 201):
            return {'ok': False, 'error': f'No se pudo crear/leer release: HTTP {status}'}

        release_id = release.get('id')
        upload_url_base = f'https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets'

        def _upload_asset(name: str, data: bytes, content_type: str = 'application/octet-stream'):
            ctx = _ssl.create_default_context()
            # Borrar el asset anterior si existe
            _, assets = self._gh_api(f'/repos/{REPO}/releases/{release_id}/assets', token=token)
            if isinstance(assets, list):
                for a in assets:
                    if a.get('name') == name:
                        self._gh_api(f'/repos/{REPO}/releases/assets/{a["id"]}',
                                     method='DELETE', token=token)
            url = f'{upload_url_base}?name={name}'
            headers = {
                'User-Agent':    'WarzoneAudioEnhancer',
                'Authorization': f'Bearer {token}',
                'Content-Type':  content_type,
                'Content-Length': str(len(data)),
            }
            req = _urllib_request.Request(url, data=data, headers=headers, method='POST')
            try:
                with _urllib_request.urlopen(req, timeout=60, context=ctx) as r:
                    return r.status
            except Exception:
                return 0

        results = {}
        results['model']   = _upload_asset('community_model.pkl',   model_bytes)
        results['scaler']  = _upload_asset('community_scaler.pkl',  scaler_bytes)
        results['samples'] = _upload_asset('community_samples.json', samples_json, 'application/json')
        results['meta']    = _upload_asset('community_meta.json',    meta_bytes,   'application/json')

        all_ok = all(s in (200, 201) for s in results.values())
        return {
            'ok': all_ok,
            'sample_count': len(engine.training_samples),
            'upload_results': results,
        }

    def submit_samples(self):
        """
        Envía las muestras como contribución anónima creando un GitHub Issue.
        Funciona para cualquier usuario, sin necesidad de ser owner del repo.
        """
        import json as _json, base64
        if not engine.training_samples:
            return {'ok': False, 'error': 'No tienes muestras para enviar'}

        token = self._get_gh_token()
        REPO  = 'mojotuning/Anki-Audio-boost'

        mine, enemy, counts = engine.get_sample_count()
        summary = ', '.join(f'{k}:{v}' for k, v in counts.items() if v > 0)
        samples_b64 = base64.b64encode(engine.get_samples_json().encode()).decode()

        body = (
            f'## Contribución de muestras de entrenamiento\n\n'
            f'**Versión:** {VERSION}\n'
            f'**Total muestras:** {len(engine.training_samples)}\n'
            f'**Resumen:** {summary}\n\n'
            f'<details><summary>Datos (base64)</summary>\n\n'
            f'```\n{samples_b64}\n```\n\n</details>'
        )

        if token:
            # Crear issue con el token propio
            status, resp = self._gh_api(
                f'/repos/{REPO}/issues', method='POST', token=token,
                body={'title': f'[Samples] Contribución {len(engine.training_samples)} muestras',
                      'body': body, 'labels': ['community-samples']},
            )
            if status in (200, 201):
                return {'ok': True, 'issue_url': resp.get('html_url', ''), 'method': 'api'}

        # Sin token: abrir el navegador con el issue pre-relleno (URL limitada a 8KB)
        import urllib.parse, webbrowser
        title = urllib.parse.quote(f'[Samples] {len(engine.training_samples)} muestras (v{VERSION})')
        # Versión corta del body sin los datos base64 para el fallback URL
        short_body = urllib.parse.quote(
            f'Contribución de {len(engine.training_samples)} muestras.\nResumen: {summary}\n'
            f'(Pega el archivo data/samples.json como adjunto)')
        url = f'https://github.com/{REPO}/issues/new?title={title}&body={short_body}'
        webbrowser.open(url)
        return {'ok': True, 'method': 'browser', 'issue_url': url}

    def download_community_samples(self):
        """
        Descarga las muestras comunitarias del último release y las fusiona localmente.
        Después reentrena el modelo con el conjunto fusionado.
        """
        REPO = 'mojotuning/Anki-Audio-boost'
        URL  = f'https://github.com/{REPO}/releases/download/community-model/community_samples.json'
        ctx = _ssl.create_default_context()

        try:
            req = _urllib_request.Request(URL, headers={'User-Agent': 'WarzoneAudioEnhancer'})
            with _urllib_request.urlopen(req, timeout=30, context=ctx) as r:
                community_json = r.read().decode()
        except Exception as e:
            return {'ok': False, 'error': f'No se pudo descargar muestras: {e}'}

        added = engine.merge_community_samples(community_json)
        if added > 0 and len(engine.training_samples) >= 10:
            engine.train_model()

        _, _, counts = engine.get_sample_count()
        counts['trained'] = engine.model_trained
        return {
            'ok': True,
            'new_samples': added,
            'total': len(engine.training_samples),
            'samples': counts,
        }


VERSION = '1.5.13'

# ─── Bandeja del sistema (system tray) ────────────────────────────────────────
try:
    import pystray
    from PIL import Image, ImageDraw
    _PYSTRAY_AVAILABLE = True
except ImportError:
    _PYSTRAY_AVAILABLE = False

_tray_icon = None


def _make_tray_image(running: bool = False):
    """Genera un icono 64×64 para la bandeja: verde=activo, gris=inactivo."""
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = '#00ff6a' if running else '#3a5540'
    d.ellipse([8, 8, 56, 56], fill=color, outline='#050a08', width=3)
    d.rectangle([28, 20, 36, 36], fill='#050a08')
    d.rectangle([28, 40, 36, 46], fill='#050a08')
    return img


def _tray_show(icon, item):
    global _window
    if _window:
        try:
            _window.show()
        except Exception:
            pass


def _tray_quit(icon, item):
    _unregister_hotkeys()
    engine.stop()
    icon.stop()
    os._exit(0)


def _start_tray():
    global _tray_icon
    if not _PYSTRAY_AVAILABLE:
        return
    menu = pystray.Menu(
        pystray.MenuItem('Mostrar ventana', _tray_show, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Salir', _tray_quit),
    )
    _tray_icon = pystray.Icon(
        'WarzoneAudio',
        _make_tray_image(False),
        'Warzone Audio Enhancer',
        menu,
    )
    import threading
    threading.Thread(target=_tray_icon.run, daemon=True).start()


def _update_tray_icon(running: bool):
    global _tray_icon
    if _tray_icon and _PYSTRAY_AVAILABLE:
        try:
            _tray_icon.icon = _make_tray_image(running)
            _tray_icon.title = f'Warzone Audio Enhancer — {"ACTIVO" if running else "OFFLINE"}'
        except Exception:
            pass

# Pre-import módulos críticos al inicio para que estén en memoria antes de cualquier
# limpieza de directorios temporales de PyInstaller (_MEI*).
import ssl as _ssl
import subprocess as _subprocess
import tempfile as _tempfile
import urllib.request as _urllib_request

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


def _is_webview2_installed() -> bool:
    """Verifica via registro si WebView2 Runtime está instalado."""
    try:
        import winreg
        _WV2_GUID = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
        for hive, path in (
            (winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_WV2_GUID}'),
            (winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\Microsoft\EdgeUpdate\Clients\{_WV2_GUID}'),
            (winreg.HKEY_CURRENT_USER,  rf'SOFTWARE\Microsoft\EdgeUpdate\Clients\{_WV2_GUID}'),
        ):
            try:
                with winreg.OpenKey(hive, path):
                    return True
            except OSError:
                pass
    except Exception:
        pass
    return False


def _is_dotnet8_installed() -> bool:
    """Verifica si .NET 8 Desktop Runtime está instalado."""
    # Método 1: dotnet --list-runtimes
    try:
        r = _subprocess.run(
            ['dotnet', '--list-runtimes'],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000
        )
        if 'Microsoft.WindowsDesktop.App 8.' in r.stdout:
            return True
    except Exception:
        pass
    # Método 2: registro
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r'SOFTWARE\dotnet\Setup\InstalledVersions\x64\sharedFramework\Microsoft.WindowsDesktop.App'
        ):
            return True
    except Exception:
        pass
    return False


def _silent_install(url, prefix, args, ok_codes=(0,)):
    """Descarga url a temp y ejecuta con args. Devuelve (ok, error_str)."""
    # Usar el almacén de certificados del sistema (no certifi) para evitar
    # problemas con rutas de directorios temporales de PyInstaller ya eliminados.
    ctx = _ssl.create_default_context()
    tmp = _tempfile.mktemp(suffix='.exe', prefix=prefix)
    try:
        req = _urllib_request.Request(url, headers={'User-Agent': 'WarzoneAudioEnhancer'})
        with _urllib_request.urlopen(req, timeout=180, context=ctx) as r:
            with open(tmp, 'wb') as f:
                f.write(r.read())
        result = _subprocess.run([tmp] + args, timeout=300, creationflags=0x08000000)
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
        _subprocess.Popen([sys.executable] + sys.argv[1:])
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
    ok, err = _silent_install(
        'https://aka.ms/dotnet/8.0/windowsdesktop-runtime-win-x64.exe',
        'wze_dotnet_', ['/install', '/quiet', '/norestart'],
        ok_codes=(0, 1641, 3010)
    )
    if ok:
        _msgbox('Warzone Audio Enhancer', '✓ .NET Runtime instalado.\n\nEl programa se reiniciará ahora.')
        _subprocess.Popen([sys.executable] + sys.argv[1:])
        os._exit(0)
    else:
        _msgbox('Warzone Audio Enhancer — Error',
                f'Error instalando .NET Runtime:\n{err}\n\n'
                'Instala manualmente:\nhttps://aka.ms/dotnet/8.0/windowsdesktop-runtime-win-x64.exe',
                0x00 | 0x10)
        sys.exit(1)


if __name__ == '__main__':
    _start_tray()  # Arrancar bandeja del sistema (daemon thread)
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
        if 'WebView2' in str(e) or 'webview2' in str(e).lower():
            # Siempre ofrecer instalar/reinstalar: la DLL falta independientemente del registro
            _install_webview2()
        else:
            _msgbox('Warzone Audio Enhancer — Error',
                    f'Error al iniciar:\n\n{e}\n\n'
                    'Si persiste, visita:\nhttps://github.com/mojotuning/Anki-Audio-boost/issues',
                    0x00 | 0x10)
            sys.exit(1)
    except RuntimeError as e:
        es = str(e).lower()
        if ('net runtime' in es or 'netfx' in es or 'dotnet' in es or 'clr' in es) and not _is_dotnet8_installed():
            _install_dotnet()
        else:
            _msgbox('Warzone Audio Enhancer — Error',
                    f'Error al iniciar:\n\n{e}\n\n'
                    'Si el error menciona WebView2:\nhttps://aka.ms/webview2\n\n'
                    'Si el error menciona .NET:\nhttps://aka.ms/dotnet/8.0/windowsdesktop-runtime-win-x64.exe\n\n'
                    'Si persiste:\nhttps://github.com/mojotuning/Anki-Audio-boost/issues', 0x00 | 0x10)
            sys.exit(1)
    except OSError as e:
        es = str(e).lower()
        if ('clrloader' in es or ('clr' in es and 'loader' in es)) and not _is_dotnet8_installed():
            _install_dotnet()
        else:
            _msgbox('Warzone Audio Enhancer — Error',
                    f'Error al iniciar:\n\n{e}\n\n'
                    'Si persiste, visita:\nhttps://github.com/mojotuning/Anki-Audio-boost/issues',
                    0x00 | 0x10)
            sys.exit(1)
    except Exception as e:
        from webview import WebViewException  # noqa: F401 – resolve sin reimportar
        if isinstance(e, WebViewException):
            es = str(e).lower()
            # pythonnet no pudo cargar el CLR → probablemente falta .NET
            if ('pythonnet' in es or 'clr' in es or 'net runtime' in es) and not _is_dotnet8_installed():
                _install_dotnet()
            _msgbox('Warzone Audio Enhancer — Error',
                    f'Error al iniciar (WebView):\n\n{e}\n\n'
                    'Requiere .NET 8 Desktop Runtime:\nhttps://aka.ms/dotnet/8.0/windowsdesktop-runtime-win-x64.exe\n\n'
                    'Y/o WebView2 Runtime:\nhttps://aka.ms/webview2', 0x00 | 0x10)
        else:
            _msgbox('Warzone Audio Enhancer — Error inesperado',
                    f'{type(e).__name__}:\n\n{e}\n\n'
                    'Visita:\nhttps://github.com/mojotuning/Anki-Audio-boost/issues',
                    0x00 | 0x10)
        sys.exit(1)

