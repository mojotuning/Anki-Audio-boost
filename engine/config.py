"""
Constantes globales del motor de audio.
"""
import sys
import os
from pathlib import Path

SAMPLE_RATE  = 48000   # Hz — Voicemeeter y la mayoría de interfaces modernas
BLOCK_SIZE   = 1024    # Muestras por bloque
CHANNELS     = 2


def _get_data_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(os.path.dirname(sys.executable)) / "data"
    return Path("data")


DATA_DIR     = _get_data_dir()
MODEL_FILE   = DATA_DIR / "model.pkl"
SCALER_FILE  = DATA_DIR / "scaler.pkl"
SAMPLES_FILE = DATA_DIR / "samples.json"

DATA_DIR.mkdir(exist_ok=True)

# Rangos de frecuencia para cada tipo de sonido
FREQ_RANGES = {
    "footsteps":  (80,  600),    # Pasos: graves/medios bajos
    "gunshots":   (600, 4000),   # Disparos: medios/agudos
    "airstrikes": (40,  200),    # Aéreos: sub-graves
    "ambient":    (200, 800),    # Ambiente general
}
