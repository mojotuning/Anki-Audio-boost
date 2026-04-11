"""
Presets de ecualización competitiva para EqualizerAPO.
Cada preset define parámetros que se convierten en una curva GraphicEQ
con ~30 puntos de control — sin solapamiento, sin huecos, sin piedad.
"""

# Parámetros ajustables por el usuario (UI sliders):
#   footstep_db  : Boost en meseta de pasos (400–1500 Hz), dB
#   gun_db       : Cut en rango de disparos (3000–4500 Hz), dB
#   streak_db    : Cut progresivo sub-500 Hz (streaks/explosiones), dB
#   lfe_cut_hz   : Frecuencia de corte del HPF sub-grave, Hz
#   ceiling_db   : Headroom / anti-clip, dB
#   clarity_db   : Presencia en agudos (>6 kHz), dB

PRESETS = {
    "warzone": {
        "name": "Warzone",
        "icon": "🎯",
        "description": "Pasos +15 dB, streaks -15 dB, disparos -10 dB",
        "params": {
            "footstep_db":  15.0,
            "gun_db":      -10.0,
            "streak_db":   -15.0,
            "lfe_cut_hz":     80,
            "ceiling_db":   -1.0,
            "clarity_db":    3.0,
        },
    },
    "fortnite": {
        "name": "Fortnite",
        "icon": "🏗",
        "description": "Pasos +12 dB, construcciones claras, explosiones -10 dB",
        "params": {
            "footstep_db":  12.0,
            "gun_db":       -6.0,
            "streak_db":   -10.0,
            "lfe_cut_hz":     60,
            "ceiling_db":   -1.0,
            "clarity_db":    4.0,
        },
    },
    "apex": {
        "name": "Apex Legends",
        "icon": "🎮",
        "description": "Pasos +10 dB, habilidades -8 dB, agudos +5 dB",
        "params": {
            "footstep_db":  10.0,
            "gun_db":        -5.0,
            "streak_db":    -8.0,
            "lfe_cut_hz":     70,
            "ceiling_db":   -1.0,
            "clarity_db":     5.0,
        },
    },
    "flat": {
        "name": "Flat",
        "icon": "📊",
        "description": "Sin procesamiento — bypass",
        "params": {
            "footstep_db":   0.0,
            "gun_db":        0.0,
            "streak_db":     0.0,
            "lfe_cut_hz":     20,
            "ceiling_db":    0.0,
            "clarity_db":     0.0,
        },
    },
}

# Rango de cada slider para la UI
PARAM_RANGES = {
    "footstep_db": {"min": -6,  "max": 20, "step": 0.5, "unit": "dB",
                    "label": "Footstep",  "desc": "400–1500 Hz · Pasos"},
    "gun_db":      {"min": -18, "max": 6,  "step": 0.5, "unit": "dB",
                    "label": "Own Gun",   "desc": "3–4.5 kHz · Tus disparos"},
    "streak_db":   {"min": -20, "max": 0,  "step": 0.5, "unit": "dB",
                    "label": "Streak",    "desc": "<500 Hz · Explosiones/Streaks"},
    "lfe_cut_hz":  {"min": 20,  "max": 150, "step": 5, "unit": "Hz",
                    "label": "LFE Cut",   "desc": "Sub-graves · Rumble"},
    "ceiling_db":  {"min": -12, "max": 0,  "step": 0.5, "unit": "dB",
                    "label": "Ceiling",   "desc": "Headroom · Anti-clip"},
    "clarity_db":  {"min": -6,  "max": 10, "step": 0.5, "unit": "dB",
                    "label": "Clarity",   "desc": ">6 kHz · Presencia"},
}


def params_to_apo_config(params: dict, preset_name: str = "Custom") -> str:
    """Genera configuración EqualizerAPO usando GraphicEQ de ~30 puntos.

    En lugar de filtros paramétricos (PK) que se solapan y crean huecos,
    GraphicEQ define la ganancia EXACTA en cada frecuencia.  APO interpola
    linealmente en escala logarítmica entre los puntos → curva continua,
    sin conflictos, sin gaps.
    """
    foot = params.get("footstep_db", 0.0)
    gun = params.get("gun_db", 0.0)
    streak = params.get("streak_db", 0.0)
    clarity = params.get("clarity_db", 0.0)
    ceiling = params.get("ceiling_db", 0.0)
    lfe = params.get("lfe_cut_hz", 80)

    # ── Construir curva de 30 puntos ──────────────────────────────────────
    # Cada tupla es (frecuencia_Hz, ganancia_dB).
    # La curva tiene 5 zonas: sub-kill → footstep ramp → meseta → gun valley → clarity rise
    points = [
        # ── Sub-bass: DESTRUIR (streak amplificado) ──
        (20,    streak * 1.5),
        (40,    streak * 1.4),
        (60,    streak * 1.2),
        (80,    streak * 1.0),
        (120,   streak * 0.8),
        (180,   streak * 0.5),
        (250,   streak * 0.2),
        # ── Transición a pasos ──
        (300,   foot * 0.30),
        # ── Footstep: MESETA SOSTENIDA ──
        (400,   foot * 0.65),
        (500,   foot * 0.85),
        (600,   foot * 0.95),
        (700,   foot * 1.00),          # meseta empieza
        (800,   foot * 1.00),
        (1000,  foot * 1.00),
        (1200,  foot * 1.00),          # meseta termina
        # ── Bajada suave de pasos ──
        (1500,  foot * 0.80),
        (1800,  foot * 0.55),
        (2000,  foot * 0.40),
        (2200,  foot * 0.25),
        (2500,  foot * 0.10),
        # ── Gun valley: CORTE PROFUNDO ──
        (2800,  gun * 0.50),
        (3000,  gun * 0.85),
        (3500,  gun * 1.00),           # centro del corte
        (4000,  gun * 1.00),
        (4500,  gun * 0.70),
        # ── Transición a clarity ──
        (5000,  gun * 0.25 + clarity * 0.15),
        # ── Clarity / presence ──
        (6000,  clarity * 0.55),
        (8000,  clarity * 0.80),
        (10000, clarity * 1.00),
        (12000, clarity * 0.75),
        (16000, clarity * 0.35),
        (20000, 0.0),
    ]

    # ── Preamp: solo ceiling (la curva ya está balanceada) ────────────────
    # Solo agregamos compensación mínima si el boost es extremo (>14 dB).
    max_gain = max(g for _, g in points)
    preamp = ceiling
    if max_gain > 14.0:
        preamp -= (max_gain - 14.0) * 0.20
    preamp = min(preamp, 0.0)

    # ── Generar config ────────────────────────────────────────────────────
    lines = [
        f"# WarzoneAudioEnhancer v2.1 — {preset_name}",
        "# GraphicEQ — curva quirúrgica de {0} puntos".format(len(points)),
        "",
    ]

    if preamp != 0.0:
        lines.append(f"Preamp: {preamp:.1f} dB")
        lines.append("")

    # HPF solo si LFE > 20 Hz (refuerza el corte de sub que ya hace la curva)
    if lfe > 20:
        lines.append(f"Filter: ON HP Fc {lfe} Hz Q 0.707")
        lines.append("")

    # GraphicEQ — una sola línea con todos los puntos
    eq_parts = []
    for freq, gain in points:
        eq_parts.append(f"{freq} {gain:.1f}")
    lines.append("GraphicEQ: " + "; ".join(eq_parts))
    lines.append("")

    return "\n".join(lines)
