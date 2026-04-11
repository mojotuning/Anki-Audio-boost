"""
Presets de ecualización competitiva para EqualizerAPO.
Cada preset define parámetros que se convierten en filtros APO.
"""

# Parámetros ajustables por el usuario (UI sliders):
#   footstep_db  : Boost/cut en rango de pasos (200–2500 Hz), dB
#   gun_db       : Boost/cut en rango de disparos (2000–6000 Hz), dB
#   streak_db    : Low-shelf para streaks/explosiones (<150 Hz), dB
#   lfe_cut_hz   : Frecuencia de corte del HPF sub-grave, Hz
#   ceiling_db   : Preamp (nivel máximo de salida), dB
#   clarity_db   : High-shelf para presencia/detalle (>6000 Hz), dB

PRESETS = {
    "warzone": {
        "name": "Warzone",
        "icon": "🎯",
        "description": "Pasos +12 dB, streaks -12 dB, disparos -6 dB",
        "params": {
            "footstep_db":  12.0,
            "gun_db":       -6.0,
            "streak_db":   -12.0,
            "lfe_cut_hz":     80,
            "ceiling_db":   -8.0,
            "clarity_db":    3.0,
        },
    },
    "fortnite": {
        "name": "Fortnite",
        "icon": "🏗",
        "description": "Pasos +10 dB, construcciones claras, explosiones -8 dB",
        "params": {
            "footstep_db":  10.0,
            "gun_db":       -4.0,
            "streak_db":    -8.0,
            "lfe_cut_hz":     60,
            "ceiling_db":   -6.0,
            "clarity_db":    4.0,
        },
    },
    "apex": {
        "name": "Apex Legends",
        "icon": "🎮",
        "description": "Pasos +8 dB, habilidades -6 dB, agudos +5 dB",
        "params": {
            "footstep_db":   8.0,
            "gun_db":        -3.0,
            "streak_db":     -6.0,
            "lfe_cut_hz":     70,
            "ceiling_db":    -6.0,
            "clarity_db":     5.0,
        },
    },
    "flat": {
        "name": "Flat",
        "icon": "📊",
        "description": "Sin procesamiento — solo LFE cut y ceiling",
        "params": {
            "footstep_db":   0.0,
            "gun_db":        0.0,
            "streak_db":     0.0,
            "lfe_cut_hz":     80,
            "ceiling_db":    -3.0,
            "clarity_db":     0.0,
        },
    },
}

# Rango de cada slider para la UI
PARAM_RANGES = {
    "footstep_db": {"min": -6,  "max": 18, "step": 0.5, "unit": "dB",
                    "label": "Footstep",  "desc": "200–2500 Hz · Pasos"},
    "gun_db":      {"min": -15, "max": 6,  "step": 0.5, "unit": "dB",
                    "label": "Own Gun",   "desc": "2–6 kHz · Tus disparos"},
    "streak_db":   {"min": -18, "max": 0,  "step": 0.5, "unit": "dB",
                    "label": "Streak",    "desc": "<150 Hz · Explosiones"},
    "lfe_cut_hz":  {"min": 20,  "max": 150, "step": 5, "unit": "Hz",
                    "label": "LFE Cut",   "desc": "Sub-graves · Rumble"},
    "ceiling_db":  {"min": -20, "max": 0,  "step": 0.5, "unit": "dB",
                    "label": "Ceiling",   "desc": "Nivel máximo de salida"},
    "clarity_db":  {"min": -6,  "max": 10, "step": 0.5, "unit": "dB",
                    "label": "Clarity",   "desc": ">6 kHz · Presencia"},
}


def params_to_apo_config(params: dict, preset_name: str = "Custom") -> str:
    """Convierte parámetros de preset a texto de configuración de EqualizerAPO."""
    lines = [
        f"# WarzoneAudioEnhancer v2.0 — {preset_name}",
        "# Auto-generated — do not edit manually",
        "",
    ]

    # Preamp / ceiling
    ceiling = params.get("ceiling_db", -6.0)
    lines.append(f"Preamp: {ceiling:.1f} dB")
    lines.append("")

    # 1. HPF — LFE Cut
    lfe = params.get("lfe_cut_hz", 80)
    if lfe > 20:
        lines.append(f"Filter: ON HP Fc {lfe} Hz Q 0.707")
        lines.append(f"# LFE Cut — elimina rumble de explosiones por debajo de {lfe} Hz")
        lines.append("")

    # 2. Streak/Explosion reduction (Low Shelf)
    streak = params.get("streak_db", 0.0)
    if abs(streak) >= 0.5:
        lines.append(f"Filter: ON LS Fc 150 Hz Gain {streak:.1f} dB Q 0.71")
        lines.append(f"# Streak — atenúa killstreaks y explosiones")
        lines.append("")

    # 3. Footstep boost (curva de 3 bandas para cobertura natural)
    foot = params.get("footstep_db", 0.0)
    if abs(foot) >= 0.5:
        lo = foot * 0.50    # 400 Hz: base del paso
        mid = foot           # 1000 Hz: cuerpo principal del paso
        hi = foot * 0.35    # 2500 Hz: detalle/ataque del paso
        lines.append(f"Filter: ON PK Fc 400 Hz Gain {lo:.1f} dB Q 0.80")
        lines.append(f"# Footstep low — base del paso")
        lines.append(f"Filter: ON PK Fc 1000 Hz Gain {mid:.1f} dB Q 0.90")
        lines.append(f"# Footstep mid — cuerpo principal (+{foot:.1f} dB)")
        lines.append(f"Filter: ON PK Fc 2500 Hz Gain {hi:.1f} dB Q 1.20")
        lines.append(f"# Footstep detail — ataque y claridad")
        lines.append("")

    # 4. Gun reduction
    gun = params.get("gun_db", 0.0)
    if abs(gun) >= 0.5:
        lines.append(f"Filter: ON PK Fc 4000 Hz Gain {gun:.1f} dB Q 1.00")
        lines.append(f"# Own Gun — reduce tus propios disparos")
        lines.append("")

    # 5. Clarity / presence
    clarity = params.get("clarity_db", 0.0)
    if abs(clarity) >= 0.5:
        lines.append(f"Filter: ON HS Fc 7000 Hz Gain {clarity:.1f} dB Q 0.71")
        lines.append(f"# Clarity — presencia y detalle en agudos")
        lines.append("")

    return "\n".join(lines)
