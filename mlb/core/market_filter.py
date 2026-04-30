"""
mlb/core/market_filter.py — Moteur de filtrage des paris MLB.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger("MLB-Filter")

def evaluate_pitcher_strikeouts(pitcher_name: str, pitcher_stats: Dict[str, Any], adv_k_rate: float) -> Optional[Dict[str, Any]]:
    """
    Évalue si un pari OVER Strikeouts est rentable pour ce lanceur.
    
    Args:
        pitcher_name: Nom du lanceur.
        pitcher_stats: Stats historiques (k_per_9, avg_k).
        adv_k_rate: Taux de strikeout moyen de l'équipe adverse.
        
    Returns:
        Dictionnaire avec les détails du pick si intéressant, None sinon.
    """
    if not pitcher_stats:
        return None
        
    avg_k = pitcher_stats.get("avg_k", 0)
    k9 = pitcher_stats.get("k_per_9", 0)
    
    # Règle basique V1 : Si le lanceur a un K/9 > 9.0 ET l'adversaire prend > 8.5 K par match
    if k9 > 9.0 and adv_k_rate > 8.5:
        logger.info(f"⚾ [PICK K] {pitcher_name} : K/9={k9:.1f} vs ADV_K={adv_k_rate:.1f}")
        return {
            "Joueur": pitcher_name,
            "Marche": "STRIKEOUTS",
            "Confiance": "ELEVEE",
            "Moyenne_K": avg_k
        }
        
    return None
