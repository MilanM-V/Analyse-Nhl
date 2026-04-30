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
    regions = "us,eu"
    # pitcher_strikeouts, batter_home_runs, batter_hits
    markets = "pitcher_strikeouts,batter_home_runs,batter_hits"
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={api_key}&regions={regions}&markets={markets}&oddsFormat=decimal"

    odds_map: Dict[str, Dict[str, float]] = {p: {} for p in players_to_fetch}

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
                    
                    # On vérifie si ce match concerne un de nos joueurs
                    relevant_players = [
                        p for p, t in players_to_fetch.items() 
                        if t in home_team or t in away_team or home_team in t or away_team in t
                    ]
                    
                    if not relevant_players:
                        continue
                        
                    for bookmaker in event.get("bookmakers", []):
                        for market in bookmaker.get("markets", []):
                            market_key = market.get("key")
                            
                            for outcome in market.get("outcomes", []):
                                player_name = outcome.get("description", "")
                                if not player_name:
                                    continue
                                    
                                # Matcher le nom du joueur
                                matched_player = None
                                for rp in relevant_players:
                                    if rp.lower() in player_name.lower() or player_name.lower() in rp.lower():
                                        matched_player = rp
                                        break
                                        
                                if not matched_player:
                                    continue
                                    
                                # On s'intéresse uniquement aux OVER ("Over" ou "Yes")
                                outcome_name = outcome.get("name", "").lower()
                                if outcome_name not in ["over", "yes"]:
                                    continue
                                    
                                price = float(outcome.get("price", 0))
                                
                                # Assigner la cote à la bonne catégorie
                                if market_key == "pitcher_strikeouts":
                                    cat = "STRIKEOUTS"
                                elif market_key == "batter_home_runs":
                                    cat = "HOME_RUNS"
                                elif market_key == "batter_hits":
                                    cat = "HITS"
                                else:
                                    continue
                                    
                                current_best = odds_map[matched_player].get(cat, 0)
                                if price > current_best:
                                    odds_map[matched_player][cat] = price

        return odds_map
    except Exception as e:
        logger.error(f"Exception lors du scraping des cotes MLB: {e}")
        return odds_map
