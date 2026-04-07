"""
Servidor Flask - Puente entre el motor de audio y la interfaz web
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import sounddevice as sd
import threading
import time
import sys
import os
import webbrowser

sys.path.insert(0, os.path.dirname(__file__))
from audio_engine import AudioEngine, list_audio_devices, detect_audio_software

app = Flask(__name__)
app.config['SECRET_KEY'] = 'warzone-audio-2024'
CORS(app, origins="*")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')


def _base_path() -> str:
    """Ruta base correcta tanto en desarrollo como dentro del .exe (PyInstaller)."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

engine = AudioEngine()

# ─── Callbacks del engine → UI ───────────────────────────────────────────────
def on_level(level):
    socketio.emit('audio_level', {'level': float(level)})

def on_prediction(pred, conf):
    socketio.emit('prediction', {'label': pred, 'confidence': round(conf * 100, 1)})

def on_status(msg):
    socketio.emit('status', {'message': msg})

engine.on_level_update = on_level
engine.on_prediction_update = on_prediction
engine.on_status_update = on_status
# ─── Ruta raíz ─────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory(_base_path(), 'index.html')
# ─── API Routes ──────────────────────────────────────────────────────────────
@app.route('/api/devices')
def get_devices():
    return jsonify(list_audio_devices())

@app.route('/api/start', methods=['POST'])
def start_engine():
    data = request.json or {}
    input_dev = data.get('input_device')
    output_dev = data.get('output_device')
    
    success = engine.start(
        input_device=input_dev if input_dev is not None else None,
        output_device=output_dev if output_dev is not None else None
    )
    return jsonify({'success': success, 'running': engine.running})

@app.route('/api/stop', methods=['POST'])
def stop_engine():
    engine.stop()
    return jsonify({'success': True, 'running': False})

@app.route('/api/status')
def get_status():
    mine, enemy = engine.get_sample_count()
    return jsonify({
        'running': engine.running,
        'model_trained': engine.model_trained,
        'training_mode': engine.training_mode,
        'training_label': engine.training_label,
        'samples': {'mine': mine, 'enemy': enemy},
        'gains': engine.gains,
        'last_prediction': engine.last_prediction,
        'confidence': round(engine.prediction_confidence * 100, 1)
    })

@app.route('/api/gains', methods=['POST'])
def set_gains():
    data = request.json or {}
    for key, val in data.items():
        if key in engine.gains:
            engine.gains[key] = float(val)
    return jsonify({'gains': engine.gains})

@app.route('/api/training/start', methods=['POST'])
def start_training():
    data = request.json or {}
    label = data.get('label', 'mine')  # 'mine' | 'enemy'
    engine.set_training_mode(True, label)
    return jsonify({'training': True, 'label': label})

@app.route('/api/training/stop', methods=['POST'])
def stop_training():
    engine.set_training_mode(False)
    return jsonify({'training': False})

@app.route('/api/training/train', methods=['POST'])
def trigger_train():
    success = engine.train_model()
    mine, enemy = engine.get_sample_count()
    return jsonify({
        'success': success,
        'samples': {'mine': mine, 'enemy': enemy},
        'model_trained': engine.model_trained
    })

@app.route('/api/training/clear', methods=['POST'])
def clear_training():
    engine.clear_samples()
    return jsonify({'cleared': True})

@app.route('/api/samples')
def get_samples():
    mine, enemy = engine.get_sample_count()
    return jsonify({'mine': mine, 'enemy': enemy})


@app.route('/api/software_scan')
def software_scan():
    """Detecta VB-Cable, Voicemeter y EQ APO. Solo lectura, sin modificar nada."""
    return jsonify(detect_audio_software())


if __name__ == '__main__':
    print("🎮 Warzone Audio Server iniciando en http://localhost:5000")

    def _open_browser():
        time.sleep(1.5)
        webbrowser.open('http://localhost:5000')

    threading.Thread(target=_open_browser, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
