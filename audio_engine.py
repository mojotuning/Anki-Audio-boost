"""
Warzone Audio Enhancer - Motor de Audio Principal
Thin shim -- la logica real vive en el paquete engine/.
"""
from engine import AudioEngine, list_audio_devices, detect_audio_software  # noqa: F401

# Re-exportar constantes por si algun modulo las importa desde aqui
from engine.config import (  # noqa: F401
    SAMPLE_RATE, BLOCK_SIZE, CHANNELS, FREQ_RANGES,
    DATA_DIR, MODEL_FILE, SCALER_FILE, SAMPLES_FILE,
)
