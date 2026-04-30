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
        
    # Les features requises par notre modèle V2:
    # ['is_home', 'L5_K9', 'Opp_L10_K', 'L5_Velo', 'L5_SwStr', 'Umpire_K_Factor']
    k9 = pitcher_stats.get("k_per_9", 0)
    
    # Création du DataFrame pour la prédiction (V2 features avec fallback)
    features = pd.DataFrame([{
        'is_home': int(is_home),
        'L5_K9': k9,
        'Opp_L10_K': adv_k_rate,
        'L5_Velo': pitcher_stats.get("avg_velo", 93.0),       # Fallback: vélocité moyenne MLB
        'L5_SwStr': pitcher_stats.get("swstr_pct", 0.11),     # Fallback: SwStr% moyen MLB (~11%)
        'Umpire_K_Factor': pitcher_stats.get("umpire_k_factor", 1.0),  # Fallback: arbitre neutre
    }])
    
    # Si le modèle n'a que 3 features (V1), on ne passe que celles-là
    try:
        expected_features = _xgb_model.get_booster().feature_names
        if expected_features:
            features = features[[f for f in expected_features if f in features.columns]]
    except Exception:
        pass  # Si on ne peut pas lire les features du modèle, on envoie tout
    
    try:
        # Prédiction du nombre exact de Strikeouts
        predicted_k = float(_xgb_model.predict(features)[0])
        
        # Règle : on ne présélectionne que les lanceurs où l'IA prédit au moins 5.5 Strikeouts
        # pour éviter de scraper les cotes de lanceurs médiocres
        if predicted_k >= 5.5:
            # Estimation de la probabilité que le lanceur dépasse la ligne Over 5.5 K
            # On utilise une fonction logistique centrée sur 5.5 avec un spread calibré
            # Plus predicted_k est élevé au-dessus de 5.5, plus la proba est forte
            import math
            line = 5.5
            spread = 1.2  # Calibré pour que +2K au-dessus de la ligne ≈ 85% de proba
            prob_over = 1.0 / (1.0 + math.exp(-(predicted_k - line) / spread))
            
            # Niveau de confiance
            if prob_over >= 0.70:
                confiance = "ELITE"
            elif prob_over >= 0.55:
                confiance = "ELEVEE"
            else:
                confiance = "STANDARD"
            
            return {
                "Joueur": pitcher_name,
                "Marche": "STRIKEOUTS",
                "Confiance": confiance,
                "Moyenne_K": pitcher_stats.get("avg_k", 0),
                "Predicted_K": predicted_k,
                "Proba": round(prob_over, 4),
            }
    except Exception as e:
        logger.error(f"Erreur lors de la prédiction pour {pitcher_name} : {e}")
        
    return None
