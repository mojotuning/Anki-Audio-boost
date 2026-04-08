"""
Gestión del stream de audio: callback, hilo de análisis ML, start y stop.
"""
import queue
import threading
import time as _time
from collections import Counter

import numpy as np
import sounddevice as sd

from .config import SAMPLE_RATE, CHANNELS

# Throttle: empujar a UI máx cada N segundos (evita saturar pywebview evaluate_js)
_PRED_PUSH_INTERVAL = 0.40  # segundos — cambio de clase siempre es inmediato


class StreamMixin:

    def audio_callback(self, indata, outdata, frames, time_info, status):
        """Callback del stream de audio — DEBE ser ultrarrápido, sin cálculos pesados."""
        try:
            audio     = indata.copy()
            processed = self.process_audio(audio, self.effective_prediction)
            outdata[:] = processed

            # Nivel RMS para el visualizador (operación mínima)
            level = float(np.sqrt(np.mean(audio ** 2)))
            if self.on_level_update:
                self.on_level_update(level)

            # Ring buffer para etiquetado retroactivo (~3 s)
            self._audio_ring.append(audio)

            # Encolar audio para análisis ML (sin bloquear si la cola está llena)
            try:
                self._analysis_queue.put_nowait(audio)
            except queue.Full:
                pass  # Descartar bloque — mejor que bloquear el callback

        except Exception:
            outdata[:] = indata  # Pass-through de seguridad

    def _analysis_worker(self):
        """Hilo de fondo: extrae características y predice. Nunca toca el callback."""
        while self.running:
            try:
                audio = self._analysis_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            features = self.extract_features(audio)
            if features is None:
                continue

            if self.training_mode and self.training_label:
                self.add_training_sample(features, self.training_label)

            pred, conf = self.predict(features)

            # ── Ventana de votación: suavizar con los últimos 5 bloques ──────
            self._pred_window.append((pred, conf))
            # Votar: clase con más votos; en empate, la de mayor confianza media
            votes = Counter(p for p, _ in self._pred_window)
            voted_pred = votes.most_common(1)[0][0]
            voted_conf = sum(c for p, c in self._pred_window if p == voted_pred) / votes[voted_pred]

            prev_pred              = self.last_prediction
            self.last_prediction   = voted_pred
            self.prediction_confidence = voted_conf

            # ── Umbral de confianza: EQ solo si el modelo está seguro ─────────
            if voted_pred == "unknown" or voted_conf < self.confidence_threshold:
                self.effective_prediction = "unknown"
            else:
                self.effective_prediction = voted_pred

            # ── Estadísticas de sesión ─────────────────────────────────────────
            self._session_stats['blocks_processed'] += 1
            eff = self.effective_prediction
            self._session_stats['class_counts'][eff] = \
                self._session_stats['class_counts'].get(eff, 0) + 1
            if voted_conf > 0:
                self._session_stats['confidences'].append(voted_conf)

            if self.on_prediction_update:
                now = _time.monotonic()
                # Enviar inmediatamente si la clase cambia; si no, cada 400 ms
                if voted_pred != prev_pred or (now - self._last_pred_push) >= _PRED_PUSH_INTERVAL:
                    self._last_pred_push = now
                    self.on_prediction_update(voted_pred, voted_conf)

    def start(self, input_device=None, output_device=None):
        """Inicia el procesamiento de audio."""
        self.running = True

        # Guardar dispositivos para autostart
        self.save_last_devices(input_device, output_device)

        # Limpiar cola de análisis y ventana de votación
        while not self._analysis_queue.empty():
            try:
                self._analysis_queue.get_nowait()
            except queue.Empty:
                break
        self._pred_window.clear()

        # Reiniciar estadísticas de sesión
        self._session_stats = {
            'start_time':       _time.time(),
            'blocks_processed': 0,
            'class_counts':     {},
            'confidences':      [],
        }

        # Hilo de análisis ML (separado del callback de audio)
        self._analysis_thread = threading.Thread(
            target=self._analysis_worker, daemon=True)
        self._analysis_thread.start()

        all_devs  = sd.query_devices()
        host_apis = sd.query_hostapis()

        if input_device is not None:
            input_device = int(input_device)
        if output_device is not None:
            output_device = int(output_device)

        def _ch(dev_idx, kind, use_loopback=False):
            """Canales disponibles."""
            if dev_idx is None:
                return CHANNELS
            if use_loopback and kind == 'in':
                n = int(all_devs[dev_idx]['max_output_channels'])
            else:
                key = 'max_input_channels' if kind == 'in' else 'max_output_channels'
                n   = int(all_devs[dev_idx][key])
            return min(n, CHANNELS) if n > 0 else CHANNELS

        in_ch    = _ch(input_device,  'in')
        out_ch   = _ch(output_device, 'out')
        last_err = None

        # ── Helper: callbacks para streams separados ────────────────────────
        def _make_separate_callbacks(i_ch, o_ch):
            out_buf = queue.Queue(maxsize=32)

            def _in_cb(indata, frames, time_info, status):
                try:
                    audio     = indata.copy()
                    processed = self.process_audio(audio, self.effective_prediction)
                    if processed.shape[1] != o_ch:
                        if processed.shape[1] > o_ch:
                            processed = processed[:, :o_ch]
                        else:
                            processed = np.pad(
                                processed, ((0, 0), (0, o_ch - processed.shape[1])))
                    try:
                        out_buf.put_nowait(processed)
                    except queue.Full:
                        pass
                    self._audio_ring.append(audio)
                    if self.on_level_update:
                        self.on_level_update(float(np.sqrt(np.mean(audio ** 2))))
                    try:
                        self._analysis_queue.put_nowait(audio)
                    except queue.Full:
                        pass
                except Exception:
                    pass

            def _out_cb(outdata, frames, time_info, status):
                try:
                    outdata[:] = out_buf.get_nowait()
                except queue.Empty:
                    outdata[:] = 0

            return _in_cb, _out_cb

        # ── Intentos duplex WASAPI shared (varios SR y latencias) ──────────
        in_native_sr  = int(all_devs[input_device]['default_samplerate'])  if input_device  is not None else SAMPLE_RATE
        out_native_sr = int(all_devs[output_device]['default_samplerate']) if output_device is not None else SAMPLE_RATE
        best_sr       = out_native_sr if out_native_sr == in_native_sr else out_native_sr
        sample_rates_to_try = list(dict.fromkeys([SAMPLE_RATE, best_sr, in_native_sr, 44100]))

        for sr in sample_rates_to_try:
            for lat in ('low', 'high'):
                try:
                    self.stream = sd.Stream(
                        samplerate=sr,
                        blocksize=self.block_size,
                        dtype=np.float32,
                        channels=(max(in_ch, 1), max(out_ch, 1)),
                        device=(input_device, output_device),
                        callback=self.audio_callback,
                        latency=lat,
                    )
                    self.stream.start()
                    if self.on_status_update:
                        self.on_status_update(
                            f"🎮 Audio engine activo  [{in_ch}ch → {out_ch}ch]"
                            f"  // modo: WASAPI shared ({lat}) @ {sr} Hz")
                    return True, None
                except Exception as e:
                    last_err = str(e)
                    if self.on_status_update:
                        self.on_status_update(
                            f"⚠ [WASAPI {sr}Hz {lat}] falló: {last_err} — probando siguiente...")

        # ── Fallback: streams separados (APIs distintas) ────────────────────
        _in_cb2, _out_cb2 = _make_separate_callbacks(in_ch, out_ch)
        try:
            self._in_stream = sd.InputStream(
                samplerate=best_sr, blocksize=self.block_size, dtype=np.float32,
                channels=max(in_ch, 1), device=input_device,
                callback=_in_cb2, latency='high',
            )
            self._out_stream = sd.OutputStream(
                samplerate=best_sr, blocksize=self.block_size, dtype=np.float32,
                channels=max(out_ch, 1), device=output_device,
                callback=_out_cb2, latency='high',
            )
            self._in_stream.start()
            self._out_stream.start()
            self.stream = None
            if self.on_status_update:
                self.on_status_update(
                    f"🎮 Audio engine activo  [{in_ch}ch → {out_ch}ch]  // modo: streams separados")
            return True, None
        except Exception as e:
            last_err = str(e)
            for attr in ('_in_stream', '_out_stream'):
                s = getattr(self, attr, None)
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass
                    setattr(self, attr, None)
            if self.on_status_update:
                self.on_status_update(f"⚠ [streams separados] falló: {last_err}")

        # Todos los intentos fallaron
        self.running = False
        if self.on_status_update:
            self.on_status_update(f"❌ No se pudo abrir el dispositivo: {last_err}")
        return False, last_err

    def stop(self):
        """Detiene el procesamiento."""
        self.running = False
        if self._analysis_thread and self._analysis_thread.is_alive():
            self._analysis_thread.join(timeout=1.0)
        # stream combinado
        if hasattr(self, 'stream') and self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
        # streams separados (fallback modo Voicemeeter)
        for attr in ('_in_stream', '_out_stream'):
            s = getattr(self, attr, None)
            if s is not None:
                try:
                    s.stop()
                    s.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        # Resetear estados de filtros para el próximo Start
        self._filter_zi.clear()
        self._hp_zi.clear()
        self._noise_floor_buf.clear()
        self._band_noise_floor.clear()
        self._limiter_env        = 1.0
        self._pred_window.clear()
        self.effective_prediction = "unknown"
