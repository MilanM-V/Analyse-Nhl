"""
data/fetcher.py — Pipeline de récupération asynchrone des statistiques NHL.
"""

import os
import time
import math
import json
import logging
import asyncio
import aiohttp
import sys

# Ajout du dossier racine au sys.path pour permettre l'exécution standalone
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from collections import defaultdict
from typing import Dict, List, Any, Set

from nhl.config.settings import cfg
from nhl.config.constants import TEAM_FULL_TO_ABBR, TEAM_ABBR_TO_FULL
from nhl.data.cache import get_pbp, get_toi_from_boxscore, cleanup_pbp_cache, FOLDER_NAME

logger = logging.getLogger("NHL.Fetcher")

BASE      = "https://api.nhle.com/stats/rest/en"
BASE_WEB  = "https://api-web.nhle.com"

SEMAPHORE = None

async def api_get(session: aiohttp.ClientSession, url: str, retries: int = 5) -> Any:
    """Requête GET asynchrone avec gestion du rate limiting (HTTP 429)."""
    global SEMAPHORE
    if SEMAPHORE is None:
        SEMAPHORE = asyncio.Semaphore(cfg.api.semaphore_limit)
        
    async with SEMAPHORE:
        for i in range(retries):
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        return await r.json()
                    if r.status == 429:
                        wait = min(2 ** (i + 1), 30)
                        logger.warning(f"HTTP 429 (rate limit) — attente {wait}s avant retry {i+1}/{retries} — {url}")
                        await asyncio.sleep(wait)
                        continue
                    logger.warning(f"HTTP {r.status} — {url}")
                    await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Tentative {i+1}/{retries} échouée: {e} - {url}")
                await asyncio.sleep(2)
        return None

async def fetch_all(session: aiohttp.ClientSession, endpoint: str, exp: str = None, limit: int = 100) -> List[Dict]:
    """Récupère une ressource paginée de l'API NHL Stats."""
    exp_str = exp or f"seasonId={cfg.api.season_id} and gameTypeId={cfg.api.game_type}"
    url_base = f"{BASE}/{endpoint}?limit={limit}&cayenneExp={exp_str}"
    
    first_data = await api_get(session, f"{url_base}&start=0")
    if not first_data or not first_data.get('data'):
        return []
    
    total = first_data.get('total', 0)
    all_data = first_data['data']
    
    if total <= limit:
        return all_data
        
    tasks = []
    for start in range(limit, total, limit):
        u = f"{url_base}&start={start}"
        tasks.append(api_get(session, u))
        
    results = await asyncio.gather(*tasks)
    for res in results:
        if res and res.get('data'):
            all_data.extend(res['data'])
            
    return all_data

async def get_last_n_game_ids(session: aiohttp.ClientSession, team_abbr: str, n: int = 10) -> List[str]:
    url = f"{BASE_WEB}/v1/club-schedule-season/{team_abbr}/{cfg.api.season_id}"
    data = await api_get(session, url)
    if not data: return []
    games = data.get('games', [])
    # En mode playoff, on accepte les types 2 (Saison) et 3 (Playoffs) pour assurer la continuité des stats L10
    allowed_types = [2, 3] if cfg.api.mode == "playoff" else [2]
    finished = [g for g in games if g.get('gameState') == 'OFF' and g.get('gameType') in allowed_types]
    finished.sort(key=lambda g: g.get('gameDate', ''), reverse=True)
    return [str(g['id']) for g in finished[:n]]

# --- Building CSVs Async ---

async def build_player_season_totals(session: aiohttp.ClientSession):
    logger.info("  Player Season Totals.csv...")
    summary, pct = await asyncio.gather(
        fetch_all(session, "skater/summary"),
        fetch_all(session, "skater/percentages")
    )

    pct_idx = {r['playerId']: r for r in pct}
    rows = []
    
    for r in summary:
        pid, gp = r['playerId'], r.get('gamesPlayed', 0)
        if gp == 0: continue
        
        p = pct_idx.get(pid, {})
        rows.append({
            'Player':       r.get('skaterFullName', ''),
            'Team':         r.get('teamAbbrevs', ''),
            'Position':     r.get('positionCode', 'F'),
            'GP':           gp,
            'Goals':        r.get('goals', 0),
            'Assists':      r.get('assists', 0),
            'Points':       r.get('points', 0),
            'On-Ice SH%':   round(float(p.get('shootingPct5v5') or 0.10) * 100, 2),
            'PDO':          round(float(p.get('skaterShootingPlusSavePct5v5') or 1.0) * 100, 1),
            'CF%_season':   round(float(p.get('satPercentage') or 0.5) * 100, 2),
        })

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(FOLDER_NAME, 'Player Season Totals.csv'), index=False, encoding='utf-8-sig')
    return df

async def build_on_ice(session: aiohttp.ClientSession):
    logger.info("  on_ice.csv...")
    pct = await fetch_all(session, "skater/percentages")
    rows = []
    for r in pct:
        if r.get('gamesPlayed', 0) == 0: continue
        rows.append({
            'Player':       r.get('skaterFullName', ''),
            'Team':         r.get('teamAbbrevs', ''),
            'Position':     r.get('positionCode', 'F'),
            'GP':           r.get('gamesPlayed', 0),
            'On-Ice SH%':   round(float(r.get('shootingPct5v5') or 0.10) * 100, 2),
            'PDO':          round(float(r.get('skaterShootingPlusSavePct5v5') or 1.0) * 100, 1),
        })
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(FOLDER_NAME, 'on_ice.csv'), index=False, encoding='utf-8-sig')
    return df

async def build_power_play(session: aiohttp.ClientSession):
    logger.info("  power play.csv...")
    # L'API NHL offre le endpoint timeonice qui contient ppTimeOnIcePerGame directement
    time_data = await fetch_all(session, "skater/timeonice")
    
    rows = []
    for r in time_data:
        gp = r.get('gamesPlayed', 0)
        if gp == 0: continue
        
        # ppTimeOnIcePerGame est renvoyé en secondes par l'API
        pp_toi_sec = float(r.get('ppTimeOnIcePerGame', 0))
        pp_toi_min = round(pp_toi_sec / 60.0, 2)
        
        rows.append({
            'Player': r.get('skaterFullName', ''),
            'Team':   r.get('teamAbbrevs', ''),
            'GP':     gp,
            'TOI':    pp_toi_min,
        })
        
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(FOLDER_NAME, 'power play.csv'), index=False, encoding='utf-8-sig')
    return df

async def build_goalies(session: aiohttp.ClientSession):
    logger.info("  goalies.csv...")
    data = await fetch_all(session, "goalie/summary")
    rows = []
    for r in data:
        gp = r.get('gamesPlayed', 0)
        if gp == 0: continue
        rows.append({
            'Player':   r.get('goalieFullName', ''),
            'Team':     r.get('teamAbbrevs', ''),
            'Position': 'G',
            'GP':       gp,
            'GAA':      round(float(r.get('goalsAgainstAverage') or 0), 2),
            'SV%':      round(float(r.get('savePct') or 0), 3),
        })
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(FOLDER_NAME, 'goalies.csv'), index=False, encoding='utf-8-sig')
    return df

async def build_pk(session: aiohttp.ClientSession):
    logger.info("  pk.csv...")
    pk_data = await fetch_all(session, "team/penaltykill")
    rows = []
    for r in pk_data:
        rows.append({
            'Team':   r.get('teamFullName', ''),
            'GP':     r.get('gamesPlayed', 0),
            'PK%':    round(float(r.get('penaltyKillPct') or 0.80) * 100, 1),
        })
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(FOLDER_NAME, 'pk.csv'), index=False, encoding='utf-8-sig')
    return df

async def build_match_history(session: aiohttp.ClientSession):
    logger.info("  match.csv...")
    rows = []
    
    async def fetch_team_history(team_abbr, full_name):
        url = f"{BASE_WEB}/v1/club-schedule-season/{team_abbr}/{cfg.api.season_id}"
        data = await api_get(session, url)
        if not data: return []
        res = []
        for g in data.get('games', []):
            g_type = g.get('gameType')
            # On accepte le type configuré OU le type 3 si on est en mode playoff
            is_valid_type = (g_type == int(cfg.api.game_type)) or (cfg.api.mode == "playoff" and g_type == 3)
            if g.get('gameState') != 'OFF' or not is_valid_type: continue
            res.append({
                'Game': f"{g.get('gameDate', '')} - Game {g.get('id', '')} {full_name} Limited Report",
                'Team': full_name,
                'Date': g.get('gameDate', ''),
            })
        return res

    tasks = [fetch_team_history(abbr, full) for full, abbr in TEAM_FULL_TO_ABBR.items()]
    results = await asyncio.gather(*tasks)
    for r in results: rows.extend(r)

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(FOLDER_NAME, 'match.csv'), index=False, encoding='utf-8-sig')
    return df

def compute_hdca_from_cache(all_teams: List[str], game_ids_cache: Dict[str, List[str]]):
    team_stats = defaultdict(lambda: {'hdca': 0, 'hdcf': 0, 'gp': set()})
    processed = set()

    for team_abbr in all_teams:
        game_ids = game_ids_cache.get(team_abbr, [])
        for gid in game_ids:
            if gid in processed: continue
            processed.add(gid)
            cache_path = os.path.join(FOLDER_NAME, "cache", f"pbp_cache_{gid}.json")
            if not os.path.exists(cache_path): continue
            
            with open(cache_path) as f: pbp = json.load(f)

            home_id   = pbp.get('homeTeam', {}).get('id')
            home_abbr = pbp.get('homeTeam', {}).get('abbrev', '')
            away_abbr = pbp.get('awayTeam', {}).get('abbrev', '')

            for play in pbp.get('plays', []):
                if play.get('typeDescKey') not in ('shot-on-goal', 'goal', 'missed-shot', 'blocked-shot'): continue
                det = play.get('details', {})
                if not is_high_danger(det.get('xCoord', 0), det.get('yCoord', 0), det.get('zoneCode', ''), 
                                      play.get('homeTeamDefendingSide', 'right'), det.get('eventOwnerTeamId'), home_id):
                    continue

                if det.get('eventOwnerTeamId') == home_id:
                    att_abbr, def_abbr = home_abbr, away_abbr
                else:
                    att_abbr, def_abbr = away_abbr, home_abbr

                team_stats[att_abbr]['hdcf'] += 1
                team_stats[def_abbr]['hdca'] += 1
                team_stats[att_abbr]['gp'].add(gid)
                team_stats[def_abbr]['gp'].add(gid)

    return team_stats

async def build_team_stats(session: aiohttp.ClientSession, all_teams: List[str], game_ids_cache: Dict[str, List[str]]):
    logger.info("  team.csv...")
    summary, pct, realtime, pk_data = await asyncio.gather(
        fetch_all(session, "team/summary"),
        fetch_all(session, "team/percentages"),
        fetch_all(session, "team/realtime"),
        fetch_all(session, "team/penaltykill")
    )

    pct_idx = {r['teamId']: r for r in pct}
    rt_idx  = {r['teamId']: r for r in realtime}
    pk_idx  = {r['teamId']: r for r in pk_data}

    hdca_data = compute_hdca_from_cache(all_teams, game_ids_cache)

    rows = []
    for r in summary:
        tid, name, gp = r['teamId'], r.get('teamFullName', ''), r.get('gamesPlayed', 0)
        if gp == 0: continue

        p, rt, pk = pct_idx.get(tid, {}), rt_idx.get(tid, {}), pk_idx.get(tid, {})
        abbr = TEAM_FULL_TO_ABBR.get(name, '')
        hd   = hdca_data.get(abbr, {})
        hdca_val, hdcf_val = hd.get('hdca', 0), hd.get('hdcf', 0)
        hdcf_pct = round(hdcf_val / (hdca_val + hdcf_val) * 100, 2) if (hdca_val + hdcf_val) > 0 else 50.0

        rows.append({
            'Team':   name,
            'GP':     gp,
            'GA':     r.get('goalsAgainst', 0) or 0,
            'SA':     round((r.get('shotsAgainstPerGame', 28.0) or 28.0) * gp, 0),
            'CA':     float(rt.get('totalShotAttempts') or 0),
            'CF%':    round(float(p.get('satPct') or 0.5) * 100, 2),
            'HDCA':   hdca_val,
            'HDCF%':  hdcf_pct,
            'PK%':    round(float(pk.get('penaltyKillPct') or 0.80) * 100, 1),
        })

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(FOLDER_NAME, 'team.csv'), index=False, encoding='utf-8-sig')
    return df

async def prefetch_pbp_and_boxscores(session: aiohttp.ClientSession, all_teams: List[str]) -> Dict[str, List[str]]:
    # Fix RuntimeWarning: Ensure all coroutines are gathered correctly
    teams_list = list(all_teams)
    tasks_ids = [get_last_n_game_ids(session, team, 10) for team in teams_list]
    id_results = await asyncio.gather(*tasks_ids)
    game_ids_cache = dict(zip(teams_list, id_results))
    
    unique_game_ids = set()
    for gids in game_ids_cache.values():
        unique_game_ids.update(gids)
        
    logger.info(f"  Téléchargement asynchrone PBP de {len(unique_game_ids)} matchs...")
    
    tasks = []
    for gid in unique_game_ids:
        tasks.append(get_pbp(session, gid, api_get))
        tasks.append(get_toi_from_boxscore(session, gid, api_get))
        
    await asyncio.gather(*tasks)
    return game_ids_cache

def is_high_danger(x, y, zone, home_side, event_owner_id, home_team_id):
    if zone != 'O': return False
    abs_x = abs(x)
    # High danger area is the "home plate" in front of the net:
    # 1. Must be in front of the goal line (abs_x <= 89)
    # 2. Must be within the slot distance (abs_x >= 65 is roughly 24 feet from goal line)
    # 3. Y must correspond to the slot width (between the faceoff dots).
    if abs_x > 89: return False
    dist = math.sqrt((89 - abs_x)**2 + y**2)
    return dist <= 26 and abs(y) <= 22

def estimate_xg(x, y, shot_type, is_rebound, is_rush):
    abs_x = abs(x)
    if abs_x > 89:
        xg = 0.01 # Behind the net
    else:
        dist = math.sqrt((89 - abs_x)**2 + y**2)
        if dist <= 15:
            xg = 0.18
        elif dist <= 30:
            xg = 0.08
        elif dist <= 45:
            xg = 0.04
        else:
            xg = 0.015

    if is_rebound: xg += 0.25
    if is_rush: xg += 0.10
    if shot_type in ('deflected', 'tip-in'): xg += 0.12
    if shot_type == 'slap': xg += 0.03

    return min(xg, 0.99)

def compute_last10_stats(all_teams: List[str], game_ids_cache: Dict[str, List[str]]):
    player_stats = defaultdict(lambda: {
        'name': '', 'team': '', 'pos': '', 'gp': 0, 'toi_sec': 0,
        'goals': 0, 'assists': 0, 'points': 0,
        'shots': 0, 'ixg': 0.0, 'ihdcf': 0, 'iscf': 0,
        'rebounds': 0, 'rush': 0, 'games_seen': set(), 'games_scored': defaultdict(int),
    })

    processed_games = set()

    for team_abbr in all_teams:
        game_ids = game_ids_cache.get(team_abbr, [])
        for gid in game_ids:
            if gid in processed_games: continue
            processed_games.add(gid)

            cache_path = os.path.join(FOLDER_NAME, "cache", f"pbp_cache_{gid}.json")
            if not os.path.exists(cache_path): continue
            with open(cache_path) as f: pbp = json.load(f)

            roster = {}
            for p in pbp.get('rosterSpots', []):
                pid = p['playerId']
                fn, ln = p.get('firstName', {}), p.get('lastName', {})
                first = fn.get('default', str(fn)) if isinstance(fn, dict) else str(fn)
                last  = ln.get('default', str(ln)) if isinstance(ln, dict) else str(ln)
                roster[pid] = {
                    'name': f"{first} {last}".strip(),
                    'team': p.get('teamAbbrev', {}).get('default', '') if isinstance(p.get('teamAbbrev'), dict) else str(p.get('teamAbbrev', '')),
                    'pos':  p.get('positionCode', 'F'),
                }

            home_team_id = pbp.get('homeTeam', {}).get('id')
            plays_list = pbp.get('plays', [])

            box_cache = os.path.join(FOLDER_NAME, "cache", f"box_cache_{gid}.json")
            toi_map = {}
            if os.path.exists(box_cache):
                with open(box_cache) as f:
                    data = json.load(f)
                    for side in ('homeTeam', 'awayTeam'):
                        tabbr = data.get(side, {}).get('abbrev', '')
                        for group in ('forwards', 'defense', 'goalies'):
                            for bp in data.get('playerByGameStats', {}).get(side, {}).get(group, []):
                                bpr = bp.get('playerId')
                                if not bpr: continue
                                try:
                                    m, s = map(int, bp.get('toi', '0:00').split(':'))
                                    toi_map[bpr] = {'toi': m*60+s, 'team': tabbr}
                                except: pass

            for pid_toi, toi_data in toi_map.items():
                ps = player_stats[pid_toi]
                if pid_toi in roster:
                    ps['name'], ps['pos'] = roster[pid_toi]['name'], roster[pid_toi]['pos']
                if not ps['team']: ps['team'] = toi_data['team']
                ps['games_seen'].add(gid)
                ps['toi_sec'] += toi_data['toi']

            def time_to_sec(t):
                try: m, s = map(int, t.split(':')); return m*60+s
                except: return 0

            for i, play in enumerate(plays_list):
                t, det = play.get('typeDescKey', ''), play.get('details', {})
                per = play.get('periodDescriptor', {}).get('number', 1)

                if t in ('shot-on-goal', 'goal', 'missed-shot', 'blocked-shot'):
                    pid = det.get('shootingPlayerId') if t == 'blocked-shot' else (det.get('shootingPlayerId') or det.get('scoringPlayerId'))
                    if not pid or pid not in roster: continue

                    ps_check = player_stats[pid]
                    if not ps_check['team']:
                        ps_check['name'], ps_check['pos'] = roster[pid]['name'], roster[pid]['pos']
                        ps_check['team'] = toi_map[pid]['team'] if pid in toi_map else roster[pid]['team']

                    x, y, zone = det.get('xCoord', 0), det.get('yCoord', 0), det.get('zoneCode', '')
                    home_side, owner = play.get('homeTeamDefendingSide', 'right'), det.get('eventOwnerTeamId')
                    shot_type = det.get('shotType', 'wrist')

                    tsec = time_to_sec(play.get('timeInPeriod', '0:00')) + (per-1)*1200
                    is_rebound, is_rush = False, False
                    for j in range(max(0, i-5), i):
                        pj = plays_list[j]
                        if pj.get('periodDescriptor', {}).get('number', 1) != per: continue
                        delta = tsec - (time_to_sec(pj.get('timeInPeriod','0:00')) + (per-1)*1200)
                        tj = pj.get('typeDescKey', '')
                        if tj == 'shot-on-goal' and 0 < delta <= 3: is_rebound = True
                        if tj == 'takeaway' and 0 < delta <= 4: is_rush = True

                    xg_val = estimate_xg(x, y, shot_type, is_rebound, is_rush) if zone == 'O' else 0.0
                    hd = is_high_danger(x, y, zone, home_side, owner, home_team_id)
                    sc = (math.sqrt((89 - abs(x))**2 + y**2) if zone == 'O' else 999) < 35

                    ps = player_stats[pid]
                    ps['name'], ps['team'], ps['pos'] = roster[pid]['name'], roster[pid]['team'], roster[pid]['pos']
                    ps['games_seen'].add(gid)
                    ps['ixg']   += xg_val
                    ps['ihdcf'] += int(hd)
                    ps['iscf']  += int(sc)

                    if t in ('shot-on-goal', 'goal'): ps['shots'] += 1 
                    if t == 'goal':
                        ps['goals'] += 1
                        ps['points'] += 1
                        ps['games_scored'][gid] += 1
                        
                        # Assists
                        for a_key in ('assist1PlayerId', 'assist2PlayerId'):
                            a_pid = det.get(a_key)
                            if a_pid and a_pid in roster:
                                aps = player_stats[a_pid]
                                aps['name'], aps['team'], aps['pos'] = roster[a_pid]['name'], roster[a_pid]['team'], roster[a_pid]['pos']
                                aps['assists'] += 1
                                aps['points'] += 1
                                aps['games_seen'].add(gid)

                    ps['rebounds'] += int(is_rebound)
                    ps['rush']     += int(is_rush)

    pid_to_team = {} 
    cache_dir = os.path.join(FOLDER_NAME, "cache")
    if os.path.exists(cache_dir):
        for f in os.listdir(cache_dir):
            if not f.startswith('box_cache_'): continue
            try:
                with open(os.path.join(cache_dir, f)) as fh: d = json.load(fh)
                for side in ('homeTeam', 'awayTeam'):
                    abbr = d.get(side, {}).get('abbrev', '')
                    if not abbr: continue
                    for group in ('forwards', 'defense', 'goalies'):
                        for p in d.get('playerByGameStats', {}).get(side, {}).get(group, []):
                            pid_box = p.get('playerId')
                            if pid_box and pid_box not in pid_to_team: pid_to_team[pid_box] = abbr
            except: pass

    for pid, s in player_stats.items():
        if not s['team'] and pid in pid_to_team: s['team'] = pid_to_team[pid]

    rows = []
    for pid, s in player_stats.items():
        gp = len(s['games_seen'])
        if gp == 0: continue
            
        gids = sorted(list(s['games_seen']), reverse=True)
        consec_goals = 0
        for g in gids:
            if s['games_scored'].get(g, 0) > 0: consec_goals += 1
            else: break
                
        rows.append({
            'Player':   s['name'], 'Team': s['team'], 'Position': s['pos'],
            'GP':       gp, 'TOI': round(s['toi_sec'] / 60.0, 1),
            'Goals':    s['goals'], 'Assists': s['assists'], 'Points': s['points'],
            'Shots':    s['shots'],
            'ixG':      round(s['ixg'], 3), 'iSCF': s['iscf'], 'iHDCF': s['ihdcf'],
            'Rebounds': s['rebounds'], 'RushShots': s['rush'], 'ConsecGoals': consec_goals,
        })
    df = pd.DataFrame(rows)
    df['Team'] = df['Team'].replace('', pd.NA)
    df = df.dropna(subset=['Team'])
    df.to_csv(os.path.join(FOLDER_NAME, 'last 10.csv'), index=False, encoding='utf-8-sig')
    return df

async def main_async():
    logger.info("=" * 55)
    logger.info("  DÉMARRAGE FETCHING ASYNCHRONE 🚀")
    logger.info("=" * 55)
    t0 = time.time()
    
    async with aiohttp.ClientSession() as session:
        # Phase 1: Parallel general stats building
        tasks = [
            build_player_season_totals(session),
            build_on_ice(session),
            build_power_play(session),
            build_goalies(session),
            build_pk(session),
            build_match_history(session)
        ]
        await asyncio.gather(*tasks)

        # Phase 2: Play-by-play Logic
        all_teams = list(TEAM_FULL_TO_ABBR.values())
        
        # Prefetch PBP and boxscore into json cache parallelized
        game_ids_cache = await prefetch_pbp_and_boxscores(session, all_teams)
        
        # Calculate stats (fast cpu bound operations from cache)
        compute_last10_stats(all_teams, game_ids_cache)
        await build_team_stats(session, all_teams, game_ids_cache)

    elapsed = time.time() - t0
    logger.info(f"✅ Scraping terminé en {elapsed:.1f} secondes !")

def update_all_stats_sync():
    """Point d'entrée principal pour compatibilité avec bot_logic.py."""
    global SEMAPHORE
    SEMAPHORE = None  # Reset pour la nouvelle boucle asyncio
    cleanup_pbp_cache()
    if os.name == 'nt':
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            except Exception:
                pass
    asyncio.run(main_async())
