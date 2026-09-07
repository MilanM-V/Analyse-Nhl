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


def calculate_quarter_kelly(proba: float, cote: Optional[float], categorie: str = "", current_exposure: float = 0.0, max_exposure: float = 15.0) -> str:
    """Calcule la recommandation de mise fractionnée Quarter Kelly avec Money Management Global.

    Args:
        proba: Probabilité estimée de l'événement.
        cote: Cote décimale du bookmaker.
        categorie: Catégorie du pick (BUTEUR, PASSEUR, POINTEUR).
        current_exposure: Exposition totale actuelle du Portfolio.
        max_exposure: Plafond maximum autorisé (ex: 15.0 U).

    Returns:
        String de mise formatée (ex: "1.5 U").
    """
    if not cote or cote <= 1.05:
        return "1 U"

    b = cote - 1.0
    p = proba

    # NOTE (V2): La pénalité défenseur (p * 0.6) a été supprimée.
    # Le modèle calibré (CalibratedClassifierCV isotonique) produit
    # des probabilités déjà ajustées par position via les features
    # (ixg, sog, hdcf sont naturellement plus bas pour les D-men).
    # Garder le patch en plus = double pénalité injustifiée.

    q = 1.0 - p
    f = (p * b - q) / b

    # Plafond dynamique selon la catégorie
    cap = CATEGORY_CAPS.get(categorie, 2.0)

    if f > 0:
        # Fraction très prudente (1/8ème) car les cotes réelles ont beaucoup de variance
        eighth_f = f / 8.0
        units = round(eighth_f * 100 * 2) / 2  # arrondi à 0.5 près
        units = max(0.5, min(units, cap))
        
        # Money Management Global : on réduit la mise si on dépasse le plafond
        if current_exposure + units > max_exposure:
            remaining_capacity = max(0.0, max_exposure - current_exposure)
            # Arrondi à 0.5 près
            remaining_capacity = round(remaining_capacity * 2) / 2
            units = min(units, remaining_capacity)
            
            if units <= 0:
                logger.warning(f"Pari ignoré (Kelly {f/8.0:.2f}U) : Plafond d'exposition globale atteint ({current_exposure}/{max_exposure}U).")
                return "0 U"
            else:
                logger.warning(f"Mise réduite ({units}U au lieu de cap) : Plafond global presque atteint.")
                
        return f"{units} U"

    return "0 U"


def is_cote_valid(pick: dict, cote_min: float) -> bool:
    if not pick.get("Cote") or pick["Cote"] <= 1.05:
        logger.debug(f"Pari Rejeté (Absence de Cote) : {pick['Joueur']}")
        return False
    if cote_min > 0 and pick["Cote"] < cote_min:
        logger.debug(f"Pari Rejeté (Cote {pick['Cote']:.2f} < min {cote_min:.2f}) : {pick['Joueur']}")
        return False
        
    ev = (pick["Proba"] * pick["Cote"]) - 1.0
    # FILTRE EV ADAPTATIF (P9) : Seuil dynamique selon la hauteur de la cote
    cote = pick["Cote"]
    if cote < 2.00:
        min_ev = 0.08   # 8% pour contrer le vig bookmaker sur les petites cotes
    elif cote <= 3.50:
        min_ev = 0.05   # 5% zone standard
    else:
        min_ev = 0.10   # 10% pour compenser la forte variance sur les grosses cotes

    if ev < min_ev:
        logger.debug(f"Pari Rejeté (EV {ev*100:.1f}% < requis {min_ev*100:.0f}%) : {pick['Joueur']} @ {cote:.2f}")
        return False
    return True


def apply_kelly_to_picks(picks_list: list, current_exposure: float = 0.0, max_exposure: float = 15.0) -> float:
    """Calcule et injecte la mise Kelly sur chaque pick (mutation in-place).
    Met à jour l'exposition globale en cours.

    Args:
        picks_list: Liste de dicts de picks à enrichir avec 'Mise' et 'MiseNum'.
        current_exposure: Exposition actuelle avant traitement de ces picks.
        max_exposure: Plafond maximum autorisé.
        
    Returns:
        La nouvelle exposition totale après ces picks.
    """
    for p in picks_list:
        mise_str = calculate_quarter_kelly(
            p.get('Proba', 0),
            p.get('Cote'), 
            p.get('Categorie', ''),
            current_exposure=current_exposure,
            max_exposure=max_exposure
        )
        p["Mise"] = mise_str
        try:
            val = float(mise_str.replace(" U", ""))
            p["MiseNum"] = val
            current_exposure += val
        except (ValueError, AttributeError):
            p["MiseNum"] = 0.0
            
    return current_exposure
