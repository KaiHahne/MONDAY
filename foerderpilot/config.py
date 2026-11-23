from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "connectors": [],
    "programs_dir": "programs",
    "profile_file": None,
    "profile_overrides": {},
    "output_dir": "out",
    "sample_rows": 5,
    "max_applications": 5,
}


def load_config(path: str | Path) -> dict[str, Any]:
    """Laedt die YAML-Konfiguration und fuellt Defaults auf.

    Secrets duerfen in der Datei nur als 'env:VAR_NAME' referenziert werden;
    Klartext-Keys werden abgelehnt.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config-Datei existiert nicht: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config {p} muss ein YAML-Objekt sein.")
    _reject_plaintext_secrets(data, source=str(p))
    config = dict(DEFAULTS)
    config.update(data)
    config["_config_path"] = str(p)
    base = p.resolve().parent
    for key in ("programs_dir", "output_dir"):
        config[key] = _resolve_rel(config[key], base)
    if config.get("profile_file"):
        config["profile_file"] = _resolve_rel(config["profile_file"], base)
    for conn in config.get("connectors", []):
        if isinstance(conn, dict) and "root" in conn:
            conn["root"] = _resolve_rel(conn["root"], base)
    return config


def _resolve_rel(value: Any, base: Path) -> Any:
    """Relative Pfade in der Config werden gegen das Config-Verzeichnis aufgeloest."""
    if isinstance(value, str) and value and not os.path.isabs(value) and not value.startswith("env:"):
        return str(base / value)
    return value


_SECRET_KEY_HINTS = ("key", "secret", "token", "password", "credential")


def _reject_plaintext_secrets(node: Any, source: str, path: str = "") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            full = f"{path}.{key}" if path else str(key)
            lowered = str(key).lower()
            if any(h in lowered for h in _SECRET_KEY_HINTS) and isinstance(value, str):
                if value.startswith("env:"):
                    continue
                raise ValueError(
                    f"{source}: moegliches Secret in Klartext bei '{full}'. "
                    "Bitte als 'env:VAR_NAME' referenzieren, nie direkt eintragen."
                )
            _reject_plaintext_secrets(value, source, full)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _reject_plaintext_secrets(item, source, f"{path}[{i}]")


def load_profile_file(path: str | Path) -> dict[str, Any]:
    """Laedt ein optionales YAML mit manuell gepflegten Profildaten."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Profil-Datei existiert nicht: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Profil-Datei {p} muss ein YAML-Objekt sein.")
    return {k: v for k, v in data.items() if not str(k).startswith("_")}
