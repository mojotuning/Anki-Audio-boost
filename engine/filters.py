"""
Filtros de audio: EQ por banda, expander, highpass, noise gate, reducción de ruido y limiter.
"""
import numpy as np
from scipy import signal

from .config import SAMPLE_RATE

# Clases de predicción por grupo — frozenset para lookup O(1) en el hot-path RT
_CLS_MINE_FEET  = frozenset({'mine_feet', 'mine'})
_CLS_ENEMY      = frozenset({'enemy_feet', 'enemy', 'enemy_guns'})


class FiltersMixin:

    # ─── Upward expander ─────────────────────────────────────────────────────

    def _expander_gain(self, band_signal_rms: float, band_key: tuple, boosting: bool) -> float:
        """
        Devuelve un multiplicador [0.0–1.0] que escala la ganancia del EQ.
        Si la señal en la banda apenas supera el piso de ruido → gain = 0 (no boost).
        Si la señal está claramente por encima → gain = 1.0 (boost completo).
        Solo actúa en bandas con boost (gain_db > 0). En atenuaciones siempre = 1.0.
        """
        if not boosting:
            return 1.0   # atenuaciones siempre se aplican completas

        floor = self._band_noise_floor.get(band_key, band_signal_rms)

        # Actualizar piso: alpha lento cuando la señal es baja (sigue el ruido),
        # alpha rápido cuando hay señal para no «pegarse» a ella.
        above = band_signal_rms > floor * (10 ** (self._expander_threshold_db / 20))
        alpha = self._expander_alpha_fast if above else self._expander_alpha_slow
        self._band_noise_floor[band_key] = (
            alpha * band_signal_rms + (1 - alpha) * floor
        )

        if floor < 1e-9:
            return 1.0
        # Ratio señal/piso en dB
        ratio_db = 20 * np.log10(max(band_signal_rms, 1e-9) / floor)
        # Fade lineal: 0 → 0 dB sobre el piso, 1 → threshold_db sobre el piso
        t = np.clip(ratio_db / self._expander_threshold_db, 0.0, 1.0)
        return float(t)

    # ─── EQ por banda ─────────────────────────────────────────────────────────

    def apply_eq_band(self, audio: np.ndarray, low_hz: float, high_hz: float, gain_db: float) -> np.ndarray:
        """Aplica ganancia a una banda usando sosfilt con estado persistente + upward expander.
        El expander asegura que no se amplifique el piso de ruido cuando no hay señal real.
        """
        if abs(gain_db) < 0.05:   # umbral: evita aplicar filtros casi-neutros
            return audio
        nyq  = SAMPLE_RATE / 2.0
        low  = max(low_hz  / nyq, 0.001)
        high = min(high_hz / nyq, 0.999)
        if low >= high:
            return audio

        band_key = (low_hz, high_hz)
        if band_key not in self._sos_cache:
            self._sos_cache[band_key] = signal.butter(4, [low, high], btype='band', output='sos')
        sos = self._sos_cache[band_key]
        n_ch            = audio.shape[1] if audio.ndim > 1 else 1
        gain_linear_full = 10.0 ** (gain_db / 20.0)
        boosting        = gain_db > 0.0
        result          = audio.copy()

        for ch in range(n_ch):
            x   = audio[:, ch] if audio.ndim > 1 else audio.ravel()
            key = (band_key, ch)
            if key not in self._filter_zi:
                self._filter_zi[key] = signal.sosfilt_zi(sos) * x[0]
            band_signal, self._filter_zi[key] = signal.sosfilt(sos, x, zi=self._filter_zi[key])

            # RMS solo del canal 0 para el expander (evitar cálculo doble)
            if ch == 0:
                band_rms   = float(np.sqrt(np.mean(band_signal ** 2)))
                exp_factor = self._expander_gain(band_rms, band_key, boosting)
            # Interpolar gain: en silencio gain=1 (sin tocar), con señal gain=gain_linear_full
            effective_gain = 1.0 + (gain_linear_full - 1.0) * exp_factor
            processed_ch   = x - band_signal + band_signal * effective_gain
            if audio.ndim > 1:
                result[:, ch] = processed_ch
            else:
                result = processed_ch

        return result.astype(audio.dtype)

    # ─── Buffer y configuración ───────────────────────────────────────────────

    def set_buffer_size(self, size: int):
        """Cambia el tamaño del buffer de audio (equivalente a WDM Buffering en Voicemeeter).
        Valores comunes: 256 (mínima latencia), 512, 1024, 2048 (máxima estabilidad).
        Aplica al siguiente Start; no interrumpe el stream en curso.
        """
        valid = (128, 256, 512, 1024, 2048)
        if size in valid:
            self.block_size = size

    def set_noise_config(self, config: dict):
        """Actualiza parámetros de reducción de ruido desde la UI."""
        self.noise_config.update(config)

    # ─── Reducción de ruido ───────────────────────────────────────────────────

    def _apply_highpass(self, audio: np.ndarray) -> np.ndarray:
        """Butterworth HPF a 100 Hz con estado persistente (sin clicks)."""
        _hp_key = ('hp', 100)
        if _hp_key not in self._sos_cache:
            self._sos_cache[_hp_key] = signal.butter(4, 100.0 / (SAMPLE_RATE / 2.0), btype='highpass', output='sos')
        sos  = self._sos_cache[_hp_key]
        n_ch = audio.shape[1] if audio.ndim > 1 else 1
        result = audio.copy()
        for ch in range(n_ch):
            x = audio[:, ch] if audio.ndim > 1 else audio.ravel()
            if ch not in self._hp_zi:
                self._hp_zi[ch] = signal.sosfilt_zi(sos) * x[0]
            y, self._hp_zi[ch] = signal.sosfilt(sos, x, zi=self._hp_zi[ch])
            if audio.ndim > 1:
                result[:, ch] = y
            else:
                result = y
        return result.astype(audio.dtype)

    def _apply_noise_gate(self, audio: np.ndarray) -> np.ndarray:
        """Silencia bloques cuyo RMS está por debajo del umbral."""
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < self.noise_config['gate_threshold']:
            return np.zeros_like(audio)
        return audio

    def _apply_noise_reduction(self, audio: np.ndarray) -> np.ndarray:
        """Sustracción espectral: estima el piso de ruido y lo resta."""
        strength = float(self.noise_config['nr_strength'])
        result   = audio.copy()
        channels = audio.shape[1] if audio.ndim > 1 else 1
        for ch in range(channels):
            x     = audio[:, ch] if audio.ndim > 1 else audio
            spec  = np.fft.rfft(x)
            mag   = np.abs(spec)
            phase = np.angle(spec)
            # Actualizar estimación del piso de ruido (estadística mínima)
            self._noise_floor_buf.append(mag)
            if len(self._noise_floor_buf) >= 5:
                noise_est = np.min(self._noise_floor_buf, axis=0)
            else:
                noise_est = mag * 0.1
            # Sustraer piso de ruido y reconstruir
            mag_clean  = np.maximum(mag - strength * noise_est, 0.0)
            spec_clean = mag_clean * np.exp(1j * phase)
            x_clean    = np.fft.irfft(spec_clean, n=len(x))
            if audio.ndim > 1:
                result[:, ch] = x_clean
            else:
                result = x_clean.astype(audio.dtype)
        return result.astype(np.float32)

    # ─── Pipeline principal ───────────────────────────────────────────────────

    def _process_audio_for_preview(self, audio_chunk: np.ndarray, prediction: str) -> np.ndarray:
        """Aplica el mismo EQ que process_audio pero de forma stateless (sosfiltfilt,
        fase cero) para que el preview suene como el audio normal sin contaminar
        el estado del stream ni los datos de entrenamiento."""
        processed = audio_chunk.copy().astype(np.float64)

        # HP stateless (si está activado)
        if self.noise_config['hp_enabled']:
            _hp_key = ('hp', 100)
            if _hp_key not in self._sos_cache:
                self._sos_cache[_hp_key] = signal.butter(
                    4, 100.0 / (SAMPLE_RATE / 2.0), btype='highpass', output='sos')
            sos  = self._sos_cache[_hp_key]
            n_ch = processed.shape[1] if processed.ndim > 1 else 1
            for ch in range(n_ch):
                x = processed[:, ch] if processed.ndim > 1 else processed.ravel()
                y = signal.sosfiltfilt(sos, x)
                if processed.ndim > 1:
                    processed[:, ch] = y
                else:
                    processed = y

        def _band(audio, low_hz, high_hz, gain_db):
            if gain_db == 0.0:
                return audio
            nyq  = SAMPLE_RATE / 2.0
            low  = max(low_hz  / nyq, 0.001)
            high = min(high_hz / nyq, 0.999)
            if low >= high:
                return audio
            band_key = (low_hz, high_hz)
            if band_key not in self._sos_cache:
                self._sos_cache[band_key] = signal.butter(
                    4, [low, high], btype='band', output='sos')
            sos         = self._sos_cache[band_key]
            gain_linear = 10.0 ** (gain_db / 20.0)
            n_ch        = audio.shape[1] if audio.ndim > 1 else 1
            result      = audio.copy()
            for ch in range(n_ch):
                x  = audio[:, ch] if audio.ndim > 1 else audio.ravel()
                b  = signal.sosfiltfilt(sos, x)
                pc = x - b + b * gain_linear
                if audio.ndim > 1:
                    result[:, ch] = pc
                else:
                    result = pc
            return result.astype(audio.dtype)

        def db(key):
            return 20.0 * np.log10(max(self.gains[key], 1e-6))

        if prediction in _CLS_MINE_FEET:
            processed = _band(processed, 80,  600,  db('own_footsteps'))
            processed = _band(processed, 600, 4000, db('enemy_gunshots'))
            processed = _band(processed, 40,  200,  db('airstrikes'))
        elif prediction == 'mine_guns':
            processed = _band(processed, 80,  600,  db('enemy_footsteps'))
            processed = _band(processed, 600, 4000, db('own_gunshots'))
            processed = _band(processed, 40,  200,  db('airstrikes'))
        elif prediction == 'airstrike':
            processed = _band(processed, 40,  200,  db('airstrike_vol'))
            processed = _band(processed, 80,  600,  db('enemy_footsteps'))
            processed = _band(processed, 600, 4000, db('enemy_gunshots'))
        elif prediction in _CLS_ENEMY:
            processed = _band(processed, 80,  600,  db('enemy_footsteps'))
            processed = _band(processed, 600, 4000, db('enemy_gunshots'))
            processed = _band(processed, 40,  200,  db('airstrikes'))
        # else: unknown → solo HP si estaba habilitado, sin EQ

        return processed.astype(np.float32)

    def process_audio(self, audio_chunk, prediction):
        """
        4 clases de entrenamiento:
          mine_feet  → atenuar graves 80-600 Hz (mis pasos)
          mine_guns  → atenuar medios 600-4000 Hz (mis disparos)
          enemy_feet → boost graves (pasos enemigo)
          enemy_guns → boost medios (disparos enemigo)
          unknown    → boost todo (modo por defecto, sin modelo)

        Backward compat: 'mine' → mine_feet, 'enemy' → enemy_feet
        """
        # Bypass: pasar el audio sin ningún procesamiento
        if getattr(self, 'bypass', False):
            return audio_chunk.astype(np.float32)

        processed = audio_chunk.copy().astype(np.float64)

        # ─── Reducción de ruido (antes del EQ) ──────────────────────────────
        if self.noise_config['hp_enabled']:
            processed = self._apply_highpass(processed)
        if self.noise_config['gate_enabled']:
            processed = self._apply_noise_gate(processed)
        if self.noise_config['nr_enabled']:
            processed = self._apply_noise_reduction(processed)

        def db(key):
            return 20.0 * np.log10(max(self.gains[key], 1e-6))

        # ── EQ por clase: UNA banda por clase, sin solapamiento ─────────
        # Problema anterior: cada clase aplicó 3 bandas simultáneamente usando
        # ganancias de OTRAS clases. Eso causa:
        #   · audio fino: corte de -20 dB en 80-600 Hz elimina el cuerpo del audio
        #   · inconsistencia: 'mine_feet' también boostó 'enemy_gunshots' sin razón
        # Solución: una clase → una banda, sin efectos colaterales.
        if prediction in _CLS_MINE_FEET:
            t_low, t_mid, t_sub = db('own_footsteps'), 0.0, 0.0      # cortar graves: mis pasos
        elif prediction == 'mine_guns':
            t_low, t_mid, t_sub = 0.0, db('own_gunshots'), 0.0       # cortar medios: mis disparos
        elif prediction == 'enemy_feet' or prediction == 'enemy':
            t_low, t_mid, t_sub = db('enemy_footsteps'), 0.0, 0.0    # boost graves: pasos enemigo
        elif prediction == 'enemy_guns':
            t_low, t_mid, t_sub = 0.0, db('enemy_gunshots'), 0.0     # boost medios: disparos enemigo
        elif prediction == 'airstrike':
            t_low, t_mid, t_sub = 0.0, 0.0, db('airstrike_vol')      # atenuar sub: ataque aéreo
        else:   # unknown / sin modelo → no hay corrección, solo lo que ya se aplicó antes
            t_low, t_mid, t_sub = 0.0, 0.0, 0.0

        # ── Interpolación suave hacia target: elimina clicks en transiciones ──
        # Sin esto: cambio de clase en 1 bloque (21 ms) = salto brusco de ganancia
        # en la banda = discontinuidad en el filtro IIR = click audible.
        # Con _S=0.12: 8 bloques ≈ 170 ms de fundido cruzado.
        _S = 0.12
        eq = self._eq_smooth
        eq['low_db'] += _S * (t_low - eq['low_db'])
        eq['mid_db'] += _S * (t_mid - eq['mid_db'])
        eq['sub_db'] += _S * (t_sub - eq['sub_db'])

        # ── Aplicar solo bandas con corrección significativa ──────────────
        if abs(eq['low_db']) >= 0.05:
            processed = self.apply_eq_band(processed, 80,  600,  eq['low_db'])
        if abs(eq['mid_db']) >= 0.05:
            processed = self.apply_eq_band(processed, 600, 4000, eq['mid_db'])
        if abs(eq['sub_db']) >= 0.05:
            processed = self.apply_eq_band(processed, 40,  200,  eq['sub_db'])

        # ── Retorno directo si no hubo ningún procesamiento ──────────────
        nr_active = (self.noise_config['hp_enabled'] or
                     self.noise_config['gate_enabled'] or
                     self.noise_config['nr_enabled'])
        eq_active = (abs(eq['low_db']) >= 0.05 or
                     abs(eq['mid_db']) >= 0.05 or
                     abs(eq['sub_db']) >= 0.05)
        if not eq_active and not nr_active:
            return audio_chunk.astype(np.float32)

        # ── Limiter suave con attack/release ────────────────────────────────
        # Attack: instantáneo (el gain baja de golpe al target del bloque).
        #   Esto no causa clicks porque el bloque ya está procesado como unidad.
        # Release: suave (~20 bloques = ~420 ms) → sin artefactos al recuperar.
        # Ceiling 0.90 da headroom para transientes de filtro entre bloques.
        # Hard clip final a 0.95 como red de seguridad (casi nunca activa).
        ceiling = 0.90
        peak    = float(np.max(np.abs(processed)))
        if peak > 1e-9:
            target_gain = min(ceiling / peak, 1.0)
        else:
            target_gain = 1.0

        if target_gain < self._limiter_env:
            self._limiter_env = target_gain           # attack instantáneo
        else:
            self._limiter_env = min(
                self._limiter_release + (1.0 - self._limiter_release) * self._limiter_env,
                1.0
            )

        processed = processed * self._limiter_env
        np.clip(processed, -0.95, 0.95, out=processed)   # failsafe

        return processed.astype(np.float32)
