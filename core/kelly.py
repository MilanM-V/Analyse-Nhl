"""
core/kelly.py — Calcul de mise fractionnée (Quarter Kelly) et validation EV.

Extrait de bot_logic.py pour réutilisation par le dashboard et les tests.
"""
import logging
from typing import Dict, Optional

from config.settings import cfg

logger = logging.getLogger("NHL_Bot")

# Plafonds de mise par catégorie (depuis config/settings.toml)
CATEGORY_CAPS: Dict[str, float] = {
    "BUTEUR": cfg.kelly.buteur_cap,
    "PASSEUR": cfg.kelly.passeur_cap,
    "POINTEUR": cfg.kelly.pointeur_cap,
}


def calculate_quarter_kelly(proba: float, cote: Optional[float], categorie: str = "") -> str:
    """Calcule la recommandation de mise fractionnée Quarter Kelly.

    Args:
        proba: Probabilité estimée de l'événement.
        cote: Cote décimale du bookmaker.
        categorie: Catégorie du pick (BUTEUR, PASSEUR, POINTEUR).

    Returns:
        String de mise formatée (ex: "1.5 U").
    """
    if not cote or cote <= 1.05:
        return "1 U"

    b = cote - 1.0
    p = proba

    # Pénalité pour les défenseurs : leur taux de conversion réel
    # est inférieur aux forwards (tirs lointains)
    if categorie == "DÉFENSEUR":
        p = p * 0.6

    q = 1.0 - p
    f = (p * b - q) / b

    # Plafond dynamique selon la catégorie
    cap = CATEGORY_CAPS.get(categorie, 2.0)

    if f > 0:
        quarter_f = f / 4.0
        units = round(quarter_f * 100 * 2) / 2  # arrondi à 0.5 près
        units = max(0.5, min(units, cap))
        return f"{units} U"

    return "0 U"


def is_cote_valid(pick: dict, cote_min: float) -> bool:
    """Vérifie que la cote existe, dépasse le minimum, et que l'EV est positive.

    Args:
        pick: Dictionnaire du pick contenant 'Cote', 'Proba', 'Joueur'.
        cote_min: Cote minimum requise pour le marché.

    Returns:
        True si le pick est valide pour le pari.
    """
    if not pick.get("Cote") or pick["Cote"] <= 1.05:
        logger.debug(f"Pari Rejeté (Absence de Cote) : {pick['Joueur']}")
        return False
    if cote_min > 0 and pick["Cote"] < cote_min:
        logger.debug(f"Pari Rejeté (Cote {pick['Cote']:.2f} < min {cote_min:.2f}) : {pick['Joueur']}")
        return False
    ev = (pick["Proba"] * pick["Cote"]) - 1.0
    if ev < 0.02:
        logger.debug(f"Pari Rejeté (-EV) : {pick['Joueur']} (EV: {ev*100:.1f}%)")
        return False
    return True


def apply_kelly_to_picks(picks_list: list) -> None:
    """Calcule et injecte la mise Kelly sur chaque pick (mutation in-place).

    Args:
        picks_list: Liste de dicts de picks à enrichir avec 'Mise' et 'MiseNum'.
    """
    for p in picks_list:
        mise_str = calculate_quarter_kelly(
            p.get('Proba', 0),
            p.get('Cote'), p.get('Categorie', '')
        )
        p["Mise"] = mise_str
        try:
            p["MiseNum"] = float(mise_str.replace(" U", ""))
        except (ValueError, AttributeError):
            p["MiseNum"] = 1.0
