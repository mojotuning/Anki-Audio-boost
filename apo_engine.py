"""
Motor de integración con EqualizerAPO.
Detecta APO, escribe configuración, gestiona perfiles.
"""
import json
import os
import subprocess
import sys
import winreg
from pathlib import Path

from presets import PRESETS, STAGE_FILES, build_stage_files

# Subcarpeta y marcadores de bloque en config.txt
_OUR_SUBDIR   = "WarzoneAE"
_BLOCK_START  = "# === WarzoneAE BEGIN ==="
_BLOCK_END    = "# === WarzoneAE END ==="


def _get_data_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(os.path.dirname(sys.executable)) / "data"
    return Path("data")


DATA_DIR = _get_data_dir()
DATA_DIR.mkdir(exist_ok=True)
_PROFILES_FILE = DATA_DIR / "profiles.json"
_STATE_FILE = DATA_DIR / "state.json"


class APOEngine:
    def __init__(self):
        self.apo_path: Path | None = self._find_apo()
        self.config_dir: Path | None = self.apo_path / "config" if self.apo_path else None

    @property
    def our_dir(self) -> Path | None:
        """Ruta a la subcarpeta WarzoneAE dentro del config de APO."""
        return self.config_dir / _OUR_SUBDIR if self.config_dir else None
        self.enabled = False
        self.active_preset: str = "warzone"
        self.params: dict = dict(PRESETS["warzone"]["params"])
        self._load_state()

    # ─── Detección de APO ─────────────────────────────────────────────────

    @staticmethod
    def _find_apo() -> Path | None:
        """Busca EqualizerAPO via registro o rutas comunes."""
        # Registro
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for sub in (r"SOFTWARE\EqualizerAPO", r"SOFTWARE\WOW6432Node\EqualizerAPO"):
                try:
                    key = winreg.OpenKey(hive, sub)
                    val, _ = winreg.QueryValueEx(key, "InstallPath")
                    winreg.CloseKey(key)
                    p = Path(val)
                    if p.exists():
                        return p
                except OSError:
                    pass
        # Rutas comunes
        for p in (Path(r"C:\Program Files\EqualizerAPO"),
                  Path(r"C:\Program Files (x86)\EqualizerAPO")):
            if (p / "config").is_dir():
                return p
        return None

    def is_apo_installed(self) -> bool:
        return self.config_dir is not None and self.config_dir.is_dir()

    # ─── Detección de software ────────────────────────────────────────────

    def detect_software(self) -> dict:
        """Detecta software de audio instalado."""
        result = {
            "apo": self.is_apo_installed(),
            "apo_path": str(self.apo_path) if self.apo_path else None,
            "voicemeeter": False,
            "vb_cable": False,
            "reaplugs": False,
            "reajs": False,
            "stages": {},
        }

        # Voicemeeter
        for sub in (r"SOFTWARE\VB-Audio\Voicemeeter",
                    r"SOFTWARE\WOW6432Node\VB-Audio\Voicemeeter"):
            try:
                k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub)
                winreg.CloseKey(k)
                result["voicemeeter"] = True
                break
            except OSError:
                pass
        if not result["voicemeeter"]:
            # Fallback: buscar exe
            for p in (Path(r"C:\Program Files\VB\Voicemeeter"),
                      Path(r"C:\Program Files (x86)\VB\Voicemeeter")):
                if p.exists():
                    result["voicemeeter"] = True
                    break

        # VB-Cable
        for sub in (r"SOFTWARE\VB-Audio\Cable",
                    r"SOFTWARE\WOW6432Node\VB-Audio\Cable"):
            try:
                k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub)
                winreg.CloseKey(k)
                result["vb_cable"] = True
                break
            except OSError:
                pass

        # reajs.dll (Spatial Engine — requerido para 01_spatial.txt)
        from presets import _find_reajs_path
        result["reajs"] = Path(_find_reajs_path()).exists()

        # Stage files: verificar si los 5 archivos de WarzoneAE existen
        result["stages"] = {}
        if self.our_dir:
            for f in STAGE_FILES:
                result["stages"][f] = (self.our_dir / f).exists()
        else:
            result["stages"] = {f: False for f in STAGE_FILES}

        # ReaPlugs — buscar en múltiples ubicaciones y variantes de nombre
        # Paso 1: buscar carpetas que contengan "reaplug" en su nombre
        _pf = Path(r"C:\Program Files")
        _pf86 = Path(r"C:\Program Files (x86)")
        reaplugs_dirs = []
        for parent in (_pf, _pf86):
            if parent.is_dir():
                try:
                    for child in parent.iterdir():
                        if child.is_dir():
                            low = child.name.lower()
                            # Carpetas VST (VSTPlugins, VtsPlugins, vstplugins, etc.)
                            if "vst" in low or "vts" in low or "plug" in low:
                                reaplugs_dirs.append(child)
                            # Carpeta ReaPlugs directa
                            if "reaplug" in low or "reaper" in low:
                                reaplugs_dirs.append(child)
                except PermissionError:
                    pass
        # Carpetas adicionales conocidas
        reaplugs_dirs.extend([
            Path(r"C:\Program Files\Common Files\VST3"),
            Path(r"C:\Program Files\Common Files\VST2"),
            Path(r"C:\Program Files\REAPER (x64)\Plugins\FX"),
            Path(os.path.expandvars(r"%APPDATA%\REAPER\Plugins")),
        ])
        if self.config_dir:
            reaplugs_dirs.append(self.config_dir / "Plugins")
        # Buscar DLLs de ReaPlugs en todas las carpetas (incluyendo subdirs)
        for d in reaplugs_dirs:
            if not d.is_dir():
                continue
            # Buscar en la carpeta y un nivel de subdirectorio
            for pattern in ("rea*.dll", "Rea*.dll"):
                if any(d.glob(pattern)) or any(d.glob(f"*/{pattern}")):
                    result["reaplugs"] = True
                    break
            if result["reaplugs"]:
                break
        # Paso 2: revisar config.txt de APO para referencias a ReaPlugs VST
        if not result["reaplugs"] and self.config_dir:
            try:
                cfg = (self.config_dir / "config.txt").read_text(encoding="utf-8", errors="ignore").lower()
                if "reaxcomp" in cfg or "reacomp" in cfg or "reaeq" in cfg or "reaplug" in cfg:
                    result["reaplugs"] = True
            except Exception:
                pass
        # Paso 3: registro de REAPER
        if not result["reaplugs"]:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for sub in (r"SOFTWARE\REAPER", r"SOFTWARE\WOW6432Node\REAPER"):
                    try:
                        k = winreg.OpenKey(hive, sub)
                        winreg.CloseKey(k)
                        result["reaplugs"] = True
                        break
                    except OSError:
                        pass
                if result["reaplugs"]:
                    break

        return result

    # ─── Aplicar / Desactivar ─────────────────────────────────────────────

    def apply(self) -> dict:
        """Escribe los 5 archivos de stage a WarzoneAE/ dentro del config de APO."""
        if not self.is_apo_installed():
            return {"ok": False, "error": "EqualizerAPO no esta instalado"}

        try:
            preset_info = PRESETS.get(self.active_preset, PRESETS["warzone"])
            preset_name = preset_info.get("name", "Custom")
            spatial_variant = preset_info.get("_spatial_variant", "competitive")

            our = self.our_dir
            our.mkdir(parents=True, exist_ok=True)

            stage_files = build_stage_files(self.params, preset_name, spatial_variant)
            for fname, content in stage_files.items():
                (our / fname).write_text(content, encoding="utf-8")

            self._ensure_includes()
            self.enabled = True
            self._save_state()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def disable(self) -> dict:
        """Desactiva el procesamiento escribiendo comentarios de bypass en los 5 archivos."""
        if not self.is_apo_installed():
            return {"ok": False, "error": "EqualizerAPO no esta instalado"}

        try:
            our = self.our_dir
            if our and our.is_dir():
                bypass_text = (
                    "# WarzoneAudioEnhancer — DESACTIVADO\n"
                    "# Channel: all\n"
                )
                for fname in STAGE_FILES:
                    (our / fname).write_text(bypass_text, encoding="utf-8")
            self.enabled = False
            self._save_state()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _ensure_includes(self):
        """Inserta/reemplaza el bloque WarzoneAE en config.txt de APO."""
        main_config = self.config_dir / "config.txt"

        include_lines = []
        for fname in STAGE_FILES:
            include_lines.append(f"Include: {_OUR_SUBDIR}\\{fname}")

        block = (
            f"{_BLOCK_START}\n"
            + "\n".join(include_lines)
            + f"\n{_BLOCK_END}\n"
        )

        if not main_config.exists():
            main_config.write_text(block, encoding="utf-8")
            return

        content = main_config.read_text(encoding="utf-8")

        # Replace existing block if present
        if _BLOCK_START in content and _BLOCK_END in content:
            import re as _re
            content = _re.sub(
                rf"{_re.escape(_BLOCK_START)}.*?{_re.escape(_BLOCK_END)}\n?",
                block,
                content,
                flags=_re.DOTALL,
            )
            main_config.write_text(content, encoding="utf-8")
            return

        # No existing block — append at the end
        if not content.endswith("\n"):
            content += "\n"
        content += block
        main_config.write_text(content, encoding="utf-8")

    # ─── Parámetros ───────────────────────────────────────────────────────

    def set_preset(self, name: str) -> dict:
        """Carga un preset por nombre."""
        if name not in PRESETS:
            return {"ok": False, "error": f"Preset '{name}' no existe"}
        self.active_preset = name
        self.params = dict(PRESETS[name]["params"])
        self._save_state()
        return {"ok": True, "params": self.params, "preset": name}

    def update_param(self, key: str, value: float) -> dict:
        """Actualiza un parámetro individual y re-aplica si está activo."""
        if key not in self.params:
            return {"ok": False, "error": f"Parámetro '{key}' no existe"}
        self.params[key] = float(value)
        self.active_preset = "custom"
        if self.enabled:
            return self.apply()
        self._save_state()
        return {"ok": True}

    def get_state(self) -> dict:
        """Estado actual completo para la UI."""
        return {
            "enabled": self.enabled,
            "preset": self.active_preset,
            "params": dict(self.params),
        }

    # ─── Perfiles ─────────────────────────────────────────────────────────

    def save_profile(self, name: str) -> dict:
        profiles = self._load_profiles()
        profiles[name] = {
            "params": dict(self.params),
            "preset": self.active_preset,
        }
        self._save_profiles(profiles)
        return {"ok": True, "profiles": list(profiles.keys())}

    def load_profile(self, name: str) -> dict:
        profiles = self._load_profiles()
        if name not in profiles:
            return {"ok": False, "error": f"Perfil '{name}' no existe"}
        p = profiles[name]
        # Merge with current preset defaults so old profiles (missing new keys
        # like "compression") get sane defaults instead of crashing.
        base = PRESETS.get(self.active_preset, PRESETS["warzone"])["params"]
        self.params = {**base, **{k: v for k, v in p["params"].items() if k in base}}
        self.active_preset = p.get("preset", "custom")
        self._save_state()
        return {"ok": True, "params": self.params, "preset": self.active_preset}

    def delete_profile(self, name: str) -> dict:
        profiles = self._load_profiles()
        profiles.pop(name, None)
        self._save_profiles(profiles)
        return {"ok": True, "profiles": list(profiles.keys())}

    def list_profiles(self) -> dict:
        return self._load_profiles()

    def _load_profiles(self) -> dict:
        try:
            if _PROFILES_FILE.exists():
                return json.loads(_PROFILES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_profiles(self, profiles: dict):
        _PROFILES_FILE.write_text(
            json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8")

    # ─── Estado persistente ───────────────────────────────────────────────

    def _save_state(self):
        try:
            state = {
                "enabled": self.enabled,
                "preset": self.active_preset,
                "params": self.params,
            }
            _STATE_FILE.write_text(
                json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _load_state(self):
        try:
            if _STATE_FILE.exists():
                state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
                self.enabled = state.get("enabled", False)
                self.active_preset = state.get("preset", "warzone")
                saved_params = state.get("params", {})
                # Merge: usar defaults del preset como base, override con guardados
                base = PRESETS.get(self.active_preset, PRESETS["warzone"])["params"]
                self.params = {**base, **{k: v for k, v in saved_params.items() if k in base}}
        except Exception:
            pass
