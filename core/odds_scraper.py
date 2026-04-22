import os
import logging
import requests
import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("NHL_Bot")

# Configuration The Odds API
API_KEY = os.getenv("api_odds")
SPORT = "icehockey_nhl"
REGION = "us" # Regions: us, uk, au, eu

# Cache global pour éviter de consommer trop de crédits
_CACHE = {
    "data": {},      # { "Player Name": {"BUTS": 2.1, ...} }
    "timestamp": 0
}
CACHE_TTL = 3600  # 1 heure

def _get_upcoming_events() -> List[Dict]:
    """Récupère la liste des matchs NHL à venir (consomme 1 crédit)."""
    if not API_KEY:
        return []
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events?apiKey={API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            now = datetime.now(timezone.utc)
            events = r.json()
            filtered = []
            for e in events:
                try:
                    start_dt = datetime.fromisoformat(e['commence_time'].replace('Z', '+00:00'))
                    # On ne garde que les matchs qui commencent bientôt (prochaines 18h)
                    if (start_dt - now).total_seconds() < 18 * 3600:
                        filtered.append(e)
                except Exception:
                    filtered.append(e)
            return filtered
    except Exception as e:
        logger.error(f"[Odds API] Erreur récupération événements: {e}")
    return []

def _fetch_event_odds(event_id: str, markets: List[str]) -> Dict:
    """Récupère les cotes pour un événement et des marchés précis (consomme 1 crédit par marché)."""
    if not API_KEY:
        return {}
    
    market_str = ",".join(markets)
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{event_id}/odds?apiKey={API_KEY}&regions={REGION}&markets={market_str}&oddsFormat=decimal"
    
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return {}
        
        data = r.json()
        event_odds = {}
        
        for book in data.get('bookmakers', []):
            for market in book.get('markets', []):
                m_key = market['key']
                for outcome in market.get('outcomes', []):
                    p_name = outcome['description']
                    price = outcome['price']
                    
                    if p_name not in event_odds:
                        event_odds[p_name] = {"BUTS": None, "ASSISTS": None, "POINTS": None}
                    
                    if m_key == 'player_goal_scorer_anytime':
                        if event_odds[p_name]["BUTS"] is None or price > event_odds[p_name]["BUTS"]:
                            event_odds[p_name]["BUTS"] = price
                    elif m_key == 'player_assists':
                        if outcome.get('name') == 'Over' and outcome.get('point') == 0.5:
                            if event_odds[p_name]["ASSISTS"] is None or price > event_odds[p_name]["ASSISTS"]:
                                event_odds[p_name]["ASSISTS"] = price
                    elif m_key == 'player_points':
                        if outcome.get('name') == 'Over' and outcome.get('point') == 0.5:
                            if event_odds[p_name]["POINTS"] is None or price > event_odds[p_name]["POINTS"]:
                                event_odds[p_name]["POINTS"] = price
        return event_odds
    except Exception:
        return {}

async def fetch_multiple_odds(player_names: List[str]) -> Dict[str, Dict]:
    """
    Point d'entrée optimisé.
    On ne scanne que les matchs des joueurs demandés qui commencent bientôt.
    """
    if not API_KEY:
        logger.warning("[Odds API] Aucune clé API trouvée dans le .env. Passage de l'étape des cotes.")
        return {name: {"player": name, "BUTS": None, "ASSISTS": None, "POINTS": None} for name in player_names}

    if not player_names:
        return {}

    global _CACHE
    now = time.time()

    # Si le cache est récent, on l'utilise
    if _CACHE["data"] and (now - _CACHE["timestamp"] < CACHE_TTL):
        logger.info("[Odds API] Utilisation du cache des cotes.")
        return {name: _CACHE["data"].get(name, {"player": name, "BUTS": None, "ASSISTS": None, "POINTS": None}) for name in player_names}

    # 1. Récupérer les événements du jour (1 crédit)
    events = _get_upcoming_events()
    if not events:
        return {name: {"player": name, "BUTS": None, "ASSISTS": None, "POINTS": None} for name in player_names}

    new_data = {}
    
    # 2. On scanne les événements trouvés
    for event in events:
        event_id = event['id']
        # On récupère les 3 marchés pour ce match (3 crédits)
        # Note: On pourrait affiner pour ne prendre que les marchés utiles au match
        active_markets = ['player_goal_scorer_anytime', 'player_assists', 'player_points']
        
        logger.info(f"[Odds API] Scan chirurgical : {event['home_team']} vs {event['away_team']}...")
        event_data = _fetch_event_odds(event_id, active_markets)
        
        if event_data:
            for p_name, p_odds in event_data.items():
                p_odds['player'] = p_name
                new_data[p_name] = p_odds

    # Mise à jour du cache
    _CACHE["data"] = new_data
    _CACHE["timestamp"] = now

    # Retourner les résultats pour les joueurs demandés
    results = {}
    for name in player_names:
        if name in new_data:
            results[name] = new_data[name]
        else:
            results[name] = {"player": name, "BUTS": None, "ASSISTS": None, "POINTS": None}
            
    return results

# Fonctions legacy pour compatibilité
def normalize_name_for_url(name: str) -> str:
    return name.lower().replace(" ", "-")

async def fetch_player_odds(session, player_name: str) -> dict:
    all_odds = await fetch_multiple_odds([player_name])
    return all_odds.get(player_name, {"player": player_name, "BUTS": None, "ASSISTS": None, "POINTS": None})
