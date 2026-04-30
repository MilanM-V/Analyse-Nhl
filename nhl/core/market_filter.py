"""
core/market_filter.py — Filtrage des joueurs par marché (Buteur, Passeur, Pointeur).

Extrait de bot_logic.py pour réutilisation par le dashboard et les tests.
"""
import os
import json
import logging
from typing import Dict, Any, Optional, Tuple

from config.settings import cfg

logger = logging.getLogger("NHL.Filter")


def load_dynamic_probas() -> Dict[str, float]:
    """Charge les probabilités bayésiennes depuis config/probas.json.

    Returns:
        Dict avec les clés 'buteurs', 'passeurs', 'pointeurs' et leurs probas.
    """
    probas = {"buteurs": 0.35, "passeurs": 0.50, "pointeurs": 0.65}
    try:
        probas_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "probas.json")
        if os.path.exists(probas_path):
            with open(probas_path, "r") as pf:
                data = json.load(pf)
            for key in probas:
                if key in data and "proba" in data[key]:
                    probas[key] = data[key]["proba"]
            logger.info(f"Probas dynamiques chargées : B={probas['buteurs']:.3f} A={probas['passeurs']:.3f} P={probas['pointeurs']:.3f}")
        else:
            logger.info("config/probas.json non trouvé, utilisation des probas par défaut.")
    except Exception as e:
        logger.warning(f"Erreur chargement probas.json : {e}")
    return probas


def evaluate_player_markets(
    player: str,
    p_form: Dict[str, Any],
    v5_p: Dict[str, Any],
    adv_stats: Dict[str, Any],
    is_home: bool,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Évalue un joueur contre les filtres des 3 marchés.

    Args:
        player: Nom du joueur.
        p_form: Stats récentes (last 10 games).
        v5_p: Stats saison complète.
        adv_stats: Stats de l'équipe adverse.
        is_home: True si le joueur joue à domicile.

    Returns:
        Tuple (cat_but, cat_ast, cat_pts) — chaque valeur est le nom de la
        catégorie ("BUTEUR", "PASSEUR", "POINTEUR") ou None si non qualifié.
    """
    # Extractions de métriques
    season_g = float(v5_p.get('G_GP', 0)) if v5_p else 0.0
    l10_sog = float(p_form.get('L10_SOG_G', 0))
    l10_hdcf = float(p_form.get('L10_iHDCF_G', 0))

    season_a = float(v5_p.get('A_GP', 0)) if v5_p else 0.0
    season_pts = float(v5_p.get('Pts_GP', 0)) if v5_p else 0.0

    opp_ga = float(adv_stats.get('GA_G', 0)) if adv_stats else 0.0
    l10_a = float(p_form.get('L10_A_G', 0))
    l10_pts = float(p_form.get('L10_Pts_G', 0))
    p_atoi = float(p_form.get('ATOI', 0))
    pos = str(v5_p.get('Position', '')).strip() if v5_p else ""

    # Mode Playoff : On ignore le filtre "Home Only" pour augmenter le volume
    is_playoff = (cfg.api.mode == "playoff")

    # Buteurs
    cat_but = None
    if (is_home or is_playoff or not cfg.thresholds.buteurs.home_only) and \
       pos not in ('D', 'LD', 'RD') and \
       season_g >= cfg.thresholds.buteurs.season_g_min and \
       l10_sog >= cfg.thresholds.buteurs.l10_sog_min and \
       l10_hdcf >= cfg.thresholds.buteurs.l10_hdcf_min and \
       opp_ga >= cfg.thresholds.buteurs.opp_ga_min:
        cat_but = "BUTEUR"

    # Passeurs
    cat_ast = None
    if (is_home or is_playoff or not cfg.thresholds.passeurs.home_only) and \
       season_a >= cfg.thresholds.passeurs.season_a_min and \
       l10_a >= cfg.thresholds.passeurs.l10_a_min and \
       p_atoi >= cfg.thresholds.passeurs.atoi_min and \
       opp_ga >= cfg.thresholds.passeurs.opp_ga_min:
        cat_ast = "PASSEUR"

    # Pointeurs
    cat_pts = None
    if (is_home or is_playoff or not cfg.thresholds.pointeurs.home_only) and \
       season_pts >= cfg.thresholds.pointeurs.season_pts_min and \
       l10_pts >= cfg.thresholds.pointeurs.l10_pts_min and \
       p_atoi >= cfg.thresholds.pointeurs.atoi_min and \
       opp_ga >= cfg.thresholds.pointeurs.opp_ga_min:
        cat_pts = "POINTEUR"

    return cat_but, cat_ast, cat_pts
