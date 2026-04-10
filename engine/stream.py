"""
Gestión del stream de audio: callback, hilo de análisis ML, start y stop.
"""
import queue
import threading
import time as _time
from collections import Counter

import numpy as np
import sounddevice as sd

from .config import SAMPLE_RATE, CHANNELS, REVIEW_WINDOW_BLOCKS, PRED_WINDOW_BLOCKS

# Throttle: empujar a UI máx cada N segundos (evita saturar pywebview evaluate_js)
_PRED_PUSH_INTERVAL = 0.40  # segundos — cambio de clase siempre es inmediato


class StreamMixin:

    def _mix_preview_block(self, processed: np.ndarray) -> np.ndarray:
        """Mezcla el siguiente bloque de preview en `processed`.
        - Si la cola tiene datos: suma el bloque y lo clampea a ±0.98.
        - Si la cola se vacía: activa _preview_ended_flag (señal para hilo ML).
        NUNCA llama on_status_update directamente — ese callback puede bloquear
        si pywebview está esperando el WebView2 message pump, causando underrun.
        Thread-safe: deque.popleft() es atómico bajo el GIL de CPython."""
        if not self._preview_queue:
            if self._preview_active:
                self._preview_active    = False
                self._preview_ended_flag = True   # el _analysis_worker lo consume
            return processed
        try:
            pv     = self._preview_queue.popleft()
            out_ch = processed.shape[1] if processed.ndim > 1 else 1
            pv_ch  = pv.shape[1]        if pv.ndim  > 1 else 1
            if pv_ch < out_ch:
                pv = np.tile(pv, (1, -(-out_ch // pv_ch)))[:, :out_ch]
            elif pv_ch > out_ch:
                pv = pv[:, :out_ch]
            n      = min(len(processed), len(pv))
            result = processed.copy()
            result[:n] = np.clip(result[:n] + pv[:n], -0.98, 0.98)
            return result.astype(np.float32)
        except Exception:
            return processed

    def audio_callback(self, indata, outdata, frames, time_info, status):
        """Callback del stream de audio — DEBE ser ultrarrápido, sin cálculos pesados."""
        try:
            audio = indata.copy()
            # Durante grabación, pasar audio limpio sin EQ (bypass completo)
            if self.training_mode:
                processed = audio.astype(np.float32)
            else:
                processed = self.process_audio(audio, self.effective_prediction)
            # Mezclar preview de revisión si está activo (mismo dispositivo que el stream)
            processed = self._mix_preview_block(processed)

            # Ajuste de canales: si processed no coincide con outdata, recortar o rellenar.
            # Sin este guard, outdata[:] = processed lanza ValueError si in_ch != out_ch,
            # la excepción se captura en silencio y outdata queda sin inicializar → basura → static.
            if processed.ndim == 2:
                out_ch = outdata.shape[1] if outdata.ndim > 1 else 1
                if processed.shape[1] > out_ch:
                    processed = processed[:, :out_ch]
                elif processed.shape[1] < out_ch:
                    processed = np.pad(processed, ((0, 0), (0, out_ch - processed.shape[1])))
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
        # Variables locales para el caso en que el bucle termina sin predecir
        voted_pred = "unknown"
        voted_conf = 0.0
        prev_pred  = "unknown"

        while self.running:
            # Consumir flag de fin de preview desde este hilo (no-RT) para evitar
            # que evaluate_js bloquee el callback de PortAudio.
            if getattr(self, '_preview_ended_flag', False):
                self._preview_ended_flag = False
                if self.on_status_update:
                    self.on_status_update('__preview_ended__')

            try:
                audio = self._analysis_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                # ── Acumulación para ENTRENAMIENTO (→ revisar chunk) ──────────
                if self.training_mode and self.training_label:
                    self._train_accum.append(audio)
                    if len(self._train_accum) >= REVIEW_WINDOW_BLOCKS:
                        self._push_review_chunk(self.training_label)
                        self._train_accum.clear()
                else:
                    if self._train_accum:
                        self._train_accum.clear()   # cancelada grabación

                # ── Acumulación para PREDICCIÓN (~500 ms por ventana) ─────────
                self._pred_accum.append(audio)
                if len(self._pred_accum) < PRED_WINDOW_BLOCKS:
                    continue   # aún no hay suficiente audio

                pred_audio = np.concatenate(list(self._pred_accum), axis=0)
                self._pred_accum.clear()

            except Exception:
                continue

            try:
                features = self.extract_features(pred_audio)
                if features is None:
                    continue

                pred, conf = self.predict(features)

                # ── Ventana de votación: suavizar entre las últimas N predicciones ─
                self._pred_window.append((pred, conf))
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

                # ── Estadísticas de sesión ────────────────────────────────────────
                # Confianza media con algoritmo de Welford (O(1) por muestra, sin lista):
                #   _conf_n: número de muestras; _conf_mean: media acumulada
                stats = self._session_stats
                stats['blocks_processed'] += 1
                eff = self.effective_prediction
                stats['class_counts'][eff] = stats['class_counts'].get(eff, 0) + 1
                if voted_conf > 0:
                    n = stats['_conf_n'] + 1
                    stats['_conf_mean'] += (voted_conf - stats['_conf_mean']) / n
                    stats['_conf_n']     = n

            except Exception:
                continue

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

        # Limpiar cola de análisis, ventana de votación y acumuladores
        while not self._analysis_queue.empty():
            try:
                self._analysis_queue.get_nowait()
            except queue.Empty:
                break
        self._pred_window.clear()
        self._pred_accum.clear()
        self._train_accum.clear()

        # Resetear interpolación EQ suave para no heredar estado de sesión anterior
        self._eq_smooth = {'low_db': 0.0, 'mid_db': 0.0, 'sub_db': 0.0}
        self._limiter_env = 1.0

        # Reiniciar estadísticas de sesión
        self._session_stats = {
            'start_time':       _time.time(),
            'blocks_processed': 0,
            'class_counts':     {},
            '_conf_n':          0,      # contador Welford
            '_conf_mean':       0.0,    # media de confianza acumulada (Welford)
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
            # out_buf es un buffer pequeño entre los dos streams (relojes independientes).
            # Se usa un deque mutable como contenedor del último bloque procesado para
            # que _out_cb siempre tenga algo que reproducir en caso de underrun.
            # Esto elimina los clicks periódicos causados por outdata[:] = 0 cuando
            # el reloj de salida adelanta al de entrada (deriva de relojes ≈ 200 ppm).
            out_buf   = queue.Queue(maxsize=4)   # pequeño → menos latencia acumulada
            _last_blk = [np.zeros((self.block_size, o_ch), dtype=np.float32)]

            def _in_cb(indata, frames, time_info, status):
                try:
                    audio = indata.copy()
                    # Durante grabación, pasar audio limpio sin EQ (bypass completo)
                    if self.training_mode:
                        processed = audio.astype(np.float32)
                    else:
                        processed = self.process_audio(audio, self.effective_prediction)
                    if processed.ndim == 2 and processed.shape[1] != o_ch:
                        if processed.shape[1] > o_ch:
                            processed = processed[:, :o_ch]
                        else:
                            processed = np.pad(
                                processed, ((0, 0), (0, o_ch - processed.shape[1])))
                    # Mezclar preview de revisión (mismo dispositivo que el stream)
                    processed = self._mix_preview_block(processed)
                    _last_blk[0] = processed          # guardar último bloque válido
                    try:
                        out_buf.put_nowait(processed)
                    except queue.Full:
                        try:
                            out_buf.get_nowait()       # descartar el más antiguo
                            out_buf.put_nowait(processed)
                        except Exception:
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
                    # Repetir el último bloque válido en lugar de ceros.
                    # Ceros → transición abrupta audio→silencio→audio = click.
                    # Repetir el bloque anterior = continuidad sin artefactos.
                    outdata[:] = _last_blk[0][:len(outdata)]

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
                    self._stream_samplerate = sr
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
            self._stream_samplerate = best_sr
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
