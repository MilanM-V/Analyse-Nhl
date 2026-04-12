"""
data/cache.py — Fonctions de gestion de cache (JSON)
"""

import os
import json
import time
import logging

logger = logging.getLogger("NHL_Bot")

FOLDER_NAME = "stats"
CACHE_DIR = os.path.join(FOLDER_NAME, "cache")

os.makedirs(CACHE_DIR, exist_ok=True)


async def get_pbp(session, game_id, api_get_func):
    """Télécharge ou charge depuis le cache le Play-By-Play d'un match."""
    cache_path = os.path.join(CACHE_DIR, f"pbp_cache_{game_id}.json")
    
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)
            
    from config.settings import cfg
    url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
    data = await api_get_func(session, url)
    if data:
        with open(cache_path, 'w') as f:
            json.dump(data, f)
    return data

async def get_toi_from_boxscore(session, game_id, api_get_func):
    """Télécharge ou charge depuis le cache le boxscore pour extraire le TOI."""
    cache_path = os.path.join(CACHE_DIR, f"box_cache_{game_id}.json")
    
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            data = json.load(f)
    else:
        url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"
        data = await api_get_func(session, url)
        if data:
            with open(cache_path, 'w') as f:
                json.dump(data, f)

    if not data: return {}

    toi_dict = {}
    def parse_toi(toi_str):
        try:
            m, s = map(int, toi_str.split(':'))
            return m * 60 + s
        except:
            return 0

    for side in ('homeTeam', 'awayTeam'):
        team_abbr = data.get(side, {}).get('abbrev', '')
        team_data = data.get('playerByGameStats', {}).get(side, {})
        for group in ('forwards', 'defense', 'goalies'):
            for p in team_data.get(group, []):
                pid = p.get('playerId')
                if pid:
                    toi_dict[pid] = {'toi': parse_toi(p.get('toi', '0:00')), 'team': team_abbr}
    return toi_dict

def cleanup_pbp_cache():
    """Supprime les fichiers cache vieux de plus de 48h."""
    now = time.time()
    count = 0
    if not os.path.exists(CACHE_DIR): return
    for f in os.listdir(CACHE_DIR):
        if (f.startswith('pbp_cache_') or f.startswith('box_cache_')) and f.endswith('.json'):
            fpath = os.path.join(CACHE_DIR, f)
            if now - os.path.getmtime(fpath) > 2 * 86400:
                os.remove(fpath)
                count += 1
    if count: logger.info(f"  Cache PBP: {count} fichiers supprimés")
