"""
nhl/core/kelly.py — Shim de compatibilité.

Redirige vers shared/kelly.py pour les fonctions communes,
tout en gardant les constantes NHL-spécifiques.
"""
from shared.kelly import (
    calculate_quarter_kelly,
    is_cote_valid,
    apply_kelly_to_picks,
    CATEGORY_CAPS,
)

__all__ = [
    "calculate_quarter_kelly",
    "is_cote_valid",
    "apply_kelly_to_picks",
    "CATEGORY_CAPS",
]
