"""
AudioEngine — clase principal que une todos los mixins.
"""
import queue
from collections import deque

from sklearn.preprocessing import StandardScaler

from .config     import BLOCK_SIZE, DATA_DIR, PRED_VOTE_WINDOW
from .features   import FeaturesMixin
from .filters    import FiltersMixin
from .ml         import MLMixin
from .review     import ReviewMixin
from .stream     import StreamMixin


class AudioEngine(FeaturesMixin, FiltersMixin, MLMixin, ReviewMixin, StreamMixin):
    """
    Motor de audio intelligent para Warzone.
    Hereda de los mixins que implementan cada subsistema:
      FeaturesMixin — extracción de características para el clasificador ML
      FiltersMixin  — EQ por banda, expander, highpass, noise gate, limiter
      MLMixin       — entrenamiento, predicción y persistencia del modelo
      StreamMixin   — callback de audio, hilo de análisis, start/stop
    """

    def __init__(self):
        self.running        = False
        self.training_mode  = False
        self.training_label = None

        # ── Ganancias por banda (lineal) ──────────────────────────────────
        self.gains = {
            "enemy_footsteps": 1.6,   # +4 dB
            "own_footsteps":   0.1,   # −20 dB
            "enemy_gunshots":  1.4,   # +3 dB
            "own_gunshots":    0.1,   # −20 dB
            "airstrike_vol":   0.15,  # −16 dB
            "airstrikes":      1.4,   # +3 dB
        }

        # ── Buffers ───────────────────────────────────────────────────────
        self.audio_buffer   = deque(maxlen=100)
        self.feature_buffer = deque(maxlen=50)
        self.training_samples = []

        # Cola para análisis ML en hilo separado (no bloquear callback)
        self._analysis_queue  = queue.Queue(maxsize=8)
        self._analysis_thread = None

        # ── Estado ML ─────────────────────────────────────────────────────
        self.model                 = None
        self.scaler                = StandardScaler()
        self.model_trained         = False
        self.last_prediction       = "unknown"
        self.prediction_confidence = 0.0
        # Predicción efectiva usada por el EQ (= unknown si conf < umbral)
        self.effective_prediction  = "unknown"
        # Umbral de confianza mínimo para aplicar el EQ de la clase detectada
        self.confidence_threshold  = 0.60   # 60 % por defecto
        # Precisión por clase del último entrenamiento
        self._accuracy_report: dict = {}

        # Ventana de votación: votar entre las últimas N predicciones para suavizar
        self._pred_window: deque = deque(maxlen=PRED_VOTE_WINDOW)

        # ── Tamaño de bloque (ajustable desde la UI) ──────────────────────
        self.block_size = BLOCK_SIZE

        # ── Estado de filtros IIR (evita clicks entre bloques) ────────────
        self._filter_zi: dict = {}  # clave: ((low_hz, high_hz), canal) → zi
        self._hp_zi:     dict = {}  # clave: canal → zi

        # ── Upward expander ───────────────────────────────────────────────
        self._band_noise_floor:    dict  = {}
        self._sos_cache:           dict  = {}  # coeficientes SOS Butterworth por banda (inmutables)
        self._expander_alpha_slow  = 0.001  # tau ≈ 20 s
        self._expander_alpha_fast  = 0.05   # tau ≈ 0.4 s
        self._expander_threshold_db = 6.0   # dB sobre el piso para boost completo

        # ── Limiter suave ─────────────────────────────────────────────────
        self._limiter_env     = 1.0
        self._limiter_attack  = 0.85  # convergencia rápida (≈1 bloque)
        self._limiter_release = 0.05  # suelta gradual   (≈20 bloques)

        # ── Callbacks para la UI ──────────────────────────────────────────
        self.on_level_update      = None
        self.on_prediction_update = None
        self.on_status_update     = None
        self._last_pred_push      = 0.0   # throttle para on_prediction_update

        # ── Audio ring buffer para etiquetado retroactivo ─────────────────
        # 35 segundos: 35 * 48000 / 1024 ≈ 1646 bloques → maxlen=1650
        self._audio_ring: deque = deque(maxlen=1650)

        # ── Reducción de ruido ────────────────────────────────────────────
        self.noise_config = {
            'gate_enabled':   False,
            'gate_threshold': 0.02,
            'nr_enabled':     False,
            'nr_strength':    0.7,
            'hp_enabled':     False,
        }
        self._noise_floor_buf = deque(maxlen=50)  # ~1 s a 48000/1024

        # ── Dispositivos ──────────────────────────────────────────────────
        self.input_device  = None
        self.output_device = None

        # ── Bypass toggle (pasa audio sin procesar) ──────────────────────
        self.bypass = False

        # ── Preview de revisión (inyección en el stream de salida) ───────
        # Bloquecitos float32 pre-calculados listos para mezclar en outdata.
        # Asignación atómica de referencia (GIL): thread-safe entre callback
        # de PortAudio y el hilo de la API de pywebview.
        self._preview_queue     = deque()   # deque de (BLOCK_SIZE, ch) float32
        self._preview_active    = False     # True mientras hay cola pendiente
        self._stream_samplerate = 48000     # SR real del stream al arrancar
        # Flag para señalizar al hilo ML que el preview ha terminado.
        # NO se llama on_status_update desde el callback RT (bloquearía PortAudio).
        self._preview_ended_flag = False

        # ── Estadísticas de sesión ─────────────────────────────────────────
        self._session_stats = {
            'start_time':      None,
            'blocks_processed': 0,
            'class_counts':    {},
            'confidences':     [],
        }

        self._init_review()

        self._load_model()
        self._load_samples()
