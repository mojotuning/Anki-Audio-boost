"""
ReviewMixin: gestión de muestras pendientes de revisión y reproducción.

Flujo:
  1. Durante grabación, los bloques se acumulan en _train_accum.
  2. Cada REVIEW_WINDOW_BLOCKS bloques (~500 ms) se crea una entrada en _review_store.
  3. La UI recibe onReviewUpdate() y muestra las entradas pendientes.
  4. El usuario escucha cada chunk (play_sample) y confirma o rechaza.
  5. confirm_sample() extrae features y llama a add_training_sample().
"""
import threading

import numpy as np

from .config import SAMPLE_RATE, REVIEW_WINDOW_BLOCKS

try:
    import sounddevice as _sd
    _SD_OK = True
except Exception:
    _SD_OK = False


class ReviewMixin:

    def _init_review(self):
        self._review_store:   dict  = {}      # id → {id, label, audio, rms}
        self._review_counter: int   = 0
        self._review_lock            = threading.Lock()
        self._train_accum:    list  = []      # bloques acumulados durante grabación
        self._pred_accum:     list  = []      # bloques acumulados para predicción
        self.on_review_update        = None   # callback(rid, label, pending_count)

    # ─── Internos ─────────────────────────────────────────────────────────────

    def _push_review_chunk(self, label: str):
        """Crea un chunk de revisión con los bloques en _train_accum. Thread-safe."""
        if not self._train_accum:
            return
        audio = np.concatenate(self._train_accum, axis=0)
        rms   = float(np.sqrt(np.mean(audio ** 2)))
        if rms < 2e-5:          # silencio absoluto — descartar sin molestar al usuario
            return

        with self._review_lock:
            rid = self._review_counter
            self._review_counter += 1
            self._review_store[rid] = {
                'id':    rid,
                'label': label,
                'audio': audio,
                'rms':   rms,
            }
            pending = len(self._review_store)

        if self.on_review_update:
            self.on_review_update(rid, label, pending)

    # ─── API pública ───────────────────────────────────────────────────────────

    def get_pending_review(self) -> list:
        """
        Devuelve metadatos de todos los chunks pendientes (sin audio crudo).
        Incluye waveform downsampled a 80 puntos para mostrar preview en UI.
        """
        with self._review_lock:
            result = []
            for v in self._review_store.values():
                mono = v['audio'][:, 0] if v['audio'].ndim == 2 else v['audio']
                # Waveform: 80 valores de amplitud pico por segmento
                n          = 80
                chunk_size = max(1, len(mono) // n)
                waveform   = [
                    float(np.max(np.abs(mono[i * chunk_size:(i + 1) * chunk_size])))
                    for i in range(n)
                ]
                result.append({
                    'id':          v['id'],
                    'label':       v['label'],
                    'rms':         round(v['rms'] * 100, 2),
                    'duration_ms': int(len(v['audio']) / SAMPLE_RATE * 1000),
                    'waveform':    waveform,
                })
        return result

    def play_sample(self, sample_id: int) -> dict:
        """Reproduce el chunk de revisión.

        Ruta primaria (motor en marcha): inyecta los bloques PCM en el stream
        de PortAudio que ya está corriendo. El audio sale por el MISMO
        dispositivo de salida que el juego — mismo SR, misma cadena, idéntico
        a lo que escuchará el modelo en producción.

        Ruta de respaldo (motor parado): codifica como WAV base64 y deja que
        el navegador lo reproduzca vía Web Audio API.
        """
        from collections import deque as _deque
        with self._review_lock:
            entry = self._review_store.get(int(sample_id))
        if not entry:
            return {'ok': False, 'error': 'sample not found'}
        try:
            audio_out = entry['audio'].astype(np.float32)
            # Normalizar pico para que sea audible
            peak = float(np.max(np.abs(audio_out)))
            if peak > 1e-4:
                audio_out = audio_out * (0.8 / peak)

            sr          = getattr(self, '_stream_samplerate', SAMPLE_RATE)
            n_samples   = len(audio_out)
            duration_ms = int(n_samples / sr * 1000)
            n_ch        = audio_out.shape[1] if audio_out.ndim > 1 else 1

            if getattr(self, 'running', False):
                # ── Inyección en el stream de PortAudio ────────────────────────
                bs = self.block_size
                blocks = _deque()
                for i in range(0, n_samples, bs):
                    blk = audio_out[i:i + bs]
                    if len(blk) < bs:           # último bloque: rellenar con ceros
                        pad = np.zeros((bs - len(blk), n_ch), dtype=np.float32)
                        blk = np.vstack([blk, pad]) if blk.ndim > 1 else np.concatenate([blk.reshape(-1, 1), pad], axis=0)
                    blocks.append(blk.astype(np.float32))
                # Asignación atómica de referencia — thread-safe bajo el GIL
                self._preview_queue  = blocks
                self._preview_active = True
                return {'ok': True, 'mode': 'stream', 'duration_ms': duration_ms}

            # ── Respaldo: Web Audio API (motor parado) ───────────────────────
            import io
            import base64
            from scipy.io import wavfile
            buf = io.BytesIO()
            wavfile.write(buf, sr, audio_out)
            audio_b64 = base64.b64encode(buf.getvalue()).decode('ascii')
            return {'ok': True, 'mode': 'webaudio',
                    'audio_b64': audio_b64, 'sample_rate': sr, 'duration_ms': duration_ms}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def stop_playback(self) -> dict:
        """Detiene el preview: vacía la cola de inyección (asignación atómica)."""
        from collections import deque as _deque
        self._preview_queue  = _deque()   # atómico bajo el GIL
        self._preview_active = False
        return {'ok': True}

    def confirm_sample(self, sample_id: int) -> dict:
        """Extrae features del chunk y lo añade al modelo. Elimina de pendientes."""
        with self._review_lock:
            entry = self._review_store.pop(int(sample_id), None)
        if not entry:
            return {'ok': False, 'added': 0}
        features = self.extract_features(entry['audio'])
        if features is not None:
            self.add_training_sample(features, entry['label'])
            return {'ok': True, 'added': 1}
        return {'ok': False, 'added': 0}

    def reject_sample(self, sample_id: int) -> dict:
        """Descarta el chunk sin añadirlo al modelo."""
        with self._review_lock:
            self._review_store.pop(int(sample_id), None)
        return {'ok': True}

    def confirm_all_pending(self, label: str = None) -> dict:
        """Confirma todos los pendientes (opcionalmente filtrando por clase)."""
        with self._review_lock:
            if label:
                ids = [k for k, v in self._review_store.items() if v['label'] == label]
            else:
                ids = list(self._review_store.keys())
            entries = [self._review_store.pop(i) for i in ids]

        added = 0
        for entry in entries:
            features = self.extract_features(entry['audio'])
            if features is not None:
                self.add_training_sample(features, entry['label'])
                added += 1
        return {'ok': True, 'added': added}

    def reject_all_pending(self, label: str = None) -> dict:
        """Descarta todos los pendientes (opcionalmente filtrando por clase)."""
        with self._review_lock:
            if label:
                for k in [k for k, v in self._review_store.items() if v['label'] == label]:
                    del self._review_store[k]
            else:
                self._review_store.clear()
        self._train_accum.clear()
        return {'ok': True}
