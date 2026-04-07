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
        success = engine.start(input_device=inp, output_device=out)
        return {'success': success, 'running': engine.running}

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


# ─── Entrypoint ──────────────────────────────────────────────────────────────
def _html_path():
    base = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'index.html')


def _on_closing():
    engine.stop()


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
    # http_server=True: pywebview sirve los archivos locales via su propio servidor
    # interno (puerto aleatorio), sin Flask, sin localhost manual.
    webview.start(http_server=True, debug=False)
