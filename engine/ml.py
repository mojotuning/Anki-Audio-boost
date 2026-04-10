"""
Machine learning: entrenamiento, predicción, persistencia y gestión de muestras.
"""
import json
import pickle
import threading
import time

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier

from .config import MODEL_FILE, SCALER_FILE, SAMPLES_FILE, DATA_DIR, FEATURE_DIM, PRED_WINDOW_BLOCKS

_PROFILES_FILE  = DATA_DIR / "profiles.json"
_MODEL_META     = DATA_DIR / "model_meta.json"
_SAVE_INTERVAL  = 5.0   # segundos entre escrituras del JSON de muestras


class MLMixin:

    def set_confidence_threshold(self, value: float):
        """Establece el umbral mínimo de confianza [0.0–1.0] para aplicar EQ de clase."""
        self.confidence_threshold = max(0.0, min(1.0, float(value)))

    def get_accuracy_report(self) -> dict:
        """Devuelve el informe de precisión por clase del último entrenamiento."""
        return dict(getattr(self, '_accuracy_report', {}))

    def get_session_stats(self) -> dict:
        """Devuelve un resumen de la sesión actual para mostrar al detener el engine."""
        import time as _t
        stats     = self._session_stats
        start     = stats.get('start_time')
        duration_s = (_t.time() - start) if start else 0
        blocks    = stats.get('blocks_processed', 0)
        mean_conf = stats.get('_conf_mean', 0.0)   # media Welford: O(1), sin iterar lista
        total_active = sum(v for k, v in stats.get('class_counts', {}).items() if k != 'unknown')
        coverage  = (total_active / blocks * 100) if blocks > 0 else 0.0
        return {
            'duration_s':        round(duration_s, 1),
            'blocks_processed':  blocks,
            'class_counts':      dict(stats.get('class_counts', {})),
            'mean_confidence':   round(mean_conf * 100, 1),
            'coverage_pct':      round(coverage, 1),
        }

    def label_recent(self, label: str) -> int:
        """
        Etiqueta los últimos ~3 s de audio capturado (ring buffer) como una única
        muestra de clase label. Extrae features sobre el audio concatenado completo
        en lugar de hacerlo bloque a bloque (1650 llamadas a librosa → 1 llamada).
        """
        if not self._audio_ring:
            return 0
        audio = np.concatenate(list(self._audio_ring), axis=0)
        features = self.extract_features(audio)
        if features is None:
            return 0
        self.add_training_sample(features, label)
        return 1

    # ─── Perfiles de ganancia ─────────────────────────────────────────────────

    def save_profile(self, name: str) -> bool:
        """Guarda las ganancias actuales con el nombre dado."""
        profiles = self._load_profiles()
        profiles[name] = dict(self.gains)
        return self._save_profiles(profiles)

    def load_profile(self, name: str) -> bool:
        """Carga un perfil de ganancias guardado. Devuelve False si no existe."""
        profiles = self._load_profiles()
        if name not in profiles:
            return False
        for key, val in profiles[name].items():
            if key in self.gains:
                self.gains[key] = float(val)
        return True

    def delete_profile(self, name: str) -> bool:
        """Elimina un perfil guardado."""
        profiles = self._load_profiles()
        if name in profiles:
            del profiles[name]
            return self._save_profiles(profiles)
        return False

    def list_profiles(self) -> dict:
        """Devuelve todos los perfiles guardados {nombre: {gains}}."""
        return self._load_profiles()

    def _load_profiles(self) -> dict:
        try:
            if _PROFILES_FILE.exists():
                with open(_PROFILES_FILE, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_profiles(self, profiles: dict) -> bool:
        try:
            with open(_PROFILES_FILE, 'w') as f:
                json.dump(profiles, f, indent=2)
            return True
        except Exception:
            return False

    # ─── Persistencia de último dispositivo ──────────────────────────────────

    def save_last_devices(self, input_device, output_device):
        """Persiste los IDs de los últimos dispositivos usados."""
        _last_dev_file = DATA_DIR / "last_devices.json"
        try:
            with open(_last_dev_file, 'w') as f:
                json.dump({'input': input_device, 'output': output_device}, f)
        except Exception:
            pass

    def load_last_devices(self) -> dict:
        """Carga los últimos dispositivos guardados. Devuelve {} si no hay."""
        _last_dev_file = DATA_DIR / "last_devices.json"
        try:
            if _last_dev_file.exists():
                with open(_last_dev_file, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    # ─── Muestras y entrenamiento ─────────────────────────────────────────────

    def add_training_sample(self, features, label):
        """Agrega una muestra de entrenamiento.

        Guarda en disco máximo una vez cada _SAVE_INTERVAL segundos para no
        reescribir el JSON completo con cada muestra.
        Reentrena el modelo en un hilo daemon para no bloquear la UI.
        """
        self.training_samples.append({
            "features":  features.tolist(),
            "label":     label,
            "timestamp": time.time()
        })

        now = time.monotonic()
        if now - getattr(self, '_last_save_time', 0.0) >= _SAVE_INTERVAL:
            self._save_samples()
            self._last_save_time = now

        if len(self.training_samples) >= 10:
            self._train_async()

    def _train_async(self):
        """Lanza train_model() en un hilo daemon para no bloquear la UI o la API.
        Solo arranca un hilo si no hay otro en curso.
        """
        if getattr(self, '_training_thread', None) and self._training_thread.is_alive():
            return   # entrenamiento ya en curso — la nueva muestra se incluirá al terminar
        self._training_thread = threading.Thread(
            target=self.train_model, daemon=True, name='AudioEngine-train')
        self._training_thread.start()

    def train_model(self):
        """Entrena el clasificador con las muestras acumuladas.
        Hilo-seguro: hace una snapshot local de training_samples antes de fit().
        """
        samples = list(self.training_samples)   # snapshot — no bloquea el callback
        if len(samples) < 6:
            return False

        X = np.array([s["features"] for s in samples])
        y = np.array([s["label"]    for s in samples])

        if len(np.unique(y)) < 2:
            return False

        try:
            from sklearn.preprocessing import StandardScaler
            scaler = StandardScaler()
            scaler.fit(X)
            X_scaled = scaler.transform(X)

            model = GradientBoostingClassifier(
                n_estimators=200,
                learning_rate=0.08,
                max_depth=4,
                subsample=0.8,
                min_samples_leaf=3,
                random_state=42,
            )
            model.fit(X_scaled, y)

            # Precisión por clase (indicativa — mismos datos de train)
            try:
                from sklearn.metrics import classification_report
                y_pred = model.predict(X_scaled)
                report = classification_report(y, y_pred, output_dict=True, zero_division=0)
            except Exception:
                report = {}

            # Publicar resultado atómicamente — una sola asignación referencia bajo el GIL
            self.scaler          = scaler
            self.model           = model
            self.model_trained   = True
            self._accuracy_report = report
            # Cachear mean/scale como arrays contiguos para transform manual en predict()
            # Evita el overhead de validación de StandardScaler (~15-25µs por llamada)
            self._scaler_mean  = scaler.mean_.astype(np.float32)
            self._scaler_scale = scaler.scale_.astype(np.float32)
            self._save_model()
            self._save_samples()           # flush final garantizado tras entrenar
            self._last_save_time = time.monotonic()

            if self.on_status_update:
                self.on_status_update(f"✅ Modelo entrenado con {len(samples)} muestras")
            return True
        except Exception as e:
            if self.on_status_update:
                self.on_status_update(f"❌ Error entrenando: {e}")
            return False

    def predict(self, features):
        """Predice la clase del sonido con el modelo entrenado.
        Usa transform manual (resta mean / divide scale) en vez de
        StandardScaler.transform() para evitar el overhead de validación
        de sklearn en cada predicción (llamada cada ~1s desde el hilo ML).
        """
        if not self.model_trained or self.model is None:
            return "unknown", 0.0

        try:
            mean  = getattr(self, '_scaler_mean',  None)
            scale = getattr(self, '_scaler_scale', None)
            if mean is None or scale is None:
                # Fallback: scaler todavía no cacheado (carga desde disco)
                X_scaled = self.scaler.transform(features.reshape(1, -1))
            else:
                X_scaled = ((features - mean) / scale).reshape(1, -1)
            pred  = self.model.predict(X_scaled)[0]
            proba = self.model.predict_proba(X_scaled)[0]
            return pred, float(np.max(proba))
        except Exception:
            return "unknown", 0.0

    # ─── Modo de entrenamiento y estadísticas ─────────────────────────────────

    def set_training_mode(self, active, label=None):
        self.training_mode  = active
        self.training_label = label

    def get_sample_count(self):
        labels = ['mine_feet', 'mine_guns', 'enemy_feet', 'enemy_guns', 'airstrike', 'mine', 'enemy']
        counts = {lbl: sum(1 for s in self.training_samples if s['label'] == lbl)
                  for lbl in labels}
        # backward compat: 'mine' y 'enemy' viejos se suman a feet
        counts['mine_feet']  += counts.pop('mine', 0)
        counts['enemy_feet'] += counts.pop('enemy', 0)
        mine  = counts['mine_feet']  + counts['mine_guns']
        enemy = counts['enemy_feet'] + counts['enemy_guns']
        return mine, enemy, counts

    def get_samples_json(self) -> str:
        """Exporta las muestras locales como JSON string para compartir."""
        return json.dumps(self.training_samples, ensure_ascii=False)

    def merge_community_samples(self, community_json: str) -> int:
        """
        Fusiona muestras comunitarias con las locales.
        Evita duplicados por timestamp+label. Devuelve el nº de muestras nuevas añadidas.
        """
        try:
            new_samples = json.loads(community_json)
        except Exception:
            return 0

        existing_keys = {
            (s.get('label', ''), round(s.get('timestamp', 0), 2))
            for s in self.training_samples
        }
        added = 0
        for s in new_samples:
            key = (s.get('label', ''), round(s.get('timestamp', 0), 2))
            if key not in existing_keys:
                self.training_samples.append(s)
                existing_keys.add(key)
                added += 1

        if added > 0:
            self._save_samples()
        return added

    def clear_samples(self):
        self.training_samples = []
        self.model            = None
        self.model_trained    = False
        self._save_samples()
        if MODEL_FILE.exists():
            MODEL_FILE.unlink()

    # ─── Persistencia ─────────────────────────────────────────────────────────

    def _save_model(self):
        with open(MODEL_FILE, 'wb') as f:
            pickle.dump(self.model, f)
        with open(SCALER_FILE, 'wb') as f:
            pickle.dump(self.scaler, f)
        # Guardar metadatos: tamaño de ventana usado en entrenamiento.
        # Si cambia PRED_WINDOW_BLOCKS, el modelo anterior es inválido.
        try:
            with open(_MODEL_META, 'w') as f:
                json.dump({'pred_window_blocks': PRED_WINDOW_BLOCKS}, f)
        except Exception:
            pass

    def _load_model(self):
        try:
            if MODEL_FILE.exists() and SCALER_FILE.exists():
                # Verificar compatibilidad: si el modelo se entrenó con otra ventana,
                # los features tienen distribución diferente → predicciones basura.
                if _MODEL_META.exists():
                    with open(_MODEL_META, 'r') as f:
                        meta = json.load(f)
                    if meta.get('pred_window_blocks') != PRED_WINDOW_BLOCKS:
                        self._invalidate_old_model(
                            meta.get('pred_window_blocks'), PRED_WINDOW_BLOCKS)
                        return
                else:
                    # No hay meta → modelo de versión anterior. Invalidar.
                    self._invalidate_old_model(None, PRED_WINDOW_BLOCKS)
                    return

                with open(MODEL_FILE, 'rb') as f:
                    self.model = pickle.load(f)
                with open(SCALER_FILE, 'rb') as f:
                    self.scaler = pickle.load(f)
                self.model_trained = True
                # Reconstruir caché de normalización para predict() rápido
                if hasattr(self.scaler, 'mean_') and hasattr(self.scaler, 'scale_'):
                    self._scaler_mean  = self.scaler.mean_.astype(np.float32)
                    self._scaler_scale = self.scaler.scale_.astype(np.float32)
        except Exception:
            pass

    def _invalidate_old_model(self, old_window, new_window):
        """Borra modelo y muestras entrenados con ventana incompatible."""
        for f in (MODEL_FILE, SCALER_FILE, _MODEL_META):
            try:
                if f.exists():
                    f.unlink()
            except Exception:
                pass
        # Las muestras también son inválidas: sus features fueron extraídos
        # de audio de tamaño diferente → distribución incompatible.
        self.training_samples = []
        self._save_samples()
        self.model         = None
        self.model_trained = False
        if getattr(self, 'on_status_update', None):
            old_ms = int(old_window * 1024 / 48000 * 1000) if old_window else '?'
            new_ms = int(new_window * 1024 / 48000 * 1000)
            self.on_status_update(
                f'⚠️ Modelo anterior incompatible (ventana {old_ms}ms → {new_ms}ms). '
                f'Muestras borradas. Recoge nuevas muestras para entrenar.')

    def _save_samples(self):
        with open(SAMPLES_FILE, 'w') as f:
            json.dump(self.training_samples, f)

    def _load_samples(self):
        try:
            if SAMPLES_FILE.exists():
                with open(SAMPLES_FILE, 'r') as f:
                    raw = json.load(f)
                # Descartar muestras con vector de features incompatible (formato anterior)
                self.training_samples = [
                    s for s in raw if len(s.get('features', [])) == FEATURE_DIM
                ]
                discarded = len(raw) - len(self.training_samples)
                if discarded > 0 and getattr(self, 'on_status_update', None):
                    self.on_status_update(
                        f"⚠️ {discarded} muestras antiguas descartadas (features v1 → v2 — recoge nuevas muestras)"
                    )
        except Exception:
            self.training_samples = []
