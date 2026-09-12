"""
core/parlay_engine.py — Moteur de Génération de Paris Combinés Synergiques (NHL).

Développé par le Senior Quantitative Data Scientist :
1. Combiné Synergique Same-Game (Passeur + Buteur sur la même ligne ou PP1) :
   - Exploite la sous-évaluation par les bookmakers de la corrélation positive
     entre le playmaker et le finisseur.
2. Combiné Dual-Assists Inter-Matchs (Deux passeurs d'élite sur des matchs distincts) :
   - Exploite l'Edge cumulé sur les événements indépendants à fort win rate (>50%).
"""
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger("NHL.ParlayEngine")


def generate_correlated_parlays(
    picks_but: List[Dict[str, Any]], 
    picks_ast: List[Dict[str, Any]],
    min_combined_ev: float = 0.15,
    max_stake: float = 1.0
) -> List[Dict[str, Any]]:
    """Génère les combinés synergiques Same-Game (Passeur + Buteur d'une même équipe/PP1).
    
    Args:
        picks_but: Liste des picks buteurs validés avec cotes.
        picks_ast: Liste des picks passeurs validés avec cotes.
        min_combined_ev: Expected Value combinée minimale requise (15%).
        max_stake: Mise maximale conseillée en unités (0.5 à 1.0 U).
        
    Returns:
        Liste de dictionnaires représentant les combinés synergiques.
    """
    parlays = []
    
    # 1. Recherche de couples Passeur + Buteur dans la même équipe
    for p_ast in picks_ast:
        team = p_ast.get("Equipe")
        c_ast = p_ast.get("Cote")
        prob_ast = p_ast.get("Proba", 0.0)
        
        if not c_ast or c_ast <= 1.20 or prob_ast <= 0.20:
            continue
            
        for p_but in picks_but:
            if p_but.get("Equipe") != team or p_but.get("Joueur") == p_ast.get("Joueur"):
                continue
                
            c_but = p_but.get("Cote")
            prob_but = p_but.get("Proba", 0.0)
            
            if not c_but or c_but <= 1.50 or prob_but <= 0.15:
                continue
                
            # Facteur de corrélation synergique PP1 / Linemate
            # Si les deux joueurs sont sur le PP1, le facteur de boost de probabilité conjointe est de +30%
            is_joint_pp1 = (p_ast.get("PP1") in ("⭐", "PP1", True) and p_but.get("PP1") in ("⭐", "PP1", True))
            corr_factor = 1.30 if is_joint_pp1 else 1.15
            
            # Probabilité conjointe modélisée
            joint_prob = min(prob_ast, prob_but) * 0.40 + (prob_ast * prob_but) * 0.60 * corr_factor
            
            # Cote combinée estimée (MyMatch / Same-Game Parlay)
            combined_odds = round(c_ast * c_but * 0.90, 2)  # 10% de décote MyMatch appliquée par le bookmaker
            combined_ev = (joint_prob * combined_odds) - 1.0
            
            if combined_ev >= min_combined_ev:
                parlays.append({
                    "type": "SAME_GAME_SYNERGY",
                    "equipe": team,
                    "leg1_joueur": p_ast["Joueur"],
                    "leg1_marche": "PASSEUR",
                    "leg1_cote": c_ast,
                    "leg2_joueur": p_but["Joueur"],
                    "leg2_marche": "BUTEUR",
                    "leg2_cote": c_but,
                    "cote_totale": combined_odds,
                    "proba_jointe": round(joint_prob, 3),
                    "ev": round(combined_ev, 3),
                    "mise": 0.25,  # Mise fixée à 0.25U pour les paris Fun/Combinés (Phase 4)
                    "note": f"Synergie {'PP1' if is_joint_pp1 else 'Ligne 5v5'}"
                })
                
    return parlays


def generate_dual_assist_parlays(
    picks_ast: List[Dict[str, Any]],
    min_combined_ev: float = 0.15,
    max_stake: float = 1.0
) -> List[Dict[str, Any]]:
    """Génère les combinés sécurisés Dual-Assists Inter-Matchs (2 passeurs sur des matchs différents).
    
    Args:
        picks_ast: Liste des picks passeurs validés avec cotes.
        min_combined_ev: Expected Value combinée minimale (15%).
        max_stake: Mise maximale conseillée en unités.
        
    Returns:
        Liste de combinés inter-matchs.
    """
    parlays = []
    
    # Trier les passeurs par EV décroissante
    sorted_ast = sorted(
        [p for p in picks_ast if p.get("Cote") and p.get("Proba", 0) > 0.35],
        key=lambda x: (x["Proba"] * x["Cote"] - 1.0),
        reverse=True
    )
    
    if len(sorted_ast) < 2:
        return []
        
    # Former le meilleur duo de matchs différents
    p1 = sorted_ast[0]
    for p2 in sorted_ast[1:]:
        if p1.get("Equipe") == p2.get("Equipe") or p1.get("Adversaire") == p2.get("Equipe"):
            continue  # Matchs différents
            
        prob_joint = p1["Proba"] * p2["Proba"]
        combined_odds = round(p1["Cote"] * p2["Cote"], 2)
        combined_ev = (prob_joint * combined_odds) - 1.0
        
        if combined_ev >= min_combined_ev:
            parlays.append({
                "type": "DUAL_ASSISTS_CROSS_MATCH",
                "leg1_joueur": p1["Joueur"],
                "leg1_equipe": p1["Equipe"],
                "leg1_marche": "PASSEUR",
                "leg1_cote": p1["Cote"],
                "leg2_joueur": p2["Joueur"],
                "leg2_equipe": p2["Equipe"],
                "leg2_marche": "PASSEUR",
                "leg2_cote": p2["Cote"],
                "cote_totale": combined_odds,
                "proba_jointe": round(prob_joint, 3),
                "ev": round(combined_ev, 3),
                "mise": 0.25,  # Mise fixée à 0.25U pour les paris Fun/Combinés (Phase 4)
                "note": "Indépendance parfaite + Double Edge"
            })
            break  # On ne retient que le meilleur duo pour ne pas sur-exposer
            
    return parlays
