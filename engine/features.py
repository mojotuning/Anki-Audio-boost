"""
Extracción de características de audio para el clasificador ML.
"""
import numpy as np
import librosa
import warnings

warnings.filterwarnings('ignore')

from .config import SAMPLE_RATE, FREQ_RANGES, FEATURE_DIM


class FeaturesMixin:
    def extract_features(self, audio_chunk):
        """
        Extrae un vector de características de FEATURE_DIM=46 dimensiones.

        Requiere audio de al menos ~500 ms para obtener features de calidad.
        Vector resultante:
          13 MFCC mean + 13 MFCC std + 13 delta-MFCC mean
          + 4 energías de banda + RMS + ZCR + centroide espectral = 46
        """
        try:
            mono = np.mean(audio_chunk, axis=1) if audio_chunk.ndim > 1 else audio_chunk
            mono = mono.astype(np.float32)

            if len(mono) < 512:
                return None

            # 1. MFCCs + delta (velocidad temporal del timbre)
            mfccs = librosa.feature.mfcc(y=mono, sr=SAMPLE_RATE, n_mfcc=13)
            delta = librosa.feature.delta(mfccs)        # variación frame a frame

            mfcc_mean  = np.mean(mfccs, axis=1)         # 13
            mfcc_std   = np.std(mfccs,  axis=1)         # 13
            delta_mean = np.mean(delta, axis=1)          # 13

            # 2. Energía por banda de frecuencia (FFT sobre audio completo)
            freqs   = np.fft.rfftfreq(len(mono), 1.0 / SAMPLE_RATE)
            fft_mag = np.abs(np.fft.rfft(mono))
            band_e  = np.array([
                float(np.sum(fft_mag[(freqs >= lo) & (freqs <= hi)] ** 2))
                for _, (lo, hi) in FREQ_RANGES.items()
            ])                                           # 4

            # 3. Descriptores globales
            rms      = np.array([float(np.sqrt(np.mean(mono ** 2)))])          # 1
            zcr      = np.array([float(np.mean(librosa.feature.zero_crossing_rate(mono)))])  # 1
            centroid = np.array([float(np.mean(
                librosa.feature.spectral_centroid(y=mono, sr=SAMPLE_RATE)))])  # 1

            features = np.concatenate([mfcc_mean, mfcc_std, delta_mean,
                                        band_e, rms, zcr, centroid])
            assert len(features) == FEATURE_DIM, f"feature dim={len(features)}"
            return features.astype(np.float32)

        except Exception:
            return None
