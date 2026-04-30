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

async def fetch_multiple_odds(players_to_teams: Dict[str, str], telegram=None) -> Dict[str, Dict]:
    """
    Point d'entrée chirurgical avec surveillance de quota.
    """
    if not API_KEY:
        return {name: {"player": name, "BUTS": None, "ASSISTS": None, "POINTS": None} for name in players_to_teams}

    if not players_to_teams:
        return {}

    # 1. Récupérer les événements (1 crédit)
    url_events = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events?apiKey={API_KEY}"
    try:
        r = requests.get(url_events, timeout=10)
        
        # Vérification Quota
        remaining = r.headers.get('x-requests-remaining')
        if remaining and int(remaining) < 20 and telegram:
            telegram.send_message(f"⚠️ <b>ALERTE QUOTA ODDS API</b> ⚠️\nIl ne vous reste que <b>{remaining}</b> crédits sur votre quota gratuit de 500.")
            
        if r.status_code == 429 or r.status_code == 403:
            logger.error("[Odds API] QUOTA ÉPUISÉ !")
            if telegram:
                telegram.send_message("🚨 <b>QUOTA ODDS API ÉPUISÉ</b> 🚨\nLe bot ne peut plus récupérer de cotes pour ce mois-ci.")
            return {name: {"player": name, "BUTS": None, "ASSISTS": None, "POINTS": None} for name in players_to_teams}

        if r.status_code != 200:
            return {name: {"player": name, "BUTS": None, "ASSISTS": None, "POINTS": None} for name in players_to_teams}
            
        events = r.json()
    except Exception as e:
        logger.error(f"[Odds API] Erreur : {e}")
        return {name: {"player": name, "BUTS": None, "ASSISTS": None, "POINTS": None} for name in players_to_teams}

    from config.constants import TEAM_FULL_TO_ABBR
    import unicodedata

    def normalize(text: str) -> str:
        return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8').lower().replace(" ", "").replace(".", "")

    target_abbrs = set(players_to_teams.values())
    target_teams_full = {normalize(t) for t in target_abbrs}
    for full_name, abbr in TEAM_FULL_TO_ABBR.items():
        if abbr in target_abbrs:
            target_teams_full.add(normalize(full_name))

    final_results = {}
    
    for event in events:
        home = normalize(event['home_team'])
        away = normalize(event['away_team'])
        
        if any(team in home or team in away or home in team or away in team for team in target_teams_full):
            logger.info(f"🎯 [Odds API] Appel chirurgical : {event['home_team']} vs {event['away_team']}")
            event_data = _fetch_event_odds(event['id'], ['player_goal_scorer_anytime', 'player_assists', 'player_points'])
            
            if event_data:
                for p_name, p_odds in event_data.items():
                    p_odds['player'] = p_name
                    final_results[p_name] = p_odds

    results = {}
    for name in players_to_teams:
        results[name] = final_results.get(name, {"player": name, "BUTS": None, "ASSISTS": None, "POINTS": None})
            
    return results

# Fonctions legacy pour compatibilité
def normalize_name_for_url(name: str) -> str:
    return name.lower().replace(" ", "-")

async def fetch_player_odds(session, player_name: str) -> dict:
    all_odds = await fetch_multiple_odds([player_name])
    return all_odds.get(player_name, {"player": player_name, "BUTS": None, "ASSISTS": None, "POINTS": None})
