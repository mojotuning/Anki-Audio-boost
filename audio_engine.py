"""
Warzone Audio Enhancer - Motor de Audio Principal
Captura el audio del sistema, aplica filtros inteligentes y ML para
boost de pasos enemigos y silenciar los propios.
"""

import sys
import numpy as np
import sounddevice as sd
import soundfile as sf
import librosa
import json
import os
import threading
import time
import pickle
from pathlib import Path
from scipy import signal
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from collections import deque
import warnings
warnings.filterwarnings('ignore')

# ─── Configuración ───────────────────────────────────────────────────────────
SAMPLE_RATE = 44100
BLOCK_SIZE = 1024
CHANNELS = 2

# Ruta de datos: junto al .exe en producción, o carpeta local en desarrollo
def _get_data_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(os.path.dirname(sys.executable)) / "data"
    return Path("data")

DATA_DIR = _get_data_dir()
MODEL_FILE = DATA_DIR / "model.pkl"
SCALER_FILE = DATA_DIR / "scaler.pkl"
SAMPLES_FILE = DATA_DIR / "samples.json"

DATA_DIR.mkdir(exist_ok=True)

# ─── Rangos de frecuencia para cada tipo de sonido ──────────────────────────
FREQ_RANGES = {
    "footsteps":   (80,  600),   # Pasos: graves/medios bajos
    "gunshots":    (600, 4000),  # Disparos: medios/agudos
    "airstrikes":  (40,  200),   # Aéreos: sub-graves
    "ambient":     (200, 800),   # Ambiente general
}

class AudioEngine:
    def __init__(self):
        self.running = False
        self.training_mode = False
        self.training_label = None  # 'mine' | 'enemy' | None
        
        # Configuración de ganancia (0.0 a 5.0)
        self.gains = {
            "enemy_footsteps": 3.0,
            "own_footsteps":   0.1,
            "enemy_gunshots":  2.0,
            "airstrikes":      2.5,
        }
        
        # Buffers
        self.audio_buffer = deque(maxlen=100)
        self.feature_buffer = deque(maxlen=50)
        self.training_samples = []
        
        # Estado del ML
        self.model = None
        self.scaler = StandardScaler()
        self.model_trained = False
        self.last_prediction = "unknown"
        self.prediction_confidence = 0.0
        
        # Callbacks para la UI
        self.on_level_update = None
        self.on_prediction_update = None
        self.on_status_update = None
        
        # Dispositivos
        self.input_device = None   # Loopback (audio del sistema)
        self.output_device = None  # Auriculares
        
        self._load_model()
        self._load_samples()
    
    # ─── Extracción de características ──────────────────────────────────────
    def extract_features(self, audio_chunk):
        """Extrae características del audio para el clasificador ML."""
        try:
            mono = np.mean(audio_chunk, axis=1) if audio_chunk.ndim > 1 else audio_chunk
            
            if len(mono) < 512:
                return None
            
            features = []
            
            # 1. MFCCs (timbre del sonido)
            mfccs = librosa.feature.mfcc(y=mono.astype(np.float32), 
                                          sr=SAMPLE_RATE, n_mfcc=13)
            features.extend(np.mean(mfccs, axis=1))
            features.extend(np.std(mfccs, axis=1))
            
            # 2. Energía por banda de frecuencia
            freqs = np.fft.rfftfreq(len(mono), 1/SAMPLE_RATE)
            fft_mag = np.abs(np.fft.rfft(mono))
            
            for name, (low, high) in FREQ_RANGES.items():
                mask = (freqs >= low) & (freqs <= high)
                energy = np.sum(fft_mag[mask] ** 2) if mask.any() else 0
                features.append(float(energy))
            
            # 3. RMS (volumen general)
            rms = np.sqrt(np.mean(mono**2))
            features.append(float(rms))
            
            # 4. Zero crossing rate (textura del sonido)
            zcr = librosa.feature.zero_crossing_rate(mono)
            features.append(float(np.mean(zcr)))
            
            # 5. Centroide espectral
            centroid = librosa.feature.spectral_centroid(
                y=mono.astype(np.float32), sr=SAMPLE_RATE)
            features.append(float(np.mean(centroid)))
            
            return np.array(features)
        
        except Exception:
            return None
    
    # ─── Filtros de audio ────────────────────────────────────────────────────
    def apply_eq_band(self, audio, low_hz, high_hz, gain_db):
        """Aplica ganancia a una banda de frecuencia."""
        nyq = SAMPLE_RATE / 2
        low = max(low_hz / nyq, 0.001)
        high = min(high_hz / nyq, 0.999)
        
        if low >= high:
            return audio
        
        b, a = signal.butter(4, [low, high], btype='band')
        band = signal.lfilter(b, a, audio, axis=0)
        gain_linear = 10 ** (gain_db / 20)
        
        # Audio original sin esa banda + banda con ganancia aplicada
        return audio - band + (band * gain_linear)
    
    def process_audio(self, audio_chunk, prediction):
        """Aplica el procesamiento según la predicción del ML."""
        processed = audio_chunk.copy().astype(np.float64)
        
        if prediction == "enemy":
            # Boost pasos enemigos
            db_enemy_feet = 20 * np.log10(self.gains["enemy_footsteps"])
            processed = self.apply_eq_band(processed, 80, 600, db_enemy_feet)
            
            # Boost disparos
            db_guns = 20 * np.log10(self.gains["enemy_gunshots"])
            processed = self.apply_eq_band(processed, 600, 4000, db_guns)
            
        elif prediction == "mine":
            # Atenuar pasos propios
            db_own = 20 * np.log10(self.gains["own_footsteps"])
            processed = self.apply_eq_band(processed, 80, 600, db_own)
        
        # Boost ataques aéreos siempre
        db_air = 20 * np.log10(self.gains["airstrikes"])
        processed = self.apply_eq_band(processed, 40, 200, db_air)
        
        # Prevenir clipping
        max_val = np.max(np.abs(processed))
        if max_val > 0.95:
            processed = processed * (0.95 / max_val)
        
        return processed.astype(np.float32)
    
    # ─── Machine Learning ────────────────────────────────────────────────────
    def add_training_sample(self, features, label):
        """Agrega una muestra de entrenamiento."""
        self.training_samples.append({
            "features": features.tolist(),
            "label": label,
            "timestamp": time.time()
        })
        self._save_samples()
        
        if len(self.training_samples) >= 10:
            self.train_model()
    
    def train_model(self):
        """Entrena el clasificador con las muestras acumuladas."""
        if len(self.training_samples) < 6:
            return False
        
        X = np.array([s["features"] for s in self.training_samples])
        y = np.array([s["label"] for s in self.training_samples])
        
        # Necesitamos al menos muestras de ambas clases
        unique = np.unique(y)
        if len(unique) < 2:
            return False
        
        try:
            self.scaler.fit(X)
            X_scaled = self.scaler.transform(X)
            
            self.model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                random_state=42,
                class_weight='balanced'
            )
            self.model.fit(X_scaled, y)
            self.model_trained = True
            
            self._save_model()
            
            if self.on_status_update:
                self.on_status_update(f"✅ Modelo entrenado con {len(self.training_samples)} muestras")
            
            return True
        except Exception as e:
            if self.on_status_update:
                self.on_status_update(f"❌ Error entrenando: {e}")
            return False
    
    def predict(self, features):
        """Predice si el sonido es propio o enemigo."""
        if not self.model_trained or self.model is None:
            return "unknown", 0.0
        
        try:
            X = features.reshape(1, -1)
            X_scaled = self.scaler.transform(X)
            pred = self.model.predict(X_scaled)[0]
            proba = self.model.predict_proba(X_scaled)[0]
            confidence = float(np.max(proba))
            return pred, confidence
        except Exception:
            return "unknown", 0.0
    
    # ─── Loop principal de audio ─────────────────────────────────────────────
    def audio_callback(self, indata, outdata, frames, time_info, status):
        """Callback del stream de audio - se ejecuta en tiempo real."""
        try:
            audio = indata.copy()
            
            # Extraer características para ML
            features = self.extract_features(audio)
            
            if features is not None:
                # Modo entrenamiento: guardar muestra etiquetada
                if self.training_mode and self.training_label:
                    self.add_training_sample(features, self.training_label)
                
                # Predicción ML
                pred, conf = self.predict(features)
                self.last_prediction = pred
                self.prediction_confidence = conf
                
                if self.on_prediction_update:
                    self.on_prediction_update(pred, conf)
            
            # Procesar audio con los filtros
            prediction = self.last_prediction
            processed = self.process_audio(audio, prediction)
            outdata[:] = processed
            
            # Nivel de audio para la UI
            level = float(np.sqrt(np.mean(audio**2)))
            self.audio_buffer.append(level)
            
            if self.on_level_update:
                self.on_level_update(level)
        
        except Exception as e:
            outdata[:] = indata  # Pass-through en caso de error
    
    def start(self, input_device=None, output_device=None):
        """Inicia el procesamiento de audio."""
        self.running = True
        
        try:
            self.stream = sd.Stream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                dtype=np.float32,
                channels=CHANNELS,
                device=(input_device, output_device),
                callback=self.audio_callback,
                latency='low'
            )
            self.stream.start()
            
            if self.on_status_update:
                self.on_status_update("🎮 Audio engine activo")
            
            return True
        except Exception as e:
            self.running = False
            if self.on_status_update:
                self.on_status_update(f"❌ Error: {e}")
            return False
    
    def stop(self):
        """Detiene el procesamiento."""
        self.running = False
        if hasattr(self, 'stream'):
            self.stream.stop()
            self.stream.close()
    
    def set_training_mode(self, active, label=None):
        self.training_mode = active
        self.training_label = label
    
    def get_sample_count(self):
        mine = sum(1 for s in self.training_samples if s["label"] == "mine")
        enemy = sum(1 for s in self.training_samples if s["label"] == "enemy")
        return mine, enemy
    
    def clear_samples(self):
        self.training_samples = []
        self.model = None
        self.model_trained = False
        self._save_samples()
        if MODEL_FILE.exists():
            MODEL_FILE.unlink()
    
    # ─── Persistencia ────────────────────────────────────────────────────────
    def _save_model(self):
        with open(MODEL_FILE, 'wb') as f:
            pickle.dump(self.model, f)
        with open(SCALER_FILE, 'wb') as f:
            pickle.dump(self.scaler, f)
    
    def _load_model(self):
        try:
            if MODEL_FILE.exists() and SCALER_FILE.exists():
                with open(MODEL_FILE, 'rb') as f:
                    self.model = pickle.load(f)
                with open(SCALER_FILE, 'rb') as f:
                    self.scaler = pickle.load(f)
                self.model_trained = True
        except Exception:
            pass
    
    def _save_samples(self):
        with open(SAMPLES_FILE, 'w') as f:
            json.dump(self.training_samples, f)
    
    def _load_samples(self):
        try:
            if SAMPLES_FILE.exists():
                with open(SAMPLES_FILE, 'r') as f:
                    self.training_samples = json.load(f)
        except Exception:
            self.training_samples = []

# ─── Utilidades ──────────────────────────────────────────────────────────────
def list_audio_devices():
    """Lista todos los dispositivos de audio disponibles."""
    devices = sd.query_devices()
    result = []
    for i, d in enumerate(devices):
        result.append({
            "id": i,
            "name": d['name'],
            "inputs": d['max_input_channels'],
            "outputs": d['max_output_channels'],
            "default_sr": d['default_samplerate']
        })
    return result

def detect_audio_software() -> dict:
    """
    Detecta software de audio virtual instalado (VB-Cable, Voicemeter, EQ APO).
    Solo LEE el estado del sistema. NO modifica ninguna configuración existente.
    """
    result = {
        "vb_cable":              False,
        "voicemeeter":           False,
        "eq_apo":                False,
        "suggested_input":       None,
        "suggested_input_name":  None,
        "detected":              [],   # lista de strings para mostrar en la UI
    }

    # ── Escanear dispositivos de audio ─────────────────────────────────────
    try:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            name_lower = d['name'].lower()

            # VB-Cable
            if 'cable' in name_lower and not result["vb_cable"]:
                if d['max_input_channels'] > 0 or d['max_output_channels'] > 0:
                    result["vb_cable"] = True
                    result["detected"].append(f"VB-Cable  ({d['name']})")
                    # Preferir «CABLE Output» como entrada de captura
                    if d['max_input_channels'] > 0 and result["suggested_input"] is None:
                        result["suggested_input"]      = i
                        result["suggested_input_name"] = d['name']

            # Voicemeter (cualquier variante: Banana, Potato, etc.)
            if 'voicemeeter' in name_lower:
                if not result["voicemeeter"]:
                    result["voicemeeter"] = True
                    result["detected"].append(f"Voicemeter  ({d['name']})")
                # El output virtual de Voicemeter es la captura del mix
                if ('output' in name_lower or 'vaio' in name_lower) and d['max_input_channels'] > 0:
                    if result["suggested_input"] is None:
                        result["suggested_input"]      = i
                        result["suggested_input_name"] = d['name']
    except Exception:
        pass

    # ── Detectar EQ APO (sólo lectura de registro/directorio) ──────────────
    if sys.platform == 'win32':
        try:
            import winreg
            winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EqualizerAPO")
            result["eq_apo"] = True
            result["detected"].append("Equalizer APO")
        except Exception:
            pass

        if not result["eq_apo"]:
            for eq_path in [
                r"C:\Program Files\EqualizerAPO",
                r"C:\Program Files (x86)\EqualizerAPO",
            ]:
                if os.path.isdir(eq_path):
                    result["eq_apo"] = True
                    result["detected"].append("Equalizer APO")
                    break

    return result


if __name__ == "__main__":
    print("Warzone Audio Engine - Test")
    for d in list_audio_devices():
        print(f"[{d['id']}] {d['name']} | IN:{d['inputs']} OUT:{d['outputs']}")
