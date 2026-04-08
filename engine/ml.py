"""
Machine learning: entrenamiento, predicción, persistencia y gestión de muestras.
"""
import json
import pickle
import time

import numpy as np
from sklearn.ensemble import RandomForestClassifier

from .config import MODEL_FILE, SCALER_FILE, SAMPLES_FILE, DATA_DIR

_PROFILES_FILE = DATA_DIR / "profiles.json"


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
        stats = self._session_stats
        start = stats.get('start_time')
        duration_s = (_t.time() - start) if start else 0
        blocks = stats.get('blocks_processed', 0)
        confs = stats.get('confidences', [])
        mean_conf = (sum(confs) / len(confs)) if confs else 0.0
        total_active = sum(v for k, v in stats.get('class_counts', {}).items() if k != 'unknown')
        coverage = (total_active / blocks * 100) if blocks > 0 else 0.0
        return {
            'duration_s':        round(duration_s, 1),
            'blocks_processed':  blocks,
            'class_counts':      dict(stats.get('class_counts', {})),
            'mean_confidence':   round(mean_conf * 100, 1),
            'coverage_pct':      round(coverage, 1),
        }

    def label_recent(self, label: str) -> int:
        """
        Etiqueta los últimos ~3 s de audio capturado (ring buffer) como muestras de clase label.
        Devuelve el número de muestras añadidas.
        """
        if not self._audio_ring:
            return 0
        added = 0
        for audio_block in list(self._audio_ring):
            features = self.extract_features(audio_block)
            if features is not None:
                self.add_training_sample(features, label)
                added += 1
        return added

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
        """Agrega una muestra de entrenamiento."""
        self.training_samples.append({
            "features":  features.tolist(),
            "label":     label,
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
        y = np.array([s["label"]    for s in self.training_samples])

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

            # Precisión por clase (sobre los datos de entrenamiento — indicativo)
            try:
                from sklearn.metrics import classification_report
                y_pred = self.model.predict(X_scaled)
                report = classification_report(y, y_pred, output_dict=True, zero_division=0)
                self._accuracy_report = report
            except Exception:
                self._accuracy_report = {}

            self._save_model()

            if self.on_status_update:
                self.on_status_update(f"✅ Modelo entrenado con {len(self.training_samples)} muestras")

            return True
        except Exception as e:
            if self.on_status_update:
                self.on_status_update(f"❌ Error entrenando: {e}")
            return False

    def predict(self, features):
        """Predice la clase del sonido con el modelo entrenado."""
        if not self.model_trained or self.model is None:
            return "unknown", 0.0

        try:
            X        = features.reshape(1, -1)
            X_scaled = self.scaler.transform(X)
            pred     = self.model.predict(X_scaled)[0]
            proba    = self.model.predict_proba(X_scaled)[0]
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
