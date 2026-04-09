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

# ── ML ventana y features ──────────────────────────────────────────────────
# Número de bloques de 1024 muestras que se acumulan antes de extraer features.
# 1440 bloques × 1024 / 48000 Hz = 30.72 s — ventana de revisión larga: se oye el sonido completo
#   en contexto, se puede clasificar con certeza, y genera pocos fragmentos por sesión.
# 48 bloques × 1024 / 48000 Hz = 1.024 s — ventana de predicción en tiempo real.
REVIEW_WINDOW_BLOCKS = 1440  # bloques acumulados por cada chunk de revisión (~30 s)
PRED_WINDOW_BLOCKS   = 48    # bloques acumulados antes de cada predicción (~1 s)
PRED_VOTE_WINDOW     = 3     # cuántas predicciones se votan (3 × 1 s = 3 s suavizado)

# Dimensión del vector de features (debe coincidir con lo que produce extract_features).
# 13 MFCC_mean + 13 MFCC_std + 13 delta_mean + 4 bandas + RMS + ZCR + centroid = 46
FEATURE_DIM = 46
