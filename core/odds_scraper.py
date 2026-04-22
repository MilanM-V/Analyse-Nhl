import os
import logging
import requests
import asyncio
import time
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("NHL_Bot")

# Configuration The Odds API
API_KEY = os.getenv("api_odds")
SPORT = "icehockey_nhl"
REGION = "us" # Regions: us, uk, au, eu
MARKETS = "player_goal_scorer_anytime,player_assists,player_points"

# Cache global pour éviter de consommer trop de crédits
_CACHE = {
    "data": {},      # { "Player Name": {"BUTS": 2.1, ...} }
    "timestamp": 0
}
CACHE_TTL = 3600  # 1 heure

def _fetch_all_nhl_odds() -> Dict[str, Dict]:
    """Récupère toutes les cotes de la journée via The Odds API."""
    if not API_KEY:
        logger.error("[Odds API] Clé API 'api_odds' manquante dans le .env")
        return {}

    # 1. Récupérer les événements (matchs) du jour
    events_url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events?apiKey={API_KEY}"
    try:
        r = requests.get(events_url, timeout=10)
        if r.status_code != 200:
            logger.error(f"[Odds API] Erreur récupération événements: {r.status_code}")
            return {}
        events = r.json()
    except Exception as e:
        logger.error(f"[Odds API] Exception événements: {e}")
        return {}

    global_odds = {}

    # 2. Pour chaque match, récupérer les props
    for event in events:
        event_id = event['id']
        logger.info(f"[Odds API] Récupération des cotes pour {event['home_team']} vs {event['away_team']}...")
        
        props_url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{event_id}/odds?apiKey={API_KEY}&regions={REGION}&markets={MARKETS}&oddsFormat=decimal"
        try:
            r = requests.get(props_url, timeout=10)
            if r.status_code != 200:
                logger.error(f"[Odds API] Erreur props pour {event_id}: {r.status_code}")
                continue
            data = r.json()
            
            # 3. Parser les bookmakers
            # On prend le premier bookmaker qui a des données pour simplifier (Consensus ou leader)
            for book in data.get('bookmakers', []):
                for market in book.get('markets', []):
                    market_key = market['key']
                    for outcome in market.get('outcomes', []):
                        player_name = outcome['description']
                        price = outcome['price']
                        
                        if player_name not in global_odds:
                            global_odds[player_name] = {"BUTS": None, "ASSISTS": None, "POINTS": None}
                        
                        if market_key == 'player_goal_scorer_anytime':
                            # On garde la meilleure cote si déjà présente
                            if global_odds[player_name]["BUTS"] is None or price > global_odds[player_name]["BUTS"]:
                                global_odds[player_name]["BUTS"] = price
                        elif market_key == 'player_assists':
                            if outcome.get('name') == 'Over' and outcome.get('point') == 0.5:
                                if global_odds[player_name]["ASSISTS"] is None or price > global_odds[player_name]["ASSISTS"]:
                                    global_odds[player_name]["ASSISTS"] = price
                        elif market_key == 'player_points':
                            if outcome.get('name') == 'Over' and outcome.get('point') == 0.5:
                                if global_odds[player_name]["POINTS"] is None or price > global_odds[player_name]["POINTS"]:
                                    global_odds[player_name]["POINTS"] = price
                                    
        except Exception as e:
            logger.error(f"[Odds API] Exception props pour {event_id}: {e}")
            continue
            
    return global_odds

async def fetch_multiple_odds(player_names: List[str]) -> Dict[str, Dict]:
    """
    Point d'entrée compatible avec l'ancien scraper.
    Récupère ou utilise le cache pour retourner les cotes demandées.
    """
    global _CACHE
    now = time.time()
    
    # Rafraîchir le cache si nécessaire
    if not _CACHE["data"] or (now - _CACHE["timestamp"] > CACHE_TTL):
        logger.info("[Odds API] Rafraîchissement du cache des cotes...")
        _CACHE["data"] = _fetch_all_nhl_odds()
        _CACHE["timestamp"] = now
    else:
        logger.info("[Odds API] Utilisation du cache (TTL restants: %ds)", int(CACHE_TTL - (now - _CACHE["timestamp"])))

    # Filtrer pour les joueurs demandés
    results = {}
    for name in player_names:
        if name in _CACHE["data"]:
            results[name] = _CACHE["data"][name]
            results[name]['player'] = name # Compatibilité
        else:
            # On essaye une recherche floue si besoin ? (Optionnel)
            results[name] = {"player": name, "BUTS": None, "ASSISTS": None, "POINTS": None}
            
    return results

# Fonctions legacy pour compatibilité si appelées directement
def normalize_name_for_url(name: str) -> str:
    return name.lower().replace(" ", "-")

async def fetch_player_odds(session, player_name: str) -> dict:
    # Cette fonction n'est plus utilisée individuellement avec l'API
    # mais on la garde pour éviter des erreurs d'import
    all_odds = await fetch_multiple_odds([player_name])
    return all_odds.get(player_name, {"player": player_name, "BUTS": None, "ASSISTS": None, "POINTS": None})
