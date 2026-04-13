"""
Presets de ecualizacion competitiva para EqualizerAPO.
v4.0 — Pipeline multi-archivo: 5 stages en subcarpeta WarzoneAE\

PIPELINE:
  Warzone -> Hi-Fi Cable 7.1 -> Voicemeeter -> APO[WarzoneAE/] -> Windows Sonic -> Audifonos

  5 STAGES en APO (subcarpeta WarzoneAE/):
  00_base.txt      — Preamp + HPF + Air Streak
  01_spatial.txt   — reajs.dll / ArtTuneKit Spatial Engine (7.1 → binaural)
  02_gun_tamer.txt — ReaXcomp Channel L R (comprime disparos)
  03_footstep.txt  — ReaXcomp Channel SL SR RL RR (sube pasos de enemigos)
  04_limiter.txt   — Clarity EQ + reacomp brickwall limiter
"""

import re
import sys
from pathlib import Path

# ─── Stage file list ──────────────────────────────────────────────────────────

STAGE_FILES = [
    "00_base.txt",
    "01_spatial.txt",
    "02_gun_tamer.txt",
    "03_footstep.txt",
    "04_limiter.txt",
]

# ─── ChunkData exactos extraidos de attachments/BO7_S3_pre*.txt ──────────────

# Channel: L R — Gun Tamer (comprime transientes de disparo)
_GUN_TAMER_CHUNK = "OAAAAAQAAAAAAAAAAABpQMAKYekaBPM/fDqgTtwwoD8OAAAAAAAAQAAAAAAAABhACgAAAJYAAAAKAAAAEAAAAAAAAAAAQJ9AACb8+I4k9D926pD/EWKkPwAAAAAAAARAAAAAAAAAGEAFAAAAZAAAAAoAAAAQAAAAAAAAAABwt0BAxGufyfPxP/w6oE7cMKA/AAAAAAAAAEAAAAAAAAAYQAMAAABQAAAACgAAABAAAAAAAAAAAHDXQAAAAAAAAPA/iDeFSympqT8HAAAAAAD4PwAAAAAAABhABQAAAGQAAAAKAAAAEAAAAAEAAAABAAAAAAAAAAAA8D8AAAAA"

# Channel: SL SR RL RR — Footstep Comp (upward compression, sube pasos de enemigos)
_FOOTSTEP_COMP_CHUNK = "OAAAAAQAAAAAAAAAAABpQAAAAAAAAPA/9YSWLT8dwD8AAAAAAAD4PwAAAAAAACBACgAAAJYAAAAPAAAAEAAAAAAAAAAAQJ9AAG7o98CZ9j+por0VZciJP8DMzMzMzPw/AAAAAAAAJEAIAAAAeAAAABQAAAAQAAAAAAAAAABwt0AAAAAAAADwP2cBPE+RRIA/BQAAAAAA+D8AAAAAAAAkQAUAAABkAAAAFAAAABAAAAAAAAAAAHDXQAAAAAAAAPA/AKr4wwonsD8AAAAAAAD4PwAAAAAAABBABQAAAJYAAAAPAAAAEAAAAAEAAAABAAAAAAAAAAAA8D8AAAAA"

# ─── DLL finders ──────────────────────────────────────────────────────────────

def _find_reajs_path() -> str:
    for p in [
        Path(r"C:\Program Files\VSTPlugins\ReaPlugs\reajs.dll"),
        Path(r"C:\Program Files (x86)\VSTPlugins\ReaPlugs\reajs.dll"),
        Path(r"C:\Program Files\REAPER (x64)\Plugins\reajs.dll"),
    ]:
        if p.exists():
            return str(p)
    return r"C:\Program Files\VSTPlugins\ReaPlugs\reajs.dll"


def _find_reaxcomp_path() -> str:
    for p in [
        Path(r"C:\Program Files\VSTPlugins\ReaPlugs\reaxcomp-standalone.dll"),
        Path(r"C:\Program Files (x86)\VSTPlugins\ReaPlugs\reaxcomp-standalone.dll"),
    ]:
        if p.exists():
            return str(p)
    return r"C:\Program Files\VSTPlugins\ReaPlugs\reaxcomp-standalone.dll"


def find_reaplugs_path() -> str:
    for p in [
        Path(r"C:\Program Files\VSTPlugins\ReaPlugs\reacomp-standalone.dll"),
        Path(r"C:\Program Files (x86)\VSTPlugins\ReaPlugs\reacomp-standalone.dll"),
    ]:
        if p.exists():
            return str(p)
    return r"C:\Program Files\VSTPlugins\ReaPlugs\reacomp-standalone.dll"

# ─── Spatial Engine loader ────────────────────────────────────────────────────

def _attachments_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / "attachments"
    return Path(__file__).parent / "attachments"


_VARIANT_FILES = {
    "competitive": "BO7_S3_pre.txt",
    "clean":       "BO7_S3_pre_clean.txt",
    "streamer":    "BO7_S3_pre_streamer.txt",
}


def _load_spatial_stage(variant) -> str:
    """Returns content for 01_spatial.txt for the given variant.
    Reads the Spatial Engine block from the attachment file and replaces
    the hardcoded reajs.dll path with the detected path.
    """
    if not variant:
        return (
            "# WarzoneAE 01_spatial.txt — bypass (sin Spatial Engine)\n"
            "# Channel: all\n"
        )

    fname = _VARIANT_FILES.get(variant, "BO7_S3_pre.txt")
    att_file = _attachments_dir() / fname
    reajs = _find_reajs_path()

    if not att_file.exists():
        return (
            f"# WarzoneAE 01_spatial.txt — [{variant}] (attachment no encontrado: {fname})\n"
            "# Channel: all\n"
        )

    try:
        raw = att_file.read_text(encoding="utf-8")
    except Exception as exc:
        return f"# WarzoneAE 01_spatial.txt — error al leer {fname}: {exc}\n"

    # Extract lines from 'Channel: L R C SUB...' up to (not including) '# --- L R ---'
    lines = raw.splitlines()
    stage_lines = []
    in_block = False
    for line in lines:
        stripped = line.strip()
        if not in_block and stripped.startswith("Channel:") and "L R C SUB" in stripped:
            in_block = True
        if in_block:
            if stripped == "# --- L R ---":
                break
            if "reajs.dll" in line and "Library" in line:
                reajs_rep = reajs
                line = re.sub(r'Library\s+"[^"]*reajs\.dll"', lambda m: f'Library "{reajs_rep}"', line)
            stage_lines.append(line)

    header = f"# WarzoneAE 01_spatial.txt — Spatial Engine [{variant}]"
    return header + "\n" + "\n".join(stage_lines) + "\n"

# ─── Reacomp inline builder ───────────────────────────────────────────────────

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

# ─── Stage file builders ──────────────────────────────────────────────────────

def _build_00_base(params: dict, preset_name: str) -> str:
    foot    = params.get("footstep_db",  0.0)
    streak  = params.get("streak_db",    0.0)
    clarity = params.get("clarity_db",   0.0)
    ceiling = params.get("ceiling_db",  -1.0)
    lfe     = params.get("lfe_cut_hz",    80)
    max_boost = max(foot, 0.0) + max(clarity, 0.0)
    preamp    = min(ceiling - max_boost * 0.3, 0.0)
    lines = [
        "# WarzoneAE 00_base.txt — Preamp + HPF + Air Streak",
        f"# WarzoneAudioEnhancer v4.0 — {preset_name}",
        "",
        "Channel: all",
    ]
    if preamp < 0.0:
        lines.append(f"Preamp: {preamp:.1f} dB")
    if lfe > 20:
        lines.append(f"Filter: ON HP Fc {lfe} Hz Q 0.707")
    if streak != 0.0:
        lines.append("# Air Streak — rumble cut (quita lo que enmascara pasos)")
        lines.append(f"Filter: ON LSC Fc 41 Hz Gain {max(streak * 0.05, -3.0):.2f} dB Q 0.797")
        lines.append(f"Filter: ON PK Fc 80 Hz Gain {streak:.1f} dB Q 0.8")
        lines.append(f"Filter: ON PK Fc 200 Hz Gain {streak * 0.35:.1f} dB Q 1.2")
    lines.append("Filter: ON PK Fc 4500 Hz Gain -2.0 dB Q 1.5")
    return "\n".join(lines) + "\n"


def _build_02_gun_tamer(params: dict) -> str:
    gun      = params.get("gun_db", 0.0)
    reaxcomp = _find_reaxcomp_path()
    lines = [
        "# WarzoneAE 02_gun_tamer.txt — Gun Tamer",
        "# ReaXcomp Channel L R — comprime transientes de disparo",
        "",
        "Channel: L R",
        f'VSTPlugin: Library "{reaxcomp}" ChunkData "{_GUN_TAMER_CHUNK}"',
    ]
    if gun != 0.0:
        lines.append(f"Filter: ON PK Fc 500 Hz Gain {gun * 0.6:.1f} dB Q 1.2")
        lines.append(f"Filter: ON PK Fc 800 Hz Gain {gun:.1f} dB Q 1.5")
    return "\n".join(lines) + "\n"


def _build_03_footstep(params: dict) -> str:
    foot     = params.get("footstep_db", 0.0)
    reaxcomp = _find_reaxcomp_path()
    lines = [
        "# WarzoneAE 03_footstep.txt — Footstep Compressor",
        "# ReaXcomp Channel SL SR RL RR — sube pasos de enemigos",
        "",
        "Channel: SL SR RL RR",
        f'VSTPlugin: Library "{reaxcomp}" ChunkData "{_FOOTSTEP_COMP_CHUNK}"',
    ]
    if foot != 0.0:
        lines.append(f"Filter: ON PK Fc 1500 Hz Gain {foot * 0.4:.1f} dB Q 2.0")
        lines.append(f"Filter: ON PK Fc 2500 Hz Gain {foot * 0.6:.1f} dB Q 2.0")
    return "\n".join(lines) + "\n"


def _build_04_limiter(params: dict) -> str:
    clarity  = params.get("clarity_db",   0.0)
    ceiling  = params.get("ceiling_db",  -1.0)
    comp_pct = params.get("compression",  70.0)
    reacomp  = find_reaplugs_path()
    lines = [
        "# WarzoneAE 04_limiter.txt — Clarity + Brickwall Limiter",
        "",
        "Channel: all",
    ]
    if clarity != 0.0:
        lines.append(f"Filter: ON PK Fc 8000 Hz Gain {clarity:.1f} dB Q 1.0")
    if comp_pct > 0:
        ratio = 2.0 + 18.0 * (comp_pct / 100.0)
        lines.append(f'VSTPlugin: Library "{reacomp}" {_build_reacomp_inline(ceiling, ratio)}')
    return "\n".join(lines) + "\n"

# ─── Main builder ─────────────────────────────────────────────────────────────

def build_stage_files(params: dict, preset_name: str = "Custom",
                      spatial_variant=None) -> dict:
    """Returns dict mapping STAGE_FILES names → text content (5 files)."""
    return {
        "00_base.txt":      _build_00_base(params, preset_name),
        "01_spatial.txt":   _load_spatial_stage(spatial_variant),
        "02_gun_tamer.txt": _build_02_gun_tamer(params),
        "03_footstep.txt":  _build_03_footstep(params),
        "04_limiter.txt":   _build_04_limiter(params),
    }


def params_to_apo_config(params: dict, preset_name: str = "Custom") -> str:
    """Legacy single-file API — joins all stage files."""
    return "\n\n".join(build_stage_files(params, preset_name).values())


# ─── Presets ──────────────────────────────────────────────────────────────────

PRESETS = {
    "warzone": {
        "name": "Warzone",
        "icon": "🎯",
        "description": "Pasos OP · gun tamer · brickwall limiter",
        "_spatial_variant": "competitive",
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
        "_spatial_variant": "clean",
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
        "_spatial_variant": "clean",
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
        "_spatial_variant": None,
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


def _build_reacomp_inline_legacy(thresh_db: float, ratio: float,
                                  attack_ms: float = 0.6, release_ms: float = 10.0) -> str:
    return _build_reacomp_inline(thresh_db, ratio, attack_ms, release_ms)




    # Global: clarity + limiter
    lines.append("Channel: all")
    if clarity != 0.0:
        lines.append(f"Filter: ON PK Fc 8000 Hz Gain {clarity:.1f} dB Q 1.0")
    if comp_pct > 0:
        ratio = 2.0 + 18.0 * (comp_pct / 100.0)
        lines.append(f'VSTPlugin: Library "{reacomp}" {_build_reacomp_inline(ceiling, ratio)}')

    return "\n".join(lines)
