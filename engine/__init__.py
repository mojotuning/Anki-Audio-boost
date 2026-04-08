"""
Paquete engine — exporta la API pública del motor de audio.
"""
from .core    import AudioEngine
from .devices import list_audio_devices, detect_audio_software

__all__ = ['AudioEngine', 'list_audio_devices', 'detect_audio_software']
