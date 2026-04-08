"""
Extracción de características de audio para el clasificador ML.
"""
import numpy as np
import librosa
import warnings

warnings.filterwarnings('ignore')

from .config import SAMPLE_RATE, FREQ_RANGES


class FeaturesMixin:
    def extract_features(self, audio_chunk):
        """Extrae características del audio para el clasificador ML."""
        try:
            mono = np.mean(audio_chunk, axis=1) if audio_chunk.ndim > 1 else audio_chunk

            if len(mono) < 512:
                return None

            features = []

            # 1. MFCCs (timbre del sonido)
            mfccs = librosa.feature.mfcc(y=mono.astype(np.float32),
                                          sr=SAMPLE_RATE, n_mfcc=13)
            features.extend(np.mean(mfccs, axis=1))
            features.extend(np.std(mfccs, axis=1))

            # 2. Energía por banda de frecuencia
            freqs   = np.fft.rfftfreq(len(mono), 1 / SAMPLE_RATE)
            fft_mag = np.abs(np.fft.rfft(mono))

            for name, (low, high) in FREQ_RANGES.items():
                mask   = (freqs >= low) & (freqs <= high)
                energy = np.sum(fft_mag[mask] ** 2) if mask.any() else 0
                features.append(float(energy))

            # 3. RMS (volumen general)
            rms = np.sqrt(np.mean(mono ** 2))
            features.append(float(rms))

            # 4. Zero crossing rate (textura del sonido)
            zcr = librosa.feature.zero_crossing_rate(mono)
            features.append(float(np.mean(zcr)))

            # 5. Centroide espectral
            centroid = librosa.feature.spectral_centroid(
                y=mono.astype(np.float32), sr=SAMPLE_RATE)
            features.append(float(np.mean(centroid)))

            return np.array(features)

        except Exception:
            return None
