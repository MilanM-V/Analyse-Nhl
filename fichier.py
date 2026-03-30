"""
fichier_nhl.py — 100% API NHL officielle (ASYNC TURBO)
Scraping asynchrone pour passer de ~2 min à ~10 secondes.
"""

import os, time, math, json, logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
import asyncio
import aiohttp

load_dotenv()

logger = logging.getLogger("NHL_Bot")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
try:
    file_handler = RotatingFileHandler('bot.log', maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
except Exception:
    pass

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

FOLDER_NAME = "stats"
if not os.path.exists(FOLDER_NAME):
    os.makedirs(FOLDER_NAME)

BASE      = "https://api.nhle.com/stats/rest/en"
BASE_WEB  = "https://api-web.nhle.com"
SEASON_ID = "20252026"
GAME_TYPE = "2"
EXP       = f"seasonId={SEASON_ID} and gameTypeId={GAME_TYPE}"

TEAM_FULL_TO_ABBR = {
    'Anaheim Ducks': 'ANA', 'Boston Bruins': 'BOS', 'Buffalo Sabres': 'BUF',
    'Calgary Flames': 'CGY', 'Carolina Hurricanes': 'CAR', 'Chicago Blackhawks': 'CHI',
    'Colorado Avalanche': 'COL', 'Columbus Blue Jackets': 'CBJ', 'Dallas Stars': 'DAL',
    'Detroit Red Wings': 'DET', 'Edmonton Oilers': 'EDM', 'Florida Panthers': 'FLA',
    'Los Angeles Kings': 'LAK', 'Minnesota Wild': 'MIN', 'Montreal Canadiens': 'MTL',
    'Nashville Predators': 'NSH', 'New Jersey Devils': 'NJD', 'New York Islanders': 'NYI',
    'New York Rangers': 'NYR', 'Ottawa Senators': 'OTT', 'Philadelphia Flyers': 'PHI',
    'Pittsburgh Penguins': 'PIT', 'San Jose Sharks': 'SJS', 'Seattle Kraken': 'SEA',
    'St. Louis Blues': 'STL', 'Tampa Bay Lightning': 'TBL', 'Toronto Maple Leafs': 'TOR',
    'Vancouver Canucks': 'VAN', 'Vegas Golden Knights': 'VGK', 'Washington Capitals': 'WSH',
    'Winnipeg Jets': 'WPG', 'Utah Hockey Club': 'UTA',
}

# --- Asynchronous Network Layer ---

SEMAPHORE = asyncio.Semaphore(20)

async def api_get(session, url, retries=5):
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

async def fetch_all(session, endpoint, exp=None, limit=100):
    exp_str = exp or EXP
    url_base = f"{BASE}/{endpoint}?limit={limit}&cayenneExp={exp_str}"
    
    # Check total items first
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

# --- xG Model logic (no async needed) ---

SHOT_TYPE_ENCODE = {
    'wrist': 1.0, 'snap': 0.85, 'backhand': 0.75,
    'tip-in': 1.2, 'deflected': 1.15, 'slap': 0.65,
    'wrap-around': 0.70, 'bat': 0.60,
}
XG_MODEL_PATH = "models/xg_model.pkl"

def _xg_features(x, y, shot_type='wrist', is_pp=False, is_5v5=True,
                  is_slot=False, is_rebound=False, is_rush=False, period=1):
    bx   = 89.0
    ax   = abs(x)
    dist = math.sqrt((bx - ax)**2 + y**2)
    angle = math.degrees(math.atan2(abs(y), bx - ax)) if (bx - ax) > 0 else 90.0
    shot_val = SHOT_TYPE_ENCODE.get(shot_type, 0.8)
    slot = int(ax >= 69 and abs(y) <= 15)
    return [
        dist, angle, dist**2, math.sin(math.radians(angle)),
        ax, shot_val, int(is_pp), int(is_5v5), 1/(dist+1),
        slot, int(is_rebound), int(is_rush), min(period, 4),
    ]

class XGModel:
    def __init__(self):
        self._load_or_train()

    def _load_or_train(self):
        import pickle
        if os.path.exists(XG_MODEL_PATH):
            try:
                with open(XG_MODEL_PATH, 'rb') as f:
                    data = pickle.load(f)
                self.model   = data['model']
                self.scaler  = data.get('scaler')
                self.use_pkl = True
                auc = data.get('auc_cv', 0)
                n   = data.get('n_train', 0)
                logger.info(f"[xG model] Chargé depuis pkl — AUC={auc:.4f}")
                return
            except Exception as e:
                logger.warning(f"[xG model] Erreur chargement pkl: {e}")

        self.use_pkl = False
        self.scaler  = StandardScaler()
        np.random.seed(42)
        n = 10000
        xs = np.random.uniform(25, 89, n)
        ys = np.random.uniform(-30, 30, n)
        feats = np.array([_xg_features(xi, yi) for xi, yi in zip(xs, ys)])
        dist  = feats[:, 0]
        prob  = 1 / (1 + np.exp(0.12 * (dist - 18)))
        labels = (np.random.random(n) < prob).astype(int)
        X_sc = self.scaler.fit_transform(feats)
        self.model = LogisticRegression(max_iter=1000)
        self.model.fit(X_sc, labels)

    def predict(self, x, y, shot_type='wrist', sit='1551', is_rebound=False, is_rush=False, period=1):
        is_pp  = len(sit) >= 3 and sit[1] > sit[2]
        is_5v5 = sit == '1551'
        feats  = np.array([_xg_features(x, y, shot_type, is_pp, is_5v5, False, is_rebound, is_rush, period)])
        if self.scaler:
            feats = self.scaler.transform(feats)
        return float(self.model.predict_proba(feats)[0][1])

_xg_model = None

def get_xg_model():
    global _xg_model
    if _xg_model is None:
        _xg_model = XGModel()
    return _xg_model

def is_high_danger(x, y, zone_code, home_defending_side, event_owner_team_id, home_team_id):
    if zone_code != 'O': return False
    ax = abs(x)
    dist = math.sqrt((89 - ax)**2 + y**2)
    in_slot = ax >= 54 and abs(y) <= 9
    return in_slot or dist < 20

# --- Fetch details async ---

async def get_last_n_game_ids(session, team_abbr, n=10):
    url = f"{BASE_WEB}/v1/club-schedule-season/{team_abbr}/{SEASON_ID}"
    data = await api_get(session, url)
    if not data: return []
    games = data.get('games', [])
    finished = [g for g in games if g.get('gameState') == 'OFF' and g.get('gameType') == 2]
    finished.sort(key=lambda g: g.get('gameDate', ''), reverse=True)
    return [str(g['id']) for g in finished[:n]]

async def get_pbp(session, game_id):
    cache_dir = os.path.join(FOLDER_NAME, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"pbp_cache_{game_id}.json")
    
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)
            
    data = await api_get(session, f"{BASE_WEB}/v1/gamecenter/{game_id}/play-by-play")
    if data:
        with open(cache_path, 'w') as f:
            json.dump(data, f)
    return data

async def get_toi_from_boxscore(session, game_id):
    cache_dir = os.path.join(FOLDER_NAME, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"box_cache_{game_id}.json")
    
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            data = json.load(f)
    else:
        data = await api_get(session, f"{BASE_WEB}/v1/gamecenter/{game_id}/boxscore")
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

# --- Building CSVs Async ---

async def build_player_season_totals(session):
    logger.info("  Player Season Totals.csv...")
    summary_task = fetch_all(session, "skater/summary")
    pct_task = fetch_all(session, "skater/percentages")
    summary, pct = await asyncio.gather(summary_task, pct_task)

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
            'On-Ice SH%':   round(float(p.get('shootingPct5v5') or 0.10) * 100, 2),
            'PDO':          round(float(p.get('skaterShootingPlusSavePct5v5') or 1.0) * 100, 1),
            'CF%_season':   round(float(p.get('satPercentage') or 0.5) * 100, 2),
        })

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(FOLDER_NAME, 'Player Season Totals.csv'), index=False, encoding='utf-8-sig')
    return df

async def build_on_ice(session):
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

async def build_power_play(session):
    logger.info("  power play.csv...")
    summary = await fetch_all(session, "skater/summary")
    rows = []
    for r in summary:
        gp = r.get('gamesPlayed', 0)
        if gp == 0: continue
        rows.append({
            'Player': r.get('skaterFullName', ''),
            'Team':   r.get('teamAbbrevs', ''),
            'GP':     gp,
            'TOI':    float(r.get('ppPoints', 0) or 0) * 2.0,
        })
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(FOLDER_NAME, 'power play.csv'), index=False, encoding='utf-8-sig')
    return df

async def build_goalies(session):
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

async def build_pk(session):
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

async def build_match_history(session):
    logger.info("  match.csv...")
    rows = []
    
    async def fetch_team_history(team_abbr, full_name):
        url = f"{BASE_WEB}/v1/club-schedule-season/{team_abbr}/{SEASON_ID}"
        data = await api_get(session, url)
        if not data: return []
        res = []
        for g in data.get('games', []):
            if g.get('gameState') != 'OFF' or g.get('gameType') != 2: continue
            res.append({
                'Game': f"{g.get('gameDate', '')} - Game {g.get('id', '')} {full_name} Limited Report",
                'Team': full_name,
                'Date': g.get('gameDate', ''),
            })
        return res

    tasks = []
    for full_name, team_abbr in TEAM_FULL_TO_ABBR.items():
        tasks.append(fetch_team_history(team_abbr, full_name))
        
    results = await asyncio.gather(*tasks)
    for r in results: rows.extend(r)

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(FOLDER_NAME, 'match.csv'), index=False, encoding='utf-8-sig')
    return df

def compute_hdca_from_cache(all_teams, game_ids_cache=None):
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

async def build_team_stats(session, all_teams, game_ids_cache):
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

    full_to_abbr = {v2: k2 for k2, v2 in TEAM_FULL_TO_ABBR.items()}
    full_to_abbr = {v: k for k, v in full_to_abbr.items()}

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

async def prefetch_pbp_and_boxscores(session, all_teams):
    """Prétélécharge tous les Boxscores et PBP des 10 derniers matchs en parallèle."""
    # 1. Obtenir les 10 derniers game_ids par équipe
    game_tasks = {team: get_last_n_game_ids(session, team, 10) for team in all_teams}
    results = await asyncio.gather(*game_tasks.values())
    game_ids_cache = dict(zip(game_tasks.keys(), results))
    
    # 2. Extraire la liste unique des game_ids
    unique_game_ids = set()
    for gids in game_ids_cache.values():
        unique_game_ids.update(gids)
        
    logger.info(f"  Téléchargement asynchrone PBP de {len(unique_game_ids)} matchs...")
    
    # 3. Lancer Fetch PBP & Boxscore concurrently
    tasks = []
    for gid in unique_game_ids:
        tasks.append(get_pbp(session, gid))
        tasks.append(get_toi_from_boxscore(session, gid))
        
    await asyncio.gather(*tasks)
    return game_ids_cache


def compute_last10_stats(all_teams, game_ids_cache):
    xg_model = get_xg_model()

    player_stats = defaultdict(lambda: {
        'name': '', 'team': '', 'pos': '', 'gp': 0, 'toi_sec': 0,
        'goals': 0, 'shots': 0, 'ixg': 0.0, 'ihdcf': 0, 'iscf': 0,
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
                sit, per = play.get('situationCode', ''), play.get('periodDescriptor', {}).get('number', 1)

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

                    xg_val = xg_model.predict(x, y, shot_type, sit, is_rebound=is_rebound, is_rush=is_rush, period=per) if zone == 'O' else 0.0
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
                        ps['games_scored'][gid] += 1

                    ps['rebounds'] += int(is_rebound)
                    ps['rush']     += int(is_rush)

    pid_to_team = {} 
    for f in os.listdir(os.path.join(FOLDER_NAME, "cache")):
        if not f.startswith('box_cache_'): continue
        try:
            with open(os.path.join(FOLDER_NAME, "cache", f)) as fh: d = json.load(fh)
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
            'Goals':    s['goals'], 'Shots': s['shots'],
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
    
    # Init xG model in thread
    get_xg_model()

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

def cleanup_pbp_cache():
    now = time.time()
    count = 0
    cache_dir = os.path.join(FOLDER_NAME, "cache")
    if not os.path.exists(cache_dir): return
    for f in os.listdir(cache_dir):
        if (f.startswith('pbp_cache_') or f.startswith('box_cache_')) and f.endswith('.json'):
            fpath = os.path.join(cache_dir, f)
            if now - os.path.getmtime(fpath) > 2 * 86400:
                os.remove(fpath)
                count += 1
    if count: logger.info(f"  Cache PBP: {count} fichiers supprimés")

def update_all_stats_sync():
    """Point d'entrée principal pour la compatibilité avec main_bot.py"""
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

if __name__ == "__main__":
    update_all_stats_sync()
