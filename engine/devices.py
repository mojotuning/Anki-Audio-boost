"""
Detección de dispositivos de audio y software virtual instalado.
"""
import os
import sys

import sounddevice as sd


def list_audio_devices():
    """
    Devuelve dispositivos WASAPI sin deduplicar por nombre.
    WASAPI ya garantiza un endpoint por dispositivo físico/virtual.
    Deduplicar por nombre causaba perder cables virtuales cuyo nombre
    de captura y de render son iguales.
    """
    devices   = sd.query_devices()
    host_apis = sd.query_hostapis()

    wasapi_idx = next(
        (i for i, a in enumerate(host_apis) if 'wasapi' in a['name'].lower()), None
    )

    result = []
    for i, d in enumerate(devices):
        if wasapi_idx is not None and d['hostapi'] != wasapi_idx:
            continue
        if d['max_input_channels'] == 0 and d['max_output_channels'] == 0:
            continue
        result.append({
            'id':         i,
            'name':       d['name'],
            'inputs':     d['max_input_channels'],
            'outputs':    d['max_output_channels'],
            'default_sr': int(d['default_samplerate']),
        })

    return result


def detect_audio_software() -> dict:
    """
    Detecta software de audio virtual instalado (VB-Cable, Voicemeter, EQ APO).
    Solo LEE el estado del sistema. NO modifica ninguna configuración existente.
    """
    result = {
        "vb_cable":              False,
        "voicemeeter":           False,
        "eq_apo":                False,
        "suggested_input":       None,
        "suggested_input_name":  None,
        "detected":              [],
    }

    # ── Escanear dispositivos de audio ─────────────────────────────────────
    try:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            name_lower = d['name'].lower()

            # VB-Cable
            if 'cable' in name_lower and not result["vb_cable"]:
                if d['max_input_channels'] > 0 or d['max_output_channels'] > 0:
                    result["vb_cable"] = True
                    result["detected"].append(f"VB-Cable  ({d['name']})")
                    if d['max_input_channels'] > 0 and result["suggested_input"] is None:
                        result["suggested_input"]      = i
                        result["suggested_input_name"] = d['name']

            # Voicemeter (cualquier variante: Banana, Potato, etc.)
            if 'voicemeeter' in name_lower:
                if not result["voicemeeter"]:
                    result["voicemeeter"] = True
                    result["detected"].append(f"Voicemeter  ({d['name']})")
                if ('output' in name_lower or 'vaio' in name_lower) and d['max_input_channels'] > 0:
                    if result["suggested_input"] is None:
                        result["suggested_input"]      = i
                        result["suggested_input_name"] = d['name']
    except Exception:
        pass

    # ── Detectar EQ APO (sólo lectura de registro/directorio) ──────────────
    if sys.platform == 'win32':
        try:
            import winreg
            winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EqualizerAPO")
            result["eq_apo"] = True
            result["detected"].append("Equalizer APO")
        except Exception:
            pass

        if not result["eq_apo"]:
            for eq_path in [
                r"C:\Program Files\EqualizerAPO",
                r"C:\Program Files (x86)\EqualizerAPO",
            ]:
                if os.path.isdir(eq_path):
                    result["eq_apo"] = True
                    result["detected"].append("Equalizer APO")
                    break

    return result
