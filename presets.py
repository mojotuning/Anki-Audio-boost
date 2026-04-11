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
            "ceiling_db":   -2.0,
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
            "ceiling_db":   -1.0,
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
            "ceiling_db":   -1.0,
            "clarity_db":     5.0,
        },
    },
    "flat": {
        "name": "Flat",
        "icon": "📊",
        "description": "Sin procesamiento — solo LFE cut",
        "params": {
            "footstep_db":   0.0,
            "gun_db":        0.0,
            "streak_db":     0.0,
            "lfe_cut_hz":     80,
            "ceiling_db":    0.0,
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
    "ceiling_db":  {"min": -12, "max": 0,  "step": 0.5, "unit": "dB",
                    "label": "Ceiling",   "desc": "Headroom extra · Anti-clip"},
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

    foot = params.get("footstep_db", 0.0)
    gun = params.get("gun_db", 0.0)
    streak = params.get("streak_db", 0.0)
    clarity = params.get("clarity_db", 0.0)
    ceiling = params.get("ceiling_db", 0.0)

    # ── Preamp ────────────────────────────────────────────────────────────
    # Compensación MÍNIMA: solo 25% del boost máximo.
    # El audio de juegos rara vez está a 0 dBFS (-6 a -12 dBFS típico),
    # así que podemos permitir boosts grandes sin clipping real.
    # El slider "ceiling" da control manual al usuario.
    max_boost = max(foot, clarity, 0.0)
    preamp = -(max_boost * 0.25) + ceiling
    preamp = min(preamp, 0.0)
    lines.append(f"Preamp: {preamp:.1f} dB")
    lines.append("")

    # ── 1. HPF — LFE Cut ─────────────────────────────────────────────────
    lfe = params.get("lfe_cut_hz", 80)
    if lfe > 20:
        lines.append(f"Filter: ON HP Fc {lfe} Hz Q 0.707")
        lines.append("")

    # ── 2. Streak/Explosion cut (Low Shelf <200 Hz) ──────────────────────
    if abs(streak) >= 0.5:
        lines.append(f"Filter: ON LS Fc 200 Hz Gain {streak:.1f} dB Q 0.50")
        lines.append("")

    # ── 3. Footstep boost ─────────────────────────────────────────────────
    # Estrategia: 1 filtro ANCHO (low Q) centrado en 800 Hz que cubre
    # todo el rango de pasos (300–2000 Hz), más un segundo filtro para
    # el "click" de contacto del paso (2000–3000 Hz).
    # Q bajo = ancho de banda grande = los pasos suben EN TODA la banda.
    if abs(foot) >= 0.5:
        # Filtro principal: 800 Hz, Q=0.40 → cubre ~300–2000 Hz
        lines.append(f"Filter: ON PK Fc 800 Hz Gain {foot:.1f} dB Q 0.40")
        # Detalle de paso: 2500 Hz, Q=0.60 → impacto y textura
        hi = foot * 0.40
        lines.append(f"Filter: ON PK Fc 2500 Hz Gain {hi:.1f} dB Q 0.60")
        lines.append("")

    # ── 4. Gun reduction ─────────────────────────────────────────────────
    # Filtro ancho centrado en 3500 Hz para cubrir 2–6 kHz (disparos)
    if abs(gun) >= 0.5:
        lines.append(f"Filter: ON PK Fc 3500 Hz Gain {gun:.1f} dB Q 0.50")
        lines.append("")

    # ── 5. Clarity / presence ────────────────────────────────────────────
    if abs(clarity) >= 0.5:
        lines.append(f"Filter: ON HS Fc 6000 Hz Gain {clarity:.1f} dB Q 0.71")
        lines.append("")

    return "\n".join(lines)
