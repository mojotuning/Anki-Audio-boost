"""
Presets de ecualizacion competitiva para EqualizerAPO.
v3.3 — ReaXcomp multibanda (ChunkData exactos de ArtTuneDB) + sliders encima.

REQUIERE: Hi-Fi Cable 7.1 -> EqualizerAPO -> HeSuVi -> Audifonos

Por que NO funcionan los PK filters solos:
  Un filtro estatico no puede separar pasos de disparos en la misma senal.
  La unica solucion es compresion DINAMICA por canal (ReaXcomp multibanda):

  Channel: L R        => Gun Tamer   (comprime transientes de disparo)
  Channel: SL SR RL RR => Footstep Compressor (upward compression = sube pasos)

  Los ChunkData son los presets exactos de ArtTuneDB/BO7_S3,
  identicos en competitive, clean y streamer.
  Los sliders de la app añaden boost/cut fino ENCIMA de los compresores.
"""

# ChunkData exactos extraidos de attachments/BO7_S3_pre.txt

# Channel: L R — comprime transientes de disparo (Gun Tamer)
_GUN_TAMER_CHUNK = "OAAAAAQAAAAAAAAAAABpQMAKYekaBPM/fDqgTtwwoD8OAAAAAAAAQAAAAAAAABhACgAAAJYAAAAKAAAAEAAAAAAAAAAAQJ9AACb8+I4k9D926pD/EWKkPwAAAAAAAARAAAAAAAAAGEAFAAAAZAAAAAoAAAAQAAAAAAAAAABwt0BAxGufyfPxP/w6oE7cMKA/AAAAAAAAAEAAAAAAAAAYQAMAAABQAAAACgAAABAAAAAAAAAAAHDXQAAAAAAAAPA/iDeFSympqT8HAAAAAAD4PwAAAAAAABhABQAAAGQAAAAKAAAAEAAAAAEAAAABAAAAAAAAAAAA8D8AAAAA"

# Channel: SL SR RL RR — upward compression para pasos suaves (Footstep Comp)
_FOOTSTEP_COMP_CHUNK = "OAAAAAQAAAAAAAAAAABpQAAAAAAAAPA/9YSWLT8dwD8AAAAAAAD4PwAAAAAAACBACgAAAJYAAAAPAAAAEAAAAAAAAAAAQJ9AAG7o98CZ9j+por0VZciJP8DMzMzMzPw/AAAAAAAAJEAIAAAAeAAAABQAAAAQAAAAAAAAAABwt0AAAAAAAADwP2cBPE+RRIA/BQAAAAAA+D8AAAAAAAAkQAUAAABkAAAAFAAAABAAAAAAAAAAAHDXQAAAAAAAAPA/AKr4wwonsD8AAAAAAAD4PwAAAAAAABBABQAAAJYAAAAPAAAAEAAAAAEAAAABAAAAAAAAAAAA8D8AAAAA"

_REAXCOMP_DLL = r"C:\Program Files\VSTPlugins\ReaPlugs\reaxcomp-standalone.dll"
_REACOMP_DLL  = r"C:\Program Files\VSTPlugins\ReaPlugs\reacomp-standalone.dll"


def _find_reaxcomp_path() -> str:
    from pathlib import Path
    for p in [
        Path(r"C:\Program Files\VSTPlugins\ReaPlugs\reaxcomp-standalone.dll"),
        Path(r"C:\Program Files (x86)\VSTPlugins\ReaPlugs\reaxcomp-standalone.dll"),
    ]:
        if p.exists():
            return str(p)
    return _REAXCOMP_DLL


def find_reaplugs_path() -> str:
    from pathlib import Path
    for p in [
        Path(r"C:\Program Files\VSTPlugins\ReaPlugs\reacomp-standalone.dll"),
        Path(r"C:\Program Files (x86)\VSTPlugins\ReaPlugs\reacomp-standalone.dll"),
    ]:
        if p.exists():
            return str(p)
    return _REACOMP_DLL


PRESETS = {
    "warzone": {
        "name": "Warzone",
        "icon": "🎯",
        "description": "Pasos OP · gun tamer · brickwall limiter",
        "params": {
            "footstep_db":  6.0,
            "gun_db":      -8.0,
            "streak_db":  -12.0,
            "lfe_cut_hz":    80,
            "ceiling_db":  -1.0,
            "clarity_db":   2.0,
            "compression": 70.0,
        },
    },
    "fortnite": {
        "name": "Fortnite",
        "icon": "🏗",
        "description": "Pasos + construcciones · explosiones cortadas",
        "params": {
            "footstep_db":  4.0,
            "gun_db":      -5.0,
            "streak_db":   -8.0,
            "lfe_cut_hz":    60,
            "ceiling_db":  -1.0,
            "clarity_db":   3.0,
            "compression": 60.0,
        },
    },
    "apex": {
        "name": "Apex Legends",
        "icon": "🎮",
        "description": "Pasos + habilidades · agudos +3 dB",
        "params": {
            "footstep_db":  4.0,
            "gun_db":      -4.0,
            "streak_db":   -6.0,
            "lfe_cut_hz":    70,
            "ceiling_db":  -1.0,
            "clarity_db":   3.0,
            "compression": 50.0,
        },
    },
    "flat": {
        "name": "Flat",
        "icon": "📊",
        "description": "Sin procesamiento — bypass",
        "params": {
            "footstep_db":  0.0,
            "gun_db":       0.0,
            "streak_db":    0.0,
            "lfe_cut_hz":   20,
            "ceiling_db":   0.0,
            "clarity_db":   0.0,
            "compression":  0.0,
        },
    },
}

PARAM_RANGES = {
    "footstep_db":  {"min": -6,  "max": 12,  "step": 0.5, "unit": "dB",
                     "label": "Footstep",   "desc": "Boost extra surround SL/SR/RL/RR"},
    "gun_db":       {"min": -18, "max": 6,   "step": 0.5, "unit": "dB",
                     "label": "Gun Cut",    "desc": "Cut extra arma propia L/R"},
    "streak_db":    {"min": -20, "max": 0,   "step": 0.5, "unit": "dB",
                     "label": "Air Streak", "desc": "Rumble cut <200 Hz (despeja pasos)"},
    "lfe_cut_hz":   {"min": 20,  "max": 150, "step": 5,   "unit": "Hz",
                     "label": "LFE Cut",    "desc": "High-pass sub-graves"},
    "ceiling_db":   {"min": -12, "max": 0,   "step": 0.5, "unit": "dB",
                     "label": "Ceiling",    "desc": "Limiter threshold"},
    "clarity_db":   {"min": -6,  "max": 10,  "step": 0.5, "unit": "dB",
                     "label": "Clarity",    "desc": ">7 kHz presencia"},
    "compression":  {"min": 0,   "max": 100, "step": 5,   "unit": "%",
                     "label": "Compression","desc": "Limiter intensity"},
}


def _build_reacomp_inline(thresh_db: float, ratio: float,
                          attack_ms: float = 0.6, release_ms: float = 10.0) -> str:
    thresh_lin  = 10 ** (thresh_db / 20.0)
    ratio_param = 1.0 - 1.0 / max(ratio, 1.001)
    return (f'Thresh {thresh_lin:.8f} Ratio {ratio_param:.7f} '
            f'Attack {attack_ms / 1000:.4f} Release {release_ms / 1000:.2f} '
            f'Pre-comp 0 resvd 0 Lowpass 1 Hipass 0 '
            f'SignIn 0 AudIn 0 Dry 3.1622776E-08 Wet 1 '
            f'PreviewF 0 "RMS size" 0 Knee 0 AutoMkUp 0 '
            f'AutoRel 0 ClsAttk 0 AntiAls 0.07692308')


def params_to_apo_config(params: dict, preset_name: str = "Custom") -> str:
    """Config EqualizerAPO v3.3 — ReaXcomp por canal + PK sliders.

    Bloque 1: Channel all         -> preamp + HPF + streak rumble cut
    Bloque 2: Channel L R         -> Gun Tamer (ReaXcomp) + gun_db PK extra
    Bloque 3: Channel SL SR RL RR -> Footstep Comp (ReaXcomp) + foot PK extra
    Bloque 4: Channel all         -> clarity + limiter brickwall
    """
    foot     = params.get("footstep_db",  0.0)
    gun      = params.get("gun_db",       0.0)
    streak   = params.get("streak_db",    0.0)
    clarity  = params.get("clarity_db",   0.0)
    ceiling  = params.get("ceiling_db",  -1.0)
    lfe      = params.get("lfe_cut_hz",    80)
    comp_pct = params.get("compression",  70.0)

    max_boost = max(foot, 0.0) + max(clarity, 0.0)
    preamp    = min(ceiling - max_boost * 0.3, 0.0)

    reaxcomp = _find_reaxcomp_path()
    reacomp  = find_reaplugs_path()

    lines = [
        f"# WarzoneAudioEnhancer v3.3 — {preset_name}",
        "# Gun Tamer (L R) + Footstep Comp (SL SR RL RR) — ReaXcomp ChunkData",
        "",
        "Channel: all",
    ]

    if preamp < 0.0:
        lines.append(f"Preamp: {preamp:.1f} dB")
    if lfe > 20:
        lines.append(f"Filter: ON HP Fc {lfe} Hz Q 0.707")
    if streak != 0.0:
        # Igual que ArtTuneDB: LSC en 41 Hz + PK en 80/200 Hz
        lines.append("# Air Streak — rumble cut (quita lo que enmascara pasos)")
        lines.append(f"Filter: ON LSC Fc 41 Hz Gain {max(streak * 0.05, -3.0):.2f} dB Q 0.797")
        lines.append(f"Filter: ON PK Fc 80 Hz Gain {streak:.1f} dB Q 0.8")
        lines.append(f"Filter: ON PK Fc 200 Hz Gain {streak * 0.35:.1f} dB Q 1.2")
    lines.append(f"Filter: ON PK Fc 4500 Hz Gain -2.0 dB Q 1.5")
    lines.append("")

    # Gun Tamer — ReaXcomp en L R (comprime disparo propio)
    lines.append("# Gun Tamer — comprime transientes de disparo en L R")
    lines.append("Channel: L R")
    lines.append(f'VSTPlugin: Library "{reaxcomp}" ChunkData "{_GUN_TAMER_CHUNK}"')
    if gun != 0.0:
        lines.append(f"Filter: ON PK Fc 500 Hz Gain {gun * 0.6:.1f} dB Q 1.2")
        lines.append(f"Filter: ON PK Fc 800 Hz Gain {gun:.1f} dB Q 1.5")
    lines.append("")

    # Footstep Compressor — ReaXcomp en SL SR RL RR (sube pasos de enemigos)
    lines.append("# Footstep Comp — sube pasos suaves de enemigos en surround")
    lines.append("Channel: SL SR RL RR")
    lines.append(f'VSTPlugin: Library "{reaxcomp}" ChunkData "{_FOOTSTEP_COMP_CHUNK}"')
    if foot != 0.0:
        lines.append(f"Filter: ON PK Fc 1500 Hz Gain {foot * 0.4:.1f} dB Q 2.0")
        lines.append(f"Filter: ON PK Fc 2500 Hz Gain {foot * 0.6:.1f} dB Q 2.0")
    lines.append("")

    # Global: clarity + limiter
    lines.append("Channel: all")
    if clarity != 0.0:
        lines.append(f"Filter: ON PK Fc 8000 Hz Gain {clarity:.1f} dB Q 1.0")
    if comp_pct > 0:
        ratio = 2.0 + 18.0 * (comp_pct / 100.0)
        lines.append(f'VSTPlugin: Library "{reacomp}" {_build_reacomp_inline(ceiling, ratio)}')

    return "\n".join(lines)
