"""
mlb/core/market_filter.py — Moteur de filtrage des paris MLB.
"""

import os
import logging
from typing import Dict, Any, Optional
import pandas as pd
import joblib

logger = logging.getLogger("MLB-Filter")

# Chemin vers le modèle
MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "mlb", "models", "xg_model_strikeouts.pkl")

# On charge le modèle en mémoire une seule fois au démarrage
_xgb_model = None
if os.path.exists(MODEL_PATH):
    try:
        _xgb_model = joblib.load(MODEL_PATH)
    except Exception as e:
        logger.error(f"Impossible de charger le modèle XGBoost : {e}")

def evaluate_pitcher_strikeouts(pitcher_name: str, pitcher_stats: Dict[str, Any], adv_k_rate: float, is_home: bool = True) -> Optional[Dict[str, Any]]:
    """
    Évalue les Strikeouts attendus d'un lanceur en utilisant le modèle XGBoost.
    
    Args:
        pitcher_name: Nom du lanceur.
        pitcher_stats: Stats historiques (k_per_9, etc.).
        adv_k_rate: Taux de strikeout moyen de l'équipe adverse (K/match).
        is_home: Si le lanceur joue à domicile.
        
    Returns:
        Dictionnaire avec les détails du pick si intéressant, None sinon.
    """
    if not _xgb_model or not pitcher_stats:
        return None
        
    # Les 3 features requises par notre modèle: ['is_home', 'L5_K9', 'Opp_L10_K']
    k9 = pitcher_stats.get("k_per_9", 0)
    
    # Création du DataFrame pour la prédiction
    features = pd.DataFrame([{
        'is_home': int(is_home),
        'L5_K9': k9,
        'Opp_L10_K': adv_k_rate
    }])
    
    try:
        # Prédiction du nombre exact de Strikeouts
        predicted_k = float(_xgb_model.predict(features)[0])
        
        # Règle : on ne présélectionne que les lanceurs où l'IA prédit au moins 5.5 Strikeouts
        # pour éviter de scraper les cotes de lanceurs médiocres
        if predicted_k >= 5.5:
            return {
                "Joueur": pitcher_name,
                "Marche": "STRIKEOUTS",
                "Confiance": "ELEVEE",
                "Moyenne_K": pitcher_stats.get("avg_k", 0),
                "Predicted_K": predicted_k
            }
    except Exception as e:
        logger.error(f"Erreur lors de la prédiction pour {pitcher_name} : {e}")
        
    return None
