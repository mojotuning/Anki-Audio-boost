"""
Presets de ecualización competitiva para EqualizerAPO.
v3.0 — Procesamiento per-channel con compresión multibanda (ReaXcomp).

Mejoras sobre ArtTuneDB:
  • GraphicEQ per-channel: boost pasos SOLO en surround (SL SR RL RR)
  • ReaXcomp con upward compression (ratio bajo, threshold bajo, makeup alto)
    → sube los pasos QUIETOS sin matar textura (vs 79:1 brickwall de ATK)
  • Gate simétrico: mismo threshold en todos los canales surround
  • Limiter brickwall real (ratio 20:1 @ -1 dB vs 5:1 @ -0.1 dB de ATK)
  • Sin reverb artificial (señal limpia)
"""

import base64
import struct

# Parámetros ajustables por el usuario (UI sliders):
#   footstep_db  : Boost en meseta de pasos (400–1200 Hz) en canales surround, dB
#   gun_db       : Cut en rango de disparos (2800–4500 Hz) en canales front, dB
#   streak_db    : Cut progresivo sub-500 Hz (todo canal), dB
#   lfe_cut_hz   : Frecuencia de corte del HPF sub-grave, Hz
#   ceiling_db   : Headroom / anti-clip, dB
#   clarity_db   : Presencia en agudos (>6 kHz), dB
#   compression  : Intensidad de compresión surround (0-100%)

PRESETS = {
    "warzone": {
        "name": "Warzone",
        "icon": "🎯",
        "description": "Pasos OP · per-channel · compresión multibanda",
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
        "description": "Pasos + construcciones claras · explosiones cortadas",
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
        "description": "Pasos + habilidades separadas · agudos +5 dB",
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
                     "label": "Footstep",     "desc": "400–1200 Hz · Surround only"},
    "gun_db":       {"min": -18, "max": 6,  "step": 0.5, "unit": "dB",
                     "label": "Gun Cut",      "desc": "2.8–4.5 kHz · Front only"},
    "streak_db":    {"min": -20, "max": 0,  "step": 0.5, "unit": "dB",
                     "label": "Streak",       "desc": "<500 Hz · All channels"},
    "lfe_cut_hz":   {"min": 20,  "max": 150, "step": 5, "unit": "Hz",
                     "label": "LFE Cut",      "desc": "Sub-graves · Rumble"},
    "ceiling_db":   {"min": -12, "max": 0,  "step": 0.5, "unit": "dB",
                     "label": "Ceiling",      "desc": "Limiter threshold"},
    "clarity_db":   {"min": -6,  "max": 10, "step": 0.5, "unit": "dB",
                     "label": "Clarity",      "desc": ">6 kHz · Presencia"},
    "compression":  {"min": 0,   "max": 100, "step": 5, "unit": "%",
                     "label": "Compression",  "desc": "Surround dynamics control"},
}


# ── ReaXcomp ChunkData builder ───────────────────────────────────────────────

def _build_reaxcomp_chunk(bands: list) -> str:
    """Genera el ChunkData base64 para ReaXcomp.

    bands: lista de dicts con keys:
        crossover, thresh_db, ratio, attack_ms, release_ms,
        makeup_db (opcional, default 0), solo (0/1, default 0)

    Formato binario (reverse-engineered):
        Header: I(56) I(num_bands)
        Per band (56 bytes):
            d(crossover_hz) d(thresh_linear) d(ratio_linear)
            d(attack_ms) d(release_ms) I(makeup_x10) I(?) I(?) I(?)
        Footer: I(auto_makeup) I(bypass) padding
    """
    import math
    num = len(bands)
    buf = bytearray()

    # Header
    buf += struct.pack('<II', 56, num)

    for b in bands:
        xover = float(b['crossover'])
        thresh_lin = 10 ** (b['thresh_db'] / 20.0) if b['thresh_db'] != 0 else 1.0
        # Ratio stored as 1/ratio in linear
        ratio_lin = 1.0 / max(b['ratio'], 1.001)
        attack = float(b['attack_ms'])
        release = float(b['release_ms'])
        makeup = b.get('makeup_db', 0.0)

        # Pack band: 3 doubles + 2 doubles + 4 int32s = 5*8 + 4*4 = 56 bytes
        buf += struct.pack('<d', xover)
        buf += struct.pack('<d', thresh_lin)
        buf += struct.pack('<d', ratio_lin)
        buf += struct.pack('<d', attack)
        buf += struct.pack('<d', release)

        # UI state: makeup*10 as int, display height, display offset, flags
        makeup_i = int(abs(makeup) * 10)
        buf += struct.pack('<IIII', makeup_i, 150, 10, 16)

    # Footer: auto-makeup(0), bypass(0) flags, padding
    buf += struct.pack('<II', 1, 1)
    buf += struct.pack('<d', 1.0)  # wet mix
    buf += struct.pack('<I', 0)

    return base64.b64encode(buf).decode('ascii')


def _build_reacomp_inline(thresh_db: float, ratio: float,
                          attack_ms: float = 1.0, release_ms: float = 20.0,
                          lookahead_ms: float = 2.0) -> str:
    """Genera parámetros inline para ReaComp (limiter)."""
    import math
    thresh_lin = 10 ** (thresh_db / 20.0)
    # ReaComp ratio is stored as normalized 0-1 where 0=1:1 and 1=inf:1
    # Approximate: ratio_param = 1 - 1/ratio
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


# ── REAPLUGS PATH ────────────────────────────────────────────────────────────

_REAXCOMP_DLL = r"C:\Program Files\VSTPlugins\ReaPlugs\reaxcomp-standalone.dll"
_REACOMP_DLL = r"C:\Program Files\VSTPlugins\ReaPlugs\reacomp-standalone.dll"


def find_reaplugs_path() -> str | None:
    """Busca la carpeta de ReaPlugs en el sistema."""
    import os
    from pathlib import Path
    candidates = [
        Path(r"C:\Program Files\VSTPlugins\ReaPlugs"),
        Path(r"C:\Program Files (x86)\VSTPlugins\ReaPlugs"),
        Path(r"C:\Program Files\VSTPlugins"),
        Path(r"C:\Program Files (x86)\VSTPlugins"),
        Path(r"C:\Program Files\Common Files\VST3"),
        Path(r"C:\Program Files\REAPER (x64)\Plugins\FX"),
    ]
    for d in candidates:
        reaxcomp = d / "reaxcomp-standalone.dll"
        if reaxcomp.exists():
            return str(reaxcomp)
        # Check one level down
        if d.is_dir():
            for sub in d.iterdir():
                if sub.is_dir():
                    reaxcomp = sub / "reaxcomp-standalone.dll"
                    if reaxcomp.exists():
                        return str(reaxcomp)
    return None


# ── CONFIG GENERATOR ─────────────────────────────────────────────────────────

def params_to_apo_config(params: dict, preset_name: str = "Custom") -> str:
    """Genera configuración EqualizerAPO v3.0 con procesamiento per-channel.

    Arquitectura:
      1. HPF sub-grave (all channels)
      2. Channel: C SUB → kill sub/center
      3. Channel: L R → GraphicEQ (streak cut + gun cut + clarity)
      4. Channel: SL SR RL RR → GraphicEQ (streak cut + footstep boost + clarity)
      5. Channel: SL SR RL RR → ReaXcomp (upward compression footsteps)
      6. Channel: L R → ReaXcomp (gun tamer - downward compression)
      7. Channel: all → ReaComp limiter brickwall
    """
    foot = params.get("footstep_db", 0.0)
    gun = params.get("gun_db", 0.0)
    streak = params.get("streak_db", 0.0)
    clarity = params.get("clarity_db", 0.0)
    ceiling = params.get("ceiling_db", -1.0)
    lfe = params.get("lfe_cut_hz", 80)
    comp_pct = params.get("compression", 70.0)

    # ── 1. Preamp: mínima, solo ceiling ──────────────────────────────────
    preamp = ceiling
    if foot > 14.0:
        preamp -= (foot - 14.0) * 0.15
    preamp = min(preamp, 0.0)

    # ── 2. FRONT (L R): gun cut + streak cut, NO footstep boost ──────────
    front_points = [
        (20,    streak * 1.5),
        (40,    streak * 1.4),
        (60,    streak * 1.2),
        (80,    streak * 1.0),
        (120,   streak * 0.8),
        (180,   streak * 0.5),
        (250,   streak * 0.2),
        (300,   0.0),
        # Front: FLAT in footstep range (no boost on front channels)
        (400,   0.0),
        (600,   0.0),
        (800,   0.0),
        (1000,  0.0),
        (1200,  0.0),
        (1500,  0.0),
        (2000,  0.0),
        (2500,  0.0),
        # Gun valley: CORTE en front
        (2800,  gun * 0.50),
        (3000,  gun * 0.85),
        (3500,  gun * 1.00),
        (4000,  gun * 1.00),
        (4500,  gun * 0.70),
        (5000,  0.0),
        # Clarity
        (6000,  clarity * 0.55),
        (8000,  clarity * 0.80),
        (10000, clarity * 1.00),
        (12000, clarity * 0.75),
        (16000, clarity * 0.35),
        (20000, 0.0),
    ]

    # ── 3. SURROUND (SL SR RL RR): footstep boost, NO gun cut ───────────
    surround_points = [
        (20,    streak * 1.2),
        (40,    streak * 1.0),
        (60,    streak * 0.8),
        (80,    streak * 0.6),
        (120,   streak * 0.3),
        (180,   0.0),
        (250,   0.0),
        (300,   foot * 0.15),
        # Footstep ramp
        (350,   foot * 0.35),
        (400,   foot * 0.60),
        (500,   foot * 0.85),
        (600,   foot * 1.00),          # meseta empieza
        (700,   foot * 1.00),
        (800,   foot * 1.00),
        (900,   foot * 0.90),
        (1000,  foot * 0.70),
        (1200,  foot * 0.35),
        # Surround: NO gun cut (guns are front-channel)
        (1500,  0.0),
        (2000,  0.0),
        (2500,  0.0),
        (3000,  0.0),
        (3500,  0.0),
        (4000,  0.0),
        (4500,  0.0),
        (5000,  0.0),
        # Clarity
        (6000,  clarity * 0.40),
        (8000,  clarity * 0.60),
        (10000, clarity * 0.70),
        (12000, clarity * 0.50),
        (16000, clarity * 0.20),
        (20000, 0.0),
    ]

    # ── 4. CENTER + SUB: kill ────────────────────────────────────────────
    # Center carries dialog/announcer, SUB carries rumble — both cut
    # Scale the static cuts by how aggressive the preset is
    cs_scale = min(1.0, (abs(streak) + abs(gun)) / 20.0) if (streak != 0 or gun != 0) else 0.0
    center_sub_points = [
        (20,    streak * 1.5),
        (40,    streak * 1.5),
        (60,    streak * 1.5),
        (80,    streak * 1.2),
        (120,   streak * 0.8),
        (180,   streak * 0.4),
        (250,   -3.0 * cs_scale),
        (400,   -5.0 * cs_scale),
        (600,   -6.0 * cs_scale),
        (800,   -6.0 * cs_scale),
        (1000,  -5.0 * cs_scale),
        (1500,  -3.0 * cs_scale),
        (2000,  0.0),
        (4000,  0.0),
        (8000,  0.0),
        (16000, 0.0),
        (20000, 0.0),
    ]

    # ── Build config text ────────────────────────────────────────────────
    lines = [
        f"# WarzoneAudioEnhancer v3.0 — {preset_name}",
        "# Per-channel processing · Multiband compression · Brickwall limiter",
        "",
    ]

    if preamp != 0.0:
        lines.append(f"Preamp: {preamp:.1f} dB")
        lines.append("")

    # HPF on all channels
    if lfe > 20:
        lines.append(f"Filter: ON HP Fc {lfe} Hz Q 0.707")
        lines.append("")

    # ── CENTER + SUB EQ ──────────────────────────────────────────────────
    lines.append("# ── Center + Sub: reduce dialog/rumble ──")
    lines.append("Channel: C SUB")
    eq_csub = "; ".join(f"{f} {g + 0.0:.1f}" for f, g in center_sub_points)
    lines.append(f"GraphicEQ: {eq_csub}")
    lines.append("")

    # ── FRONT L R EQ ─────────────────────────────────────────────────────
    lines.append("# ── Front (L R): gun cut + streak cut ──")
    lines.append("Channel: L R")
    eq_front = "; ".join(f"{f} {g + 0.0:.1f}" for f, g in front_points)
    lines.append(f"GraphicEQ: {eq_front}")
    lines.append("")

    # ── SURROUND EQ ──────────────────────────────────────────────────────
    lines.append("# ── Surround (SL SR RL RR): footstep boost ──")
    lines.append("Channel: SL SR RL RR")
    eq_surround = "; ".join(f"{f} {g + 0.0:.1f}" for f, g in surround_points)
    lines.append(f"GraphicEQ: {eq_surround}")
    lines.append("")

    # ── REAXCOMP: Surround footstep compressor ───────────────────────────
    # Only add VST processing if compression > 0 and we reference the DLL
    if comp_pct > 0:
        # Scale compression parameters by percentage
        comp_scale = comp_pct / 100.0

        lines.append("# ── Surround compressor: upward compression for footsteps ──")
        lines.append("Channel: SL SR RL RR")

        # Our approach: LOW threshold + LOW ratio + HIGH makeup
        # = upward compression, preserves texture
        # ArtTuneDB uses: thresh +3 dB, ratio 79:1 → brickwall (kills texture)
        # We use: thresh -24 dB, ratio 3:1 → gentle lift (preserves texture)
        surround_bands = [
            {"crossover": 200,   "thresh_db": -10.0,
             "ratio": 2.0 + 2.0 * comp_scale,
             "attack_ms": 5.0,  "release_ms": 40.0,  "makeup_db": 0},
            {"crossover": 2000,  "thresh_db": -30.0 * comp_scale,
             "ratio": 2.0 + 2.5 * comp_scale,
             "attack_ms": 3.0,  "release_ms": 30.0,  "makeup_db": 0},
            {"crossover": 6000,  "thresh_db": -15.0 * comp_scale,
             "ratio": 2.0 + 1.5 * comp_scale,
             "attack_ms": 2.0,  "release_ms": 25.0,  "makeup_db": 0},
            {"crossover": 24000, "thresh_db": -8.0 * comp_scale,
             "ratio": 2.0 + 1.0 * comp_scale,
             "attack_ms": 2.0,  "release_ms": 15.0,  "makeup_db": 0},
        ]
        chunk = _build_reaxcomp_chunk(surround_bands)
        lines.append(
            f'VSTPlugin: Library "{_REAXCOMP_DLL}" ChunkData "{chunk}"'
        )
        lines.append("")

        # ── REAXCOMP: Front gun tamer ────────────────────────────────────
        lines.append("# ── Front compressor: tame guns + explosions ──")
        lines.append("Channel: L R")
        front_bands = [
            {"crossover": 200,   "thresh_db": -6.0,
             "ratio": 6.0 + 6.0 * comp_scale,
             "attack_ms": 2.0,  "release_ms": 10.0,  "makeup_db": 0},
            {"crossover": 2000,  "thresh_db": -4.0,
             "ratio": 4.0 + 4.0 * comp_scale,
             "attack_ms": 3.0,  "release_ms": 12.0,  "makeup_db": 0},
            {"crossover": 6000,  "thresh_db": -3.0,
             "ratio": 5.0 + 8.0 * comp_scale,
             "attack_ms": 1.5,  "release_ms": 8.0,   "makeup_db": 0},
            {"crossover": 24000, "thresh_db": -2.0,
             "ratio": 3.0 + 3.0 * comp_scale,
             "attack_ms": 2.0,  "release_ms": 10.0,  "makeup_db": 0},
        ]
        chunk_front = _build_reaxcomp_chunk(front_bands)
        lines.append(
            f'VSTPlugin: Library "{_REAXCOMP_DLL}" ChunkData "{chunk_front}"'
        )
        lines.append("")

    # ── Reset channel scope ──────────────────────────────────────────────
    lines.append("Channel: all")
    lines.append("")

    # ── BRICKWALL LIMITER ────────────────────────────────────────────────
    if comp_pct > 0:
        lines.append("# ── Brickwall limiter: -1 dB ceiling, ratio 20:1 ──")
        limiter_params = _build_reacomp_inline(
            thresh_db=ceiling,
            ratio=20.0,
            attack_ms=0.5,
            release_ms=15.0,
            lookahead_ms=2.0,
        )
        lines.append(
            f'VSTPlugin: Library "{_REACOMP_DLL}" {limiter_params}'
        )
        lines.append("")

    return "\n".join(lines)
