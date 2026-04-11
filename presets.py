"""
Presets de ecualización competitiva para EqualizerAPO.
v3.1 — PK Filters (parametric EQ) + ReaComp brickwall limiter.

Cambio de arquitectura:
  • GraphicEQ per-channel ELIMINADO — causaba canales muertos
  • PK filters en TODOS los canales — pasos se escuchan de todas direcciones
  • Cada slider controla bandas 100% independientes (sin bleed entre zonas)
  • ReaComp limiter brickwall (formato inline probado)
"""

# Parámetros ajustables por el usuario (UI sliders):
#   footstep_db  : Boost en zona de pasos (400–1200 Hz), dB
#   gun_db       : Cut en zona de disparos (2500–5000 Hz), dB
#   streak_db    : Cut progresivo sub-300 Hz, dB
#   lfe_cut_hz   : Frecuencia de corte del HPF, Hz
#   ceiling_db   : Headroom / limiter threshold, dB
#   clarity_db   : Presencia en agudos (>6 kHz), dB
#   compression  : Intensidad del limiter (0=off, 100=brickwall 20:1)

PRESETS = {
    "warzone": {
        "name": "Warzone",
        "icon": "🎯",
        "description": "Pasos OP · gun tamer · brickwall limiter",
        "params": {
            "footstep_db":  14.0,
            "gun_db":      -10.0,
            "streak_db":   -15.0,
            "lfe_cut_hz":     80,
            "ceiling_db":   -1.0,
            "clarity_db":    3.0,
            "compression": 70.0,
        },
    },
    "fortnite": {
        "name": "Fortnite",
        "icon": "🏗",
        "description": "Pasos + construcciones · explosiones cortadas",
        "params": {
            "footstep_db":  12.0,
            "gun_db":       -6.0,
            "streak_db":   -10.0,
            "lfe_cut_hz":     60,
            "ceiling_db":   -1.0,
            "clarity_db":    4.0,
            "compression": 60.0,
        },
    },
    "apex": {
        "name": "Apex Legends",
        "icon": "🎮",
        "description": "Pasos + habilidades · agudos +5 dB",
        "params": {
            "footstep_db":  10.0,
            "gun_db":        -5.0,
            "streak_db":    -8.0,
            "lfe_cut_hz":     70,
            "ceiling_db":   -1.0,
            "clarity_db":     5.0,
            "compression": 50.0,
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
            "compression":   0.0,
        },
    },
}

# Rango de cada slider para la UI
PARAM_RANGES = {
    "footstep_db":  {"min": -6,  "max": 20, "step": 0.5, "unit": "dB",
                     "label": "Footstep",     "desc": "400–1200 Hz boost"},
    "gun_db":       {"min": -18, "max": 6,  "step": 0.5, "unit": "dB",
                     "label": "Gun Cut",      "desc": "2.5–5 kHz cut"},
    "streak_db":    {"min": -20, "max": 0,  "step": 0.5, "unit": "dB",
                     "label": "Streak",       "desc": "<300 Hz cut"},
    "lfe_cut_hz":   {"min": 20,  "max": 150, "step": 5, "unit": "Hz",
                     "label": "LFE Cut",      "desc": "Sub-graves · Rumble"},
    "ceiling_db":   {"min": -12, "max": 0,  "step": 0.5, "unit": "dB",
                     "label": "Ceiling",      "desc": "Limiter threshold"},
    "clarity_db":   {"min": -6,  "max": 10, "step": 0.5, "unit": "dB",
                     "label": "Clarity",      "desc": ">6 kHz presencia"},
    "compression":  {"min": 0,   "max": 100, "step": 5, "unit": "%",
                     "label": "Compression",  "desc": "Limiter intensity"},
}


# ── REAPLUGS PATH ────────────────────────────────────────────────────────────

_REACOMP_DLL = r"C:\Program Files\VSTPlugins\ReaPlugs\reacomp-standalone.dll"


def _build_reacomp_inline(thresh_db: float, ratio: float,
                          attack_ms: float = 1.0, release_ms: float = 20.0,
                          lookahead_ms: float = 2.0) -> str:
    """Genera parámetros inline para ReaComp (limiter)."""
    thresh_lin = 10 ** (thresh_db / 20.0)
    ratio_param = 1.0 - 1.0 / max(ratio, 1.001)
    attack_s = attack_ms / 1000.0
    release_s = release_ms / 1000.0
    precomp = lookahead_ms / 1000.0

    return (f'Thresh {thresh_lin:.8f} Ratio {ratio_param:.7f} '
            f'Attack {attack_s:.6f} Release {release_s:.4f} '
            f'Pre-comp {precomp:.4f} resvd 0 Lowpass 1 Hipass 0 '
            f'SignIn 0 AudIn 0 Dry 3.1622776E-08 Wet 1 '
            f'PreviewF 0 "RMS size" 0 Knee 0 AutoMkUp 0 '
            f'AutoRel 0 ClsAttk 0 AntiAls 0.07692308')


def find_reaplugs_path() -> str | None:
    """Busca la carpeta de ReaPlugs en el sistema."""
    import os
    from pathlib import Path
    candidates = [
        Path(r"C:\Program Files\VSTPlugins\ReaPlugs"),
        Path(r"C:\Program Files (x86)\VSTPlugins\ReaPlugs"),
        Path(r"C:\Program Files\VSTPlugins"),
        Path(r"C:\Program Files (x86)\VSTPlugins"),
    ]
    for d in candidates:
        dll = d / "reacomp-standalone.dll"
        if dll.exists():
            return str(dll)
        if d.is_dir():
            for sub in d.iterdir():
                if sub.is_dir():
                    dll = sub / "reacomp-standalone.dll"
                    if dll.exists():
                        return str(dll)
    return None


# ── CONFIG GENERATOR ─────────────────────────────────────────────────────────

def params_to_apo_config(params: dict, preset_name: str = "Custom") -> str:
    """Genera configuración EqualizerAPO v3.1 con PK filters.

    Arquitectura simple y probada:
      1. Preamp (compensar boost)
      2. HPF sub-grave
      3. PK filters: streak cut, footstep boost, gun cut, clarity
      4. ReaComp brickwall limiter
    """
    foot = params.get("footstep_db", 0.0)
    gun = params.get("gun_db", 0.0)
    streak = params.get("streak_db", 0.0)
    clarity = params.get("clarity_db", 0.0)
    ceiling = params.get("ceiling_db", -1.0)
    lfe = params.get("lfe_cut_hz", 80)
    comp_pct = params.get("compression", 70.0)

    # ── Preamp: compensar boost para evitar clipping ─────────────────────
    max_boost = max(abs(foot), abs(clarity), 0.0)
    preamp = ceiling - max_boost * 0.4
    preamp = min(preamp, 0.0)

    lines = [
        f"# WarzoneAudioEnhancer v3.1 — {preset_name}",
        "# PK Filters · ReaComp Limiter",
        "",
    ]

    if preamp != 0.0:
        lines.append(f"Preamp: {preamp:.1f} dB")
        lines.append("")

    # ── HPF: rumble cut ──────────────────────────────────────────────────
    if lfe > 20:
        lines.append(f"# ── Rumble cut ──")
        lines.append(f"Filter: ON HP Fc {lfe} Hz Q 0.707")
        lines.append("")

    # ── STREAK CUT (<300 Hz) ─────────────────────────────────────────────
    if streak != 0.0:
        lines.append(f"# ── Streak cut (<300 Hz) ──")
        lines.append(f"Filter: ON PK Fc 35 Hz Gain {streak * 1.5 + 0.0:.1f} dB Q 0.4")
        lines.append(f"Filter: ON PK Fc 80 Hz Gain {streak * 1.0 + 0.0:.1f} dB Q 0.5")
        lines.append(f"Filter: ON PK Fc 200 Hz Gain {streak * 0.4 + 0.0:.1f} dB Q 0.7")
        lines.append("")

    # ── FOOTSTEP BOOST (400–1200 Hz) ─────────────────────────────────────
    if foot != 0.0:
        lines.append(f"# ── Footstep boost (400–1200 Hz) ──")
        lines.append(f"Filter: ON PK Fc 450 Hz Gain {foot * 0.5 + 0.0:.1f} dB Q 1.2")
        lines.append(f"Filter: ON PK Fc 650 Hz Gain {foot * 1.0 + 0.0:.1f} dB Q 1.4")
        lines.append(f"Filter: ON PK Fc 900 Hz Gain {foot * 0.8 + 0.0:.1f} dB Q 1.3")
        lines.append(f"Filter: ON PK Fc 1100 Hz Gain {foot * 0.3 + 0.0:.1f} dB Q 1.5")
        lines.append("")

    # ── GUN CUT (2.5–5 kHz) ──────────────────────────────────────────────
    if gun != 0.0:
        lines.append(f"# ── Gun cut (2.5–5 kHz) ──")
        lines.append(f"Filter: ON PK Fc 2800 Hz Gain {gun * 0.6 + 0.0:.1f} dB Q 2.5")
        lines.append(f"Filter: ON PK Fc 3500 Hz Gain {gun * 1.0 + 0.0:.1f} dB Q 2.0")
        lines.append(f"Filter: ON PK Fc 4200 Hz Gain {gun * 0.7 + 0.0:.1f} dB Q 2.5")
        lines.append("")

    # ── CLARITY (>6 kHz) ─────────────────────────────────────────────────
    if clarity != 0.0:
        lines.append(f"# ── Clarity (>6 kHz) ──")
        lines.append(f"Filter: ON PK Fc 6500 Hz Gain {clarity * 0.5 + 0.0:.1f} dB Q 1.0")
        lines.append(f"Filter: ON PK Fc 9000 Hz Gain {clarity * 1.0 + 0.0:.1f} dB Q 0.8")
        lines.append(f"Filter: ON PK Fc 12000 Hz Gain {clarity * 0.5 + 0.0:.1f} dB Q 0.7")
        lines.append("")

    # ── BRICKWALL LIMITER ────────────────────────────────────────────────
    if comp_pct > 0:
        # Scale ratio by compression %: 0%=off, 50%=4:1, 100%=20:1
        ratio = 2.0 + 18.0 * (comp_pct / 100.0)
        lines.append(f"# ── Limiter (ratio {ratio:.0f}:1) ──")
        limiter_params = _build_reacomp_inline(
            thresh_db=ceiling,
            ratio=ratio,
            attack_ms=0.5,
            release_ms=15.0,
            lookahead_ms=2.0,
        )
        lines.append(
            f'VSTPlugin: Library "{_REACOMP_DLL}" {limiter_params}'
        )
        lines.append("")

    return "\n".join(lines)
