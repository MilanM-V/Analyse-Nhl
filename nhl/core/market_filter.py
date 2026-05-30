"""
core/market_filter.py — Filtrage des joueurs par marché (Buteur, Passeur).

Intègre désormais le chargement des modèles ML (XGBoost et Logistic Regression)
et la création des features pour l'inférence en direct.
"""
import os
import logging
import joblib
import numpy as np
from typing import Dict, Any, Optional, Tuple

from config.settings import cfg

logger = logging.getLogger("NHL.Filter")


def load_ml_models() -> Dict[str, Any]:
    """Charge les modèles ML depuis le dossier models.

    Returns:
        Dict avec les clés 'but' et 'ast' contenant les modèles entraînés.
    """
    models = {}
    try:
        models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
        
        path_but = os.path.join(models_dir, "ml_model_but.pkl")
        if os.path.exists(path_but):
            models['but'] = joblib.load(path_but)
            logger.info("Modèle ML Buteur (XGBoost) chargé.")
            
        path_ast = os.path.join(models_dir, "ml_model_ast.pkl")
        if os.path.exists(path_ast):
            models['ast'] = joblib.load(path_ast)
            logger.info("Modèle ML Passeur (Logistic Regression) chargé.")
            
    except Exception as e:
        logger.error(f"Erreur chargement modèles ML : {e}")
    return models


def prepare_features_for_player(p_form: Dict[str, Any], v5_p: Dict[str, Any], adv_stats: Dict[str, Any], 
                                is_home: bool, b2b: bool, opp_b2b: bool, pp1: bool, consec_goals: int, 
                                features_list: list) -> np.ndarray:
    """Prépare le vecteur de features pour un joueur pour l'inférence ML."""
    # Extractions
    ixg_l10 = float(p_form.get('L10_ixG_G', 0))
    hdcf_l10 = float(p_form.get('L10_iHDCF_G', 0))
    sog_l10 = float(p_form.get('L10_SOG_G', 0))
    atoi_l10 = float(p_form.get('ATOI', 0))
    
    season_g = float(v5_p.get('G_GP', 0)) if v5_p else 0.0
    season_a = float(v5_p.get('A_GP', 0)) if v5_p else 0.0
    season_pts = float(v5_p.get('Pts_GP', 0)) if v5_p else 0.0
    
    ga_g = float(adv_stats.get('GA_G', 0)) if adv_stats else 0.0
    hdca_g = float(adv_stats.get('HDCA_G', 0)) if adv_stats else 0.0
    
    # Interactions
    ixg_x_hdcf = ixg_l10 * hdcf_l10
    sog_x_atoi = sog_l10 * atoi_l10
    ixg_x_ga = ixg_l10 * ga_g
    
    # Mapper toutes les features vers un dictionnaire
    feat_dict = {
        'ixg_l10': ixg_l10,
        'hdcf_l10': hdcf_l10,
        'sog_l10': sog_l10,
        'atoi_l10': atoi_l10,
        'season_g': season_g,
        'season_a': season_a,
        'season_pts': season_pts,
        'ga_g': ga_g,
        'hdca_g': hdca_g,
        'pp1': 1 if pp1 else 0,
        'is_home': 1 if is_home else 0,
        'is_b2b': 1 if b2b else 0,
        'opp_is_b2b': 1 if opp_b2b else 0,
        'consec_goals': float(consec_goals),
        'ixg_x_hdcf': ixg_x_hdcf,
        'sog_x_atoi': sog_x_atoi,
        'ixg_x_ga': ixg_x_ga
    }
    
    # Construire le vecteur exact dans l'ordre du modèle
    return np.array([[feat_dict.get(f, 0.0) for f in features_list]])


def evaluate_player_markets(
    player: str,
    p_form: Dict[str, Any],
    v5_p: Dict[str, Any],
    adv_stats: Dict[str, Any],
    is_home: bool,
) -> Tuple[Optional[str], Optional[str]]:
    """Évalue un joueur contre les filtres de base des marchés (Buteur et Passeur).
    Les pointeurs sont désactivés pour ROI négatif.

    Args:
        player: Nom du joueur.
        p_form: Stats récentes (last 10 games).
        v5_p: Stats saison complète.
        adv_stats: Stats de l'équipe adverse.
        is_home: True si le joueur joue à domicile.

    Returns:
        Tuple (cat_but, cat_ast) — chaque valeur est le nom de la
        catégorie ("BUTEUR", "PASSEUR") ou None si non qualifié.
    """
    # Extractions de métriques
    season_g = float(v5_p.get('G_GP', 0)) if v5_p else 0.0
    l10_sog = float(p_form.get('L10_SOG_G', 0))
    l10_hdcf = float(p_form.get('L10_iHDCF_G', 0))

    season_a = float(v5_p.get('A_GP', 0)) if v5_p else 0.0
    opp_ga = float(adv_stats.get('GA_G', 0)) if adv_stats else 0.0
    l10_a = float(p_form.get('L10_A_G', 0))
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

    return cat_but, cat_ast
