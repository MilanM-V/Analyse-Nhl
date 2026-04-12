"""
config/settings.py — Charge le fichier TOML de configuration et expose les valeurs.

Usage:
    from config.settings import cfg
    print(cfg.thresholds.buteurs.elite_qs)  # 9.75
"""

import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict


_CONFIG_PATH = Path(__file__).parent / "settings.toml"


def _to_namespace(d: Dict[str, Any]) -> SimpleNamespace:
    """Convertit récursivement un dict en SimpleNamespace pour un accès par attribut."""
    for k, v in d.items():
        if isinstance(v, dict):
            d[k] = _to_namespace(v)
    return SimpleNamespace(**d)


def load_config(path: Path = _CONFIG_PATH) -> SimpleNamespace:
    """Charge le fichier TOML et retourne un namespace imbriqué.

    Args:
        path: Chemin vers le fichier TOML.

    Returns:
        SimpleNamespace avec la config accessible par attribut.
    """
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return _to_namespace(raw)


cfg = load_config()
