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

from nhl.config.settings import cfg

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
                                features_list: list, cote: float = None,
                                goalie_sv_pct: float = None, player_name: str = "",
                                priors_data: Dict[str, Any] = None) -> np.ndarray:
    """Prépare le vecteur de features pour un joueur pour l'inférence ML.

    Args:
        p_form: Stats récentes (last 10 games).
        v5_p: Stats saison complète.
        adv_stats: Stats de l'équipe adverse.
        is_home: True si le joueur joue à domicile.
        b2b: True si l'équipe joue un back-to-back.
        opp_b2b: True si l'adversaire joue un back-to-back.
        pp1: True si le joueur est sur le PP1.
        consec_goals: Nombre de matchs consécutifs avec but.
        features_list: Liste ordonnée des features pour le modèle.
        cote: Cote décimale du bookmaker (optionnel, pour implied_prob).
        goalie_sv_pct: Save % du gardien adverse (optionnel, ex: 0.915).
        player_name: Nom du joueur pour chercher ses priors.
        priors_data: Dictionnaire des priors chargé depuis priors_cache.json.

    Returns:
        np.ndarray de shape (1, n_features) prêt pour predict_proba.
    """
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
    
    # Priors
    if not priors_data:
        priors_data = {"defaults": {"prior_g60": 0.55, "prior_a60": 0.94, "prior_sog60": 5.0, "prior_sh_pct": 0.095}, "players": {}}
    defs = priors_data.get("defaults", {})
    p_priors = priors_data.get("players", {}).get(player_name, {})
    
    prior_g60 = p_priors.get('prior_g60', defs.get('prior_g60', 0.55))
    prior_a60 = p_priors.get('prior_a60', defs.get('prior_a60', 0.94))
    prior_sog60 = p_priors.get('prior_sog60', defs.get('prior_sog60', 5.0))
    prior_sh_pct = p_priors.get('prior_sh_pct', defs.get('prior_sh_pct', 0.095))

    opp_xga_60 = float(adv_stats.get('xGA_60', 2.8)) # Ou utiliser GA_G comme proxy
    opp_hdca_60 = float(adv_stats.get('HDCA_G', 0.85))
    ixg_x_opp_xga = ixg_l10 * (opp_xga_60 / 2.8)
    
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
        'ixg_x_ga': ixg_x_ga,
        'prior_g60': prior_g60,
        'prior_a60': prior_a60,
        'prior_sog60': prior_sog60,
        'prior_sh_pct': prior_sh_pct,
        'opp_xga_60': opp_xga_60,
        'opp_hdca_60': opp_hdca_60,
        'opp_goalie_gsax_60': 0.0, # Simplification pour le live
        'team_xg_60': 2.8,
        'ixg_x_opp_xga': ixg_x_opp_xga,
        # === NOUVELLES FEATURES (P5) ===
        # Cote implicite du marché : feature #1 en paris sportifs.
        # Capture l'opinion agrégée de milliers de parieurs/modèles.
        'implied_prob': (1.0 / cote) if (cote and cote > 1.05) else 0.0,
        # Gardien adverse : faiblesse = 1 - SV%.
        # Plus le gardien est faible, plus la valeur est élevée.
        'goalie_weakness': (
            (1.0 - goalie_sv_pct)
            if (goalie_sv_pct and goalie_sv_pct > 0)
            else 0.08  # Default league average (1 - 0.920)
        ),
        # === NOUVELLES FEATURES (P10 — Synergies de Trios & On-Ice) ===
        'is_top6': 1.0 if (atoi_l10 >= 17.0 or pp1) else 0.0,
        'linemate_synergy': (season_g + season_a) * (1.0 if pp1 else 0.0),
        'team_scoring_env': ga_g * hdca_g,
    }
    
    # Construire le vecteur exact dans l'ordre du modèle
    return np.array([[feat_dict.get(f, 0.0) for f in features_list]])


def get_adaptive_ev_threshold(cote: float, default_ev: float = 0.05) -> float:
    """Calcule le seuil EV adaptatif selon la cote décimale (P9).

    - Cote basse (< 2.00) : Seuil 8% (contrer le vig élevé et marge de bruit)
    - Cote médiane (2.00 - 3.50) : Seuil 5% (zone de compromis optimale)
    - Cote haute (> 3.50) : Seuil 10% (contrer le long-shot bias et forte variance)
    """
    if not cote or cote <= 1.05:
        return default_ev
    if cote < 2.00:
        return 0.08
    elif cote <= 3.50:
        return 0.05
    else:
        return 0.10


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

    # Mode Playoff / Modern Scanning : On ouvre l'évaluation à tout le Top 9 actif (ATOI >= 13.5 min ou PP1)
    is_playoff = (cfg.api.mode == "playoff")
    is_top9 = (p_atoi >= 13.5)

    # Buteurs : Attaquants actifs (Défenseurs toujours strictement exclus)
    cat_but = None
    if pos not in ('D', 'LD', 'RD') and (is_top9 or season_g >= 0.20):
        if (is_home or is_playoff or not cfg.thresholds.buteurs.home_only):
            cat_but = "BUTEUR"

    # Passeurs : Joueurs avec temps de glace significatif
    cat_ast = None
    if is_top9 or season_a >= 0.30:
        if (is_home or is_playoff or not cfg.thresholds.passeurs.home_only):
            cat_ast = "PASSEUR"

    return cat_but, cat_ast
