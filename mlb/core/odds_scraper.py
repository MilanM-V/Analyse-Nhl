"""
mlb/core/odds_scraper.py — Récupération des cotes MLB via The Odds API.
"""

import os
import logging
import aiohttp
import asyncio
from typing import Dict, List, Any

logger = logging.getLogger("MLB-Odds")

async def fetch_mlb_odds(players_to_fetch: Dict[str, str]) -> Dict[str, float]:
    """
    Récupère les cotes MLB pour les Strikeouts (Pitcher) via The Odds API.
    """
    api_key = os.getenv("api_odds")
    if not api_key:
        logger.error("Clé API 'api_odds' manquante.")
        return {}

    sport = "baseball_mlb"
    regions = "us,eu"
    markets = "pitcher_strikeouts"
    
    final_results = {}
    if not players_to_fetch:
        return {}

    try:
        # 1. Fetch tous les événements du jour
        url_events = f"https://api.the-odds-api.com/v4/sports/{sport}/events?apiKey={api_key}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url_events) as r:
                if r.status != 200:
                    logger.error(f"Erreur Odds API (events): {r.status}")
                    return {}
                events = await r.json()
                
            target_teams = set(players_to_fetch.values())
            
            for event in events:
                home = event.get('home_team', '')
                away = event.get('away_team', '')
                
                # Vérifie si le match concerne une des équipes ciblées
                if any(t in home or t in away or home in t or away in t for t in target_teams):
                    event_id = event.get('id')
                    
                    # 2. Fetch les cotes spécifiques pour ce match
                    url_odds = f"https://api.the-odds-api.com/v4/sports/{sport}/events/{event_id}/odds?apiKey={api_key}&regions={regions}&markets={markets}&oddsFormat=decimal"
                    
                    async with session.get(url_odds) as r_odds:
                        if r_odds.status != 200:
                            continue
                            
                        event_odds_data = await r_odds.json()
                        match_odds_temp = {}
                        
                        for bookmaker in event_odds_data.get("bookmakers", []):
                            book_key = bookmaker.get("key")
                            for market in bookmaker.get("markets", []):
                                if market.get("key") != "pitcher_strikeouts":
                                    continue
                                    
                                for outcome in market.get("outcomes", []):
                                    player_name = outcome.get("description", "")
                                    if outcome.get("name") != "Over":
                                        continue
                                        
                                    price = outcome.get("price")
                                    
                                    if player_name not in match_odds_temp:
                                        match_odds_temp[player_name] = {"winamax": 0.0, "best_other": 0.0}
                                        
                                    if book_key == "winamax":
                                        match_odds_temp[player_name]["winamax"] = max(match_odds_temp[player_name]["winamax"], price)
                                    else:
                                        match_odds_temp[player_name]["best_other"] = max(match_odds_temp[player_name]["best_other"], price)
                        
                        # 3. Validation et sélection (Winamax prioritaire)
                        for player_name, odds_dict in match_odds_temp.items():
                            for target_player in players_to_fetch.keys():
                                # Comparaison sur le nom de famille ou nom complet
                                if target_player.lower() in player_name.lower() or player_name.lower() in target_player.lower() or target_player.split()[-1].lower() in player_name.lower():
                                    final_price = odds_dict["winamax"] if odds_dict["winamax"] > 0 else odds_dict["best_other"]
                                    if final_price > 0:
                                        # Le format attendu par bot_logic est { "STRIKEOUTS": cote }
                                        final_results[target_player] = {"STRIKEOUTS": final_price}

        return final_results
    except Exception as e:
        logger.error(f"Exception dans fetch_mlb_odds : {e}")
        return {}
