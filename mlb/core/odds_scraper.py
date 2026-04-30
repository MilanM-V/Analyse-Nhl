"""
mlb/core/odds_scraper.py — Récupération des cotes MLB via The Odds API.
"""

import os
import logging
import aiohttp
import asyncio
from typing import Dict, List, Any

logger = logging.getLogger("MLB-Odds")

async def fetch_mlb_odds(players_to_fetch: Dict[str, str]) -> Dict[str, Dict[str, float]]:
    """
    Récupère les cotes MLB pour les Strikeouts (Pitcher) et Home Runs/Hits (Batter).
    
    Args:
        players_to_fetch: Dictionnaire {nom_joueur: nom_equipe}.
        
    Returns:
        Dictionnaire des cotes: { "Gerrit Cole": {"STRIKEOUTS": 1.85}, ... }
    """
    api_key = os.getenv("api_odds")
    if not api_key:
        logger.error("Clé API 'api_odds' manquante.")
        return {}

    sport = "baseball_mlb"
    regions = "us,eu"  # US et EU pour avoir les autres bookmakers en backup
    # pitcher_strikeouts, batter_home_runs, batter_hits
    markets = "pitcher_strikeouts,batter_home_runs,batter_hits"
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={api_key}&regions={regions}&markets={markets}&oddsFormat=decimal"

    # On va stocker les lignes trouvées pour chaque joueur/cat: { "Gerrit Cole": { "STRIKEOUTS": {"price": 1.85, "point": 6.5} } }
    odds_map: Dict[str, Dict[str, Any]] = {p: {} for p in players_to_fetch}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    logger.error(f"Erreur Odds API MLB: {response.status}")
                    return odds_map
                    
                data = await response.json()
                
                for event in data:
                    home_team = event.get("home_team", "")
                    away_team = event.get("away_team", "")
                    
                    # On va stocker temporairement toutes les cotes trouvées pour ce match
                    # Structure: { player: { cat: { "winamax": {"price": p, "point": p}, "best_other": {"price": p, "point": p} } } }
                    match_odds = {p: {} for p in relevant_players}
                    
                    for bookmaker in event.get("bookmakers", []):
                        bookmaker_key = bookmaker.get("key")
                        
                        for market in bookmaker.get("markets", []):
                            market_key = market.get("key")
                            
                            for outcome in market.get("outcomes", []):
                                player_name = outcome.get("description", "")
                                if not player_name:
                                    continue
                                    
                                matched_player = None
                                for rp in relevant_players:
                                    if rp.lower() in player_name.lower() or player_name.lower() in rp.lower():
                                        matched_player = rp
                                        break
                                        
                                if not matched_player:
                                    continue
                                    
                                outcome_name = outcome.get("name", "").lower()
                                if outcome_name not in ["over", "yes"]:
                                    continue
                                    
                                price = float(outcome.get("price", 0))
                                point = outcome.get("point") # ex: 6.5
                                
                                if market_key == "pitcher_strikeouts":
                                    cat = "STRIKEOUTS"
                                elif market_key == "batter_home_runs":
                                    cat = "HOME_RUNS"
                                elif market_key == "batter_hits":
                                    cat = "HITS"
                                else:
                                    continue
                                    
                                if cat not in match_odds[matched_player]:
                                    match_odds[matched_player][cat] = {"winamax": None, "best_other": None}
                                    
                                if bookmaker_key == "winamax":
                                    current_w = match_odds[matched_player][cat]["winamax"]
                                    if current_w is None or abs(price - 1.90) < abs(current_w["price"] - 1.90):
                                        match_odds[matched_player][cat]["winamax"] = {"price": price, "point": point}
                                else:
                                    current_b = match_odds[matched_player][cat]["best_other"]
                                    if current_b is None or price > current_b["price"]:
                                        match_odds[matched_player][cat]["best_other"] = {"price": price, "point": point}

                    # Mise à jour de odds_map global avec priorité Winamax
                    for player, cats in match_odds.items():
                        for cat, data in cats.items():
                            if data["winamax"] is not None:
                                chosen = data["winamax"]
                                bookie = "winamax"
                            elif data["best_other"] is not None:
                                chosen = data["best_other"]
                                bookie = "other"
                            else:
                                continue
                                
                            current_global = odds_map[player].get(cat)
                            # Si on n'a pas de cote globale, ou si on trouve une meilleure ligne
                            # Note : Si on a déjà winamax, on le garde.
                            if current_global is None:
                                odds_map[player][cat] = {"price": chosen["price"], "point": chosen["point"], "bookie": bookie}
                            elif current_global["bookie"] == "other" and bookie == "winamax":
                                # On remplace la meilleure cote par Winamax si on le trouve dans un autre match (rare)
                                odds_map[player][cat] = {"price": chosen["price"], "point": chosen["point"], "bookie": bookie}
                            elif current_global["bookie"] == bookie and bookie == "other":
                                # Si c'est "other", on garde la meilleure cote absolue
                                if chosen["price"] > current_global["price"]:
                                    odds_map[player][cat] = {"price": chosen["price"], "point": chosen["point"], "bookie": bookie}

        final_odds = {p: {} for p in players_to_fetch}
        for player, cats in odds_map.items():
            for cat, data in cats.items():
                final_odds[player][cat] = data["price"]
                if data["point"]:
                    logger.info(f"⚾ Ligne retenue pour {player} ({cat}) : Over {data['point']} @ {data['price']} (via {data['bookie']})")
                    
        return final_odds
    except Exception as e:
        logger.error(f"Exception lors du scraping des cotes MLB: {e}")
        return odds_map
