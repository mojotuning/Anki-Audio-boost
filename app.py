"""
Warzone Audio Enhancer v2.0 — Channel Shaper para EqualizerAPO
Pywebview nativo: Python expone funciones directamente a JS.
"""

import sys
import os

_src = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _src)

if getattr(sys, 'frozen', False):
    _certifi_path = os.path.join(sys._MEIPASS, 'certifi', 'cacert.pem')
    if os.path.exists(_certifi_path):
        os.environ['SSL_CERT_FILE'] = _certifi_path
        os.environ['REQUESTS_CA_BUNDLE'] = _certifi_path

from apo_engine import APOEngine
from presets import PRESETS, PARAM_RANGES

import webview

# ─── Ventana global ──────────────────────────────────────────────────────────
_window = None

VERSION = '4.0.0'


def _push_js(call: str):
    global _window
    if _window:
        try:
            _window.evaluate_js(call)
        except Exception:
            pass


# ─── Motor ───────────────────────────────────────────────────────────────────
engine = APOEngine()


# ─── API expuesta a JavaScript ───────────────────────────────────────────────
class Api:

    def get_apo_status(self):
        sw = engine.detect_software()
        sw["enabled"] = engine.enabled
        sw["preset"] = engine.active_preset
        sw["params"] = dict(engine.params)
        return sw

    def get_diagnostics(self):
        """Diagnóstico completo — muestra qué archivos está cargando APO."""
        result = {
            'apo_path':        str(engine.apo_path) if engine.apo_path else None,
            'config_dir':      str(engine.config_dir) if engine.config_dir else None,
            'config_txt':      None,
            'stage_files':     {},
            'reaplugs_found':  None,
            'reaxcomp_found':  None,
            'reajs_found':     None,
        }

        if engine.config_dir:
            cfg = engine.config_dir / 'config.txt'
            if cfg.exists():
                result['config_txt'] = cfg.read_text(encoding='utf-8', errors='replace')

        # Stage files content
        from presets import STAGE_FILES as _SF
        if engine.our_dir and engine.our_dir.is_dir():
            for fname in _SF:
                p = engine.our_dir / fname
                result['stage_files'][fname] = (
                    p.read_text(encoding='utf-8', errors='replace') if p.exists() else None
                )
        else:
            result['stage_files'] = {f: None for f in _SF}

        # DLL checks
        from pathlib import Path as _Path
        from presets import _find_reajs_path, _find_reaxcomp_path, find_reaplugs_path
        result['reaxcomp_found'] = _Path(_find_reaxcomp_path()).exists()
        result['reacomp_found']  = _Path(find_reaplugs_path()).exists()
        result['reajs_found']    = _Path(_find_reajs_path()).exists()

        return result

    def get_presets(self):
        result = {}
        for key, p in PRESETS.items():
            result[key] = {
                "name": p["name"],
                "icon": p["icon"],
                "description": p["description"],
            }
        return result

    def get_param_ranges(self):
        return PARAM_RANGES

    def apply_preset(self, name):
        r = engine.set_preset(name)
        if r["ok"]:
            r2 = engine.apply()
            r["applied"] = r2["ok"]
            if not r2["ok"]:
                r["error"] = r2.get("error", "")
        return r

    def apply_current(self):
        return engine.apply()

    def disable(self):
        return engine.disable()

    def update_param(self, key, value):
        return engine.update_param(key, float(value))

    def get_state(self):
        return engine.get_state()

    # ─── Perfiles ─────────────────────────────────────────────────────────

    def save_profile(self, name):
        return engine.save_profile(str(name).strip())

    def load_profile(self, name):
        r = engine.load_profile(str(name))
        if r["ok"] and engine.enabled:
            engine.apply()
        return r

    def delete_profile(self, name):
        return engine.delete_profile(str(name))

    def list_profiles(self):
        return engine.list_profiles()

    # ─── Utilidades ───────────────────────────────────────────────────────

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
            release_url = data.get('html_url', '')
            exe_url = release_url
            for asset in data.get('assets', []):
                if asset.get('name', '').endswith('.exe'):
                    exe_url = asset['browser_download_url']
                    break

            def _ver(v):
                try:
                    return tuple(int(x) for x in v.split('.'))
                except Exception:
                    return (0,)

            return {
                'current': VERSION,
                'latest': latest,
                'up_to_date': _ver(VERSION) >= _ver(latest),
                'release_url': release_url,
            }
        except Exception as exc:
            return {'error': str(exc), 'current': VERSION}

    def open_url(self, url):
        import webbrowser
        webbrowser.open(url)
        return True

    def minimize_to_tray(self):
        global _window
        if _window:
            try:
                _window.hide()
            except Exception:
                pass
        return {'ok': True}

    def install_apo(self):
        """Abre la página de descarga de EqualizerAPO."""
        import webbrowser
        webbrowser.open('https://sourceforge.net/projects/equalizerapo/')
        return {'ok': True}

    # ─── Setup Wizard: instalar dependencias ──────────────────────────────

    def get_setup_status(self):
        """Retorna estado de instalación de cada dependencia (en orden)."""
        sw = engine.detect_software()
        leq_on = self._is_leq_enabled()
        return {
            'vb_cable':      {'installed': sw['vb_cable'],    'name': 'VB-Audio Hi-Fi Cable', 'desc': 'Dispositivo virtual 7.1 surround', 'leq': leq_on},
            'voicemeeter':   {'installed': sw['voicemeeter'], 'name': 'Voicemeeter',          'desc': 'Mixer / router de audio (obligatorio)'},
            'apo':           {'installed': sw['apo'],         'name': 'EqualizerAPO',         'desc': 'Motor de procesamiento de audio'},
            'reaplugs':      {'installed': sw['reaplugs'],    'name': 'ReaPlugs',             'desc': 'VST plugins — Spatial Engine + compresores + limiter'},
            'windows_sonic': {'installed': True,              'name': 'Windows Sonic',        'desc': 'Binaural 7.1→estéreo nativo de Windows — activar en propiedades del dispositivo'},
        }

    def install_dependency(self, dep_id):
        """Descarga e instala una dependencia. Retorna progreso."""

        urls = {
            'vb_cable':      'https://download.vb-audio.com/Download_CABLE/HiFiCableAudioDriver64.zip',
            'voicemeeter':   'https://download.vb-audio.com/Download_CABLE/VoicemeeterSetup.exe',
            'apo':           'https://sourceforge.net/projects/equalizerapo/files/latest/download',
            'reaplugs':      'https://www.reaper.fm/reaplugs/reaplugs239_x64-install.exe',
            'windows_sonic': None,
        }

        if dep_id not in urls:
            return {'ok': False, 'error': f'Dependencia "{dep_id}" no reconocida'}

        if dep_id == 'windows_sonic':
            return self.open_sound_panel()

        url = urls[dep_id]

        try:
            _push_js(f"setupProgress('{dep_id}', 'downloading')")

            ctx = _ssl.create_default_context()
            req = _urllib_request.Request(url, headers={'User-Agent': 'WarzoneAudioEnhancer/3.1'})
            resp = _urllib_request.urlopen(req, timeout=300, context=ctx)

            # Determine file extension from response or URL
            content_disp = resp.headers.get('Content-Disposition', '')
            if '.zip' in url or '.zip' in content_disp:
                ext = '.zip'
            else:
                ext = '.exe'

            tmp = _tempfile.mktemp(suffix=ext, prefix=f'wae_{dep_id}_')
            with open(tmp, 'wb') as f:
                total = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    total += len(chunk)

            _push_js(f"setupProgress('{dep_id}', 'installing')")

            if ext == '.zip':
                # VB-Cable comes as zip — extract and run setup
                import zipfile
                extract_dir = _tempfile.mkdtemp(prefix=f'wae_{dep_id}_')
                with zipfile.ZipFile(tmp, 'r') as z:
                    z.extractall(extract_dir)
                os.remove(tmp)
                # Find the setup exe inside
                setup_exe = None
                for root, dirs, files in os.walk(extract_dir):
                    for fn in files:
                        if fn.lower().startswith('setup') and fn.lower().endswith('.exe'):
                            setup_exe = os.path.join(root, fn)
                            break
                    if not setup_exe:
                        for fn in files:
                            if fn.lower().endswith('.exe') and ('setup' in fn.lower() or 'install' in fn.lower()):
                                setup_exe = os.path.join(root, fn)
                                break
                    if setup_exe:
                        break

                if setup_exe:
                    result = _subprocess.run([setup_exe], timeout=300)
                    ok = result.returncode in (0, 1638)
                else:
                    _subprocess.Popen(['explorer', extract_dir])
                    ok = True
            else:
                result = _subprocess.run([tmp], timeout=600)
                ok = result.returncode in (0, 1638, 3010)
                try:
                    os.remove(tmp)
                except Exception:
                    pass

            if ok:
                engine.apo_path = engine._find_apo()
                engine.config_dir = engine.apo_path / "config" if engine.apo_path else None
                _push_js(f"setupProgress('{dep_id}', 'done')")
                return {'ok': True}
            else:
                _push_js(f"setupProgress('{dep_id}', 'error')")
                return {'ok': False, 'error': f'Installer exited with code {result.returncode}'}

        except Exception as e:
            _push_js(f"setupProgress('{dep_id}', 'error')")
            return {'ok': False, 'error': str(e)}

    def open_dependency_page(self, dep_id):
        """Abre la página de descarga manual de una dependencia."""
        import webbrowser
        pages = {
            'vb_cable':      'https://vb-audio.com/Cable/#DownloadSection',
            'voicemeeter':   'https://vb-audio.com/Voicemeeter/',
            'apo':           'https://sourceforge.net/projects/equalizerapo/',
            'reaplugs':      'https://www.reaper.fm/reaplugs/',
            'windows_sonic': None,
        }
        if dep_id == 'windows_sonic':
            return self.open_sound_panel()
        if dep_id in pages:
            webbrowser.open(pages[dep_id])
            return {'ok': True}
        return {'ok': False}

    def open_sound_panel(self):
        """Abre las Propiedades de sonido de Windows para activar Windows Sonic."""
        try:
            _subprocess.Popen(['rundll32.exe', 'shell32.dll,Control_RunDLL', 'mmsys.cpl,,0'])
            return {'ok': True, 'message': 'Abierto panel de sonido. Selecciona el dispositivo → Propiedades espaciales → Windows Sonic for Headphones'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ─── Loudness Equalization (LEQ) toggle ───────────────────────────────

    def _find_hifi_cable_device_key(self):
        """Busca la clave de registro del dispositivo Hi-Fi Cable."""
        import winreg
        base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
        try:
            render_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(render_key, i)
                    props_path = f"{base}\\{subkey_name}\\Properties"
                    try:
                        props = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, props_path)
                        # Device friendly name is at {a45c254e-df1c-4efd-8020-67d146a850e0},2
                        try:
                            name, _ = winreg.QueryValueEx(props, "{a45c254e-df1c-4efd-8020-67d146a850e0},2")
                            if name and ('hi-fi' in name.lower() or 'hifi' in name.lower()):
                                winreg.CloseKey(props)
                                winreg.CloseKey(render_key)
                                return f"{base}\\{subkey_name}"
                        except OSError:
                            pass
                        winreg.CloseKey(props)
                    except OSError:
                        pass
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(render_key)
        except OSError:
            pass
        return None

    def _is_leq_enabled(self):
        """Verifica si Loudness Equalization está activado en Hi-Fi Cable."""
        import winreg
        dev_key = self._find_hifi_cable_device_key()
        if not dev_key:
            return False
        fxprops = f"{dev_key}\\FxProperties"
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, fxprops)
            # LEQ GUID: {fc52a749-4be9-4510-896e-966ba6525980},1
            val, _ = winreg.QueryValueEx(key, "{fc52a749-4be9-4510-896e-966ba6525980},1")
            winreg.CloseKey(key)
            return val == 1
        except OSError:
            return False

    def toggle_leq(self):
        """Activa/desactiva Loudness Equalization en Hi-Fi Cable.
        Abre propiedades del dispositivo si no puede hacerlo por registro."""
        try:
            # Abrir las propiedades de sonido de Windows para que el usuario
            # active LEQ manualmente (acceso directo más confiable)
            _subprocess.Popen(['rundll32.exe', 'shell32.dll,Control_RunDLL', 'mmsys.cpl,,0'])
            return {'ok': True, 'message': 'Abierto panel de sonido. Busca Hi-Fi Cable → Propiedades → Mejoras → Loudness Equalization'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}


# ─── Bandeja del sistema ─────────────────────────────────────────────────────
try:
    import pystray
    from PIL import Image, ImageDraw
    _PYSTRAY_OK = True
except ImportError:
    _PYSTRAY_OK = False

_tray_icon = None


def _make_tray_image(enabled=False):
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = '#00ff6a' if enabled else '#3a5540'
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
    icon.stop()
    os._exit(0)


def _start_tray():
    global _tray_icon
    if not _PYSTRAY_OK:
        return
    menu = pystray.Menu(
        pystray.MenuItem('Mostrar ventana', _tray_show, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Salir', _tray_quit),
    )
    _tray_icon = pystray.Icon('WarzoneAudio', _make_tray_image(False),
                              'Warzone Audio Enhancer', menu)
    import threading
    threading.Thread(target=_tray_icon.run, daemon=True).start()


def _update_tray(enabled):
    global _tray_icon
    if _tray_icon and _PYSTRAY_OK:
        try:
            _tray_icon.icon = _make_tray_image(enabled)
            _tray_icon.title = f'Warzone Audio — {"ON" if enabled else "OFF"}'
        except Exception:
            pass


# ─── Pre-imports ─────────────────────────────────────────────────────────────
import ssl as _ssl
import subprocess as _subprocess
import tempfile as _tempfile
import urllib.request as _urllib_request


# ─── Entrypoint ──────────────────────────────────────────────────────────────
def _html_path():
    base = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'index.html')


def _on_closing():
    pass  # Nada que limpiar — APO config persiste


def _msgbox(title, msg, style=0x00 | 0x40):
    import ctypes
    ctypes.windll.user32.MessageBoxW(0, msg, title, style)


def _msgbox_yesno(title, msg):
    import ctypes
    return ctypes.windll.user32.MessageBoxW(0, msg, title, 0x04 | 0x20) == 6


def _is_webview2_installed() -> bool:
    try:
        import winreg
        _WV2_GUID = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
        for hive, path in (
            (winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_WV2_GUID}'),
            (winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\Microsoft\EdgeUpdate\Clients\{_WV2_GUID}'),
            (winreg.HKEY_CURRENT_USER, rf'SOFTWARE\Microsoft\EdgeUpdate\Clients\{_WV2_GUID}'),
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
    try:
        r = _subprocess.run(['dotnet', '--list-runtimes'],
                            capture_output=True, text=True, timeout=5,
                            creationflags=0x08000000)
        if 'Microsoft.WindowsDesktop.App 8.' in r.stdout:
            return True
    except Exception:
        pass
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
        'Se necesita Microsoft WebView2 Runtime.\n\n'
        '• Componente oficial de Microsoft (gratuito)\n'
        '• Se instala automáticamente — solo una vez\n\n'
        '¿Instalar ahora?'
    ):
        sys.exit(0)
    ok, err = _silent_install(
        'https://go.microsoft.com/fwlink/p/?LinkId=2124703',
        'wze_wv2_', ['/silent', '/install'],
        ok_codes=(0, 1638, 2147747880))
    if ok:
        _msgbox('Warzone Audio Enhancer', '✓ WebView2 instalado.\nEl programa se reiniciará.')
        _subprocess.Popen([sys.executable] + sys.argv[1:])
        os._exit(0)
    else:
        _msgbox('Error', f'Error instalando WebView2:\n{err}', 0x10)
        sys.exit(1)


def _install_dotnet():
    if not _msgbox_yesno(
        'Warzone Audio Enhancer — Componente requerido',
        'Se necesita Microsoft .NET 8 Desktop Runtime.\n\n'
        '• Componente oficial de Microsoft (gratuito)\n'
        '• Se instala automáticamente — solo una vez\n\n'
        '¿Instalar ahora?'
    ):
        sys.exit(0)
    ok, err = _silent_install(
        'https://aka.ms/dotnet/8.0/windowsdesktop-runtime-win-x64.exe',
        'wze_dotnet_', ['/install', '/quiet', '/norestart'],
        ok_codes=(0, 1641, 3010))
    if ok:
        _msgbox('Warzone Audio Enhancer', '✓ .NET Runtime instalado.\nEl programa se reiniciará.')
        _subprocess.Popen([sys.executable] + sys.argv[1:])
        os._exit(0)
    else:
        _msgbox('Error', f'Error instalando .NET:\n{err}', 0x10)
        sys.exit(1)


if __name__ == '__main__':
    _start_tray()
    api = Api()
    _window = webview.create_window(
        title='Warzone Audio Enhancer',
        url=_html_path(),
        js_api=api,
        width=1000,
        height=800,
        min_size=(850, 650),
        background_color='#050a08',
        text_select=False,
        zoomable=False,
    )
    _window.events.closing += _on_closing
    try:
        webview.start(http_server=True, debug=False)
    except FileNotFoundError as e:
        if 'WebView2' in str(e) or 'webview2' in str(e).lower():
            _install_webview2()
        else:
            _msgbox('Warzone Audio Enhancer — Error',
                    f'Error al iniciar:\n\n{e}\n\n'
                    'Si persiste, visita:\nhttps://github.com/mojotuning/Anki-Audio-boost/issues',
                    0x10)
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
                    'Si persiste:\nhttps://github.com/mojotuning/Anki-Audio-boost/issues', 0x10)
            sys.exit(1)
    except OSError as e:
        es = str(e).lower()
        if ('clrloader' in es or ('clr' in es and 'loader' in es)) and not _is_dotnet8_installed():
            _install_dotnet()
        else:
            _msgbox('Warzone Audio Enhancer — Error',
                    f'Error al iniciar:\n\n{e}\n\n'
                    'Si persiste, visita:\nhttps://github.com/mojotuning/Anki-Audio-boost/issues',
                    0x10)
            sys.exit(1)
    except Exception as e:
        try:
            from webview import WebViewException
            if isinstance(e, WebViewException):
                es = str(e).lower()
                if ('pythonnet' in es or 'clr' in es or 'net runtime' in es) and not _is_dotnet8_installed():
                    _install_dotnet()
                _msgbox('Warzone Audio Enhancer — Error',
                        f'Error al iniciar (WebView):\n\n{e}\n\n'
                        'Requiere .NET 8 Desktop Runtime:\nhttps://aka.ms/dotnet/8.0/windowsdesktop-runtime-win-x64.exe\n\n'
                        'Y/o WebView2 Runtime:\nhttps://aka.ms/webview2', 0x10)
                sys.exit(1)
        except ImportError:
            pass
        _msgbox('Warzone Audio Enhancer — Error inesperado',
                f'{type(e).__name__}:\n\n{e}\n\n'
                'Visita:\nhttps://github.com/mojotuning/Anki-Audio-boost/issues',
                0x10)
        sys.exit(1)
