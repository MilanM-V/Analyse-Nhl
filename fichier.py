"""
fichier_nhl.py — 100% API NHL officielle, zéro Selenium, zéro scraping tiers
Remplace fichier.py + NST/MoneyPuck.

Stats calculées :
  - Player Season Totals.csv : GP, Goals, Position, oiSH%, PDO, CF% (via API percentages)
  - last 10.csv              : stats agrégées sur les 10 derniers matchs de chaque équipe
                               incluant ixG (modèle logistique) et iHDCF (coordonnées XY)
  - power play.csv           : TOI PP par joueur
  - team.csv                 : GA/j, SA/j, CA/j, CF%, HDCA/j, PK% par équipe
  - on_ice.csv               : oiSH%, PDO par joueur (5v5)
  - goalies.csv              : GP, GAA, SV% par gardien
  - match.csv                : historique matchs (pour B2B)
  - pk.csv                   : PK% par équipe
"""

import os, time, math, json, csv, pickle, requests, logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

load_dotenv()

logger = logging.getLogger("NHL_Bot")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = RotatingFileHandler('bot.log', maxBytes=5*1024*1024, backupCount=5)
file_handler.setFormatter(formatter)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(file_handler)
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

def api_get(url, retries=5):
    for i in range(retries):
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                wait = min(2 ** (i + 1), 30)
                logger.warning(f"HTTP 429 (rate limit) — attente {wait}s avant retry {i+1}/{retries} — {url}")
                time.sleep(wait)
                continue
            logger.warning(f"HTTP {r.status_code} — {url}")
            time.sleep(1)
        except Exception as e:
            logger.warning(f"Tentative {i+1}/{retries} échouée: {e}")
            time.sleep(2)
    return None

def fetch_all(endpoint, exp=None, limit=100):
    """Récupère toutes les pages d'un endpoint paginé (max 100 par page)."""
    exp_str = exp or EXP
    all_data = []
    start = 0
    while True:
        url = f"{BASE}/{endpoint}?limit={limit}&start={start}&cayenneExp={exp_str}"
        data = api_get(url)
        if not data or not data.get('data'):
            break
        all_data.extend(data['data'])
        total = data.get('total', 0)
        logger.debug(f"  {endpoint}: {len(all_data)}/{total}")
        if len(all_data) >= total or len(data['data']) < limit:
            break
        start += limit
        time.sleep(0.2)
    return all_data

SHOT_TYPE_ENCODE = {
    'wrist': 1.0, 'snap': 0.85, 'backhand': 0.75,
    'tip-in': 1.2, 'deflected': 1.15, 'slap': 0.65,
    'wrap-around': 0.70, 'bat': 0.60,
}
XG_MODEL_PATH = "xg_model.pkl"  

def _xg_features(x, y, shot_type='wrist', is_pp=False, is_5v5=True,
                  is_slot=False, is_rebound=False, is_rush=False, period=1):
    """Features pour le modèle xG — identiques à train_xg.py v2 (13 features)."""
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
    """
    Modèle xG chargé depuis xg_model.pkl (entraîné sur vraies données NHL).
    Fallback sur modèle logistique synthétique si pkl absent.
    """
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
                logger.info(f"[xG model] Chargé depuis pkl — AUC={auc:.4f} n={n} tirs")
                return
            except Exception as e:
                logger.warning(f"[xG model] Erreur chargement pkl: {e} — fallback synthétique")

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
        logger.info("[xG model] Modèle synthétique (lance train_xg.py pour ameliorer)")

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
    """
    Zone haute danger NHL = slot devant le filet.
    Coordonnées NHL : patinoire de -100 à +100 en X, -42 à +42 en Y.
    But local à x=+89 (côté droit quand homeTeamDefendingSide='right').
    On normalise pour que les tirs soient toujours en zone offensive positive.
    """
    if zone_code != 'O':
        return False
    ax = abs(x)
    dist = math.sqrt((89 - ax)**2 + y**2)
    in_slot = ax >= 54 and abs(y) <= 9
    return in_slot or dist < 20

def get_last_n_game_ids(team_abbr, n=10):
    """Retourne les IDs des n derniers matchs terminés d'une équipe."""
    url = f"{BASE_WEB}/v1/club-schedule-season/{team_abbr}/{SEASON_ID}"
    data = api_get(url)
    if not data:
        return []
    games = data.get('games', [])
    finished = [g for g in games if g.get('gameState') == 'OFF'
                and g.get('gameType') == 2]
    finished.sort(key=lambda g: g.get('gameDate', ''), reverse=True)
    return [str(g['id']) for g in finished[:n]]

def get_pbp(game_id):
    """Retourne le play-by-play d'un match avec cache fichier."""
    cache_dir = os.path.join(FOLDER_NAME, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"pbp_cache_{game_id}.json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)
    data = api_get(f"{BASE_WEB}/v1/gamecenter/{game_id}/play-by-play")
    if data:
        with open(cache_path, 'w') as f:
            json.dump(data, f)
    time.sleep(0.3)
    return data

def get_toi_from_boxscore(game_id):
    """
    Retourne {playerId: {'toi': toi_seconds, 'team': team_abbr}} depuis le boxscore.
    toi format '18:03' → 1083 secondes.
    """
    cache_dir = os.path.join(FOLDER_NAME, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, f"box_cache_{game_id}.json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            data = json.load(f)
    else:
        data = api_get(f"{BASE_WEB}/v1/gamecenter/{game_id}/boxscore")
        if data:
            with open(cache_path, 'w') as f:
                json.dump(data, f)
        time.sleep(0.2)

    if not data:
        return {}

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
                toi = parse_toi(p.get('toi', '0:00'))
                if pid:
                    toi_dict[pid] = {'toi': toi, 'team': team_abbr}
    return toi_dict

def compute_last10_stats(all_teams):
    """
    Agrège les stats des 10 derniers matchs pour chaque joueur.
    Calcule : goals, shots, ixG, iHDCF, iSCF, TOI, GP
    """
    logger.info("  Calcul last 10 — agrégation play-by-play...")
    xg_model = get_xg_model()

    player_stats = defaultdict(lambda: {
        'name': '', 'team': '', 'pos': '',
        'gp': 0, 'toi_sec': 0,
        'goals': 0, 'shots': 0,
        'ixg': 0.0, 'ihdcf': 0,
        'iscf': 0,
        'rebounds': 0,   
        'rush': 0,       
        'games_seen': set(),
    })

    processed_games = set()

    for team_abbr in all_teams:
        game_ids = get_last_n_game_ids(team_abbr, n=10)
        logger.info(f"    {team_abbr}: {len(game_ids)} matchs")

        for gid in game_ids:
            if gid in processed_games:
                continue
            processed_games.add(gid)

            pbp = get_pbp(gid)
            if not pbp:
                continue

            roster = {}
            for p in pbp.get('rosterSpots', []):
                pid = p['playerId']
                fn  = p.get('firstName', {})
                ln  = p.get('lastName', {})
                first = fn.get('default', str(fn)) if isinstance(fn, dict) else str(fn)
                last  = ln.get('default', str(ln)) if isinstance(ln, dict) else str(ln)
                roster[pid] = {
                    'name': f"{first} {last}".strip(),
                    'team': p.get('teamAbbrev', {}).get('default', '') if isinstance(p.get('teamAbbrev'), dict) else str(p.get('teamAbbrev', '')),
                    'pos':  p.get('positionCode', 'F'),
                }

            home_team_id = pbp.get('homeTeam', {}).get('id')

            def time_to_sec(t):
                try:
                    m, s = map(int, t.split(':'))
                    return m * 60 + s
                except:
                    return 0

            plays_list = pbp.get('plays', [])

            toi_map = get_toi_from_boxscore(gid)
            for pid_toi, toi_data in toi_map.items():
                toi_sec  = toi_data['toi']
                box_team = toi_data['team']   
                ps = player_stats[pid_toi]
                if pid_toi in roster:
                    ps['name'] = roster[pid_toi]['name']
                    ps['pos']  = roster[pid_toi]['pos']
                if not ps['team']:
                    ps['team'] = box_team
                ps['games_seen'].add(gid)
                ps['toi_sec'] += toi_sec

            for i, play in enumerate(plays_list):
                t    = play.get('typeDescKey', '')
                det  = play.get('details', {})
                sit  = play.get('situationCode', '')
                per  = play.get('periodDescriptor', {}).get('number', 1)

                if t in ('shot-on-goal', 'goal', 'missed-shot', 'blocked-shot'):
                    if t == 'blocked-shot':
                        pid = det.get('shootingPlayerId')
                    else:
                        pid = det.get('shootingPlayerId') or det.get('scoringPlayerId')
                    if not pid or pid not in roster:
                        continue

                    ps_check = player_stats[pid]
                    if not ps_check['team']:
                        ps_check['name'] = roster[pid]['name']
                        ps_check['pos']  = roster[pid]['pos']
                        if pid in toi_map:
                            ps_check['team'] = toi_map[pid]['team']
                        else:
                            ps_check['team'] = roster[pid]['team']

                    x    = det.get('xCoord', 0)
                    y    = det.get('yCoord', 0)
                    zone = det.get('zoneCode', '')
                    home_side = play.get('homeTeamDefendingSide', 'right')
                    owner = det.get('eventOwnerTeamId')

                    shot_type = det.get('shotType', 'wrist')

                    tsec = time_to_sec(play.get('timeInPeriod', '0:00')) + (per-1)*1200
                    is_rebound = False
                    is_rush    = False
                    for j in range(max(0, i-5), i):
                        pj  = plays_list[j]
                        if pj.get('periodDescriptor', {}).get('number', 1) != per:
                            continue
                        tj    = pj.get('typeDescKey', '')
                        tsecj = time_to_sec(pj.get('timeInPeriod','0:00')) + (per-1)*1200
                        delta = tsec - tsecj
                        if tj == 'shot-on-goal' and 0 < delta <= 3:
                            is_rebound = True
                        if tj == 'takeaway' and 0 < delta <= 4:
                            is_rush = True

                    xg_val = xg_model.predict(x, y, shot_type, sit, is_rebound=is_rebound, is_rush=is_rush, period=per) if zone == 'O' else 0.0
                    hd     = is_high_danger(x, y, zone, home_side, owner, home_team_id)
                    dist   = math.sqrt((89 - abs(x))**2 + y**2) if zone == 'O' else 999
                    sc     = dist < 35

                    ps = player_stats[pid]
                    ps['name'] = roster[pid]['name']
                    ps['team'] = roster[pid]['team']
                    ps['pos']  = roster[pid]['pos']
                    ps['games_seen'].add(gid)
                    ps['ixg']   += xg_val
                    ps['ihdcf'] += int(hd)
                    ps['iscf']  += int(sc)

                    if t in ('shot-on-goal', 'goal'):
                        ps['shots'] += 1 
                    if t == 'goal':
                        ps['goals'] += 1

                    ps['rebounds'] += int(is_rebound)
                    ps['rush']     += int(is_rush)

    cache_dir = os.path.join(FOLDER_NAME, "cache")
    pid_to_team = {} 
    for f in os.listdir(cache_dir):
        if not f.startswith('box_cache_'): continue
        try:
            with open(os.path.join(cache_dir, f)) as fh:
                d = json.load(fh)
            for side in ('homeTeam', 'awayTeam'):
                abbr = d.get(side, {}).get('abbrev', '')
                if not abbr: continue
                for group in ('forwards', 'defense', 'goalies'):
                    for p in d.get('playerByGameStats', {}).get(side, {}).get(group, []):
                        pid_box = p.get('playerId')
                        if pid_box and pid_box not in pid_to_team:
                            pid_to_team[pid_box] = abbr
        except: pass

    fixed = 0
    for pid, s in player_stats.items():
        if not s['team'] and pid in pid_to_team:
            s['team'] = pid_to_team[pid]
            fixed += 1
    logger.info(f"  Teams récupérés depuis index boxscore: {fixed} joueurs corrigés")

    rows = []
    for pid, s in player_stats.items():
        gp = len(s['games_seen'])
        if gp == 0:
            continue
        toi_min = round(s['toi_sec'] / 60.0, 1)
        rows.append({
            'Player':   s['name'],
            'Team':     s['team'],
            'Position': s['pos'],
            'GP':       gp,
            'TOI':      toi_min,
            'Goals':    s['goals'],
            'Shots':    s['shots'],
            'ixG':      round(s['ixg'], 3),
            'iSCF':     s['iscf'],
            'iHDCF':    s['ihdcf'],
            'Rebounds': s['rebounds'],   
            'RushShots':s['rush'],      
        })

    return pd.DataFrame(rows)

def build_player_season_totals():
    """Équivalent Player Season Totals.csv — stats saison + oiSH% + PDO + CF%"""
    logger.info("  Player Season Totals.csv...")

    summary = fetch_all("skater/summary")
    pct     = fetch_all("skater/percentages")

    pct_idx = {r['playerId']: r for r in pct}

    rows = []
    for r in summary:
        pid   = r['playerId']
        gp    = r.get('gamesPlayed', 0)
        if gp == 0:
            continue
        p     = pct_idx.get(pid, {})
        oish  = round(float(p.get('shootingPct5v5') or 0.10) * 100, 2)
        pdo_raw = float(p.get('skaterShootingPlusSavePct5v5') or 1.0)
        pdo   = round(pdo_raw * 100, 1)
        cf    = round(float(p.get('satPercentage') or 0.5) * 100, 2)
        pos   = r.get('positionCode', 'F')

        rows.append({
            'Player':       r.get('skaterFullName', ''),
            'Team':         r.get('teamAbbrevs', ''),
            'Position':     pos,
            'GP':           gp,
            'Goals':        r.get('goals', 0),
            'On-Ice SH%':   oish,
            'PDO':          pdo,
            'CF%_season':   cf,
        })

    df = pd.DataFrame(rows)
    path = os.path.join(FOLDER_NAME, 'Player Season Totals.csv')
    df.to_csv(path, index=False, encoding='utf-8-sig')
    logger.info(f"  OK — {len(df)} joueurs")
    return df

def build_on_ice():
    """Équivalent on_ice.csv — oiSH% et PDO 5v5"""
    logger.info("  on_ice.csv...")
    pct = fetch_all("skater/percentages")
    rows = []
    for r in pct:
        if r.get('gamesPlayed', 0) == 0:
            continue
        oish    = round(float(r.get('shootingPct5v5') or 0.10) * 100, 2)
        pdo_raw = float(r.get('skaterShootingPlusSavePct5v5') or 1.0)
        pdo     = round(pdo_raw * 100, 1)
        rows.append({
            'Player':       r.get('skaterFullName', ''),
            'Team':         r.get('teamAbbrevs', ''),
            'Position':     r.get('positionCode', 'F'),
            'GP':           r.get('gamesPlayed', 0),
            'On-Ice SH%':   oish,
            'PDO':          pdo,
        })
    df = pd.DataFrame(rows)
    path = os.path.join(FOLDER_NAME, 'on_ice.csv')
    df.to_csv(path, index=False, encoding='utf-8-sig')
    logger.info(f"  OK — {len(df)} joueurs")
    return df

def build_power_play():
    """Équivalent power play.csv — TOI PP par joueur"""
    logger.info("  power play.csv...")
    summary = fetch_all("skater/summary")
    rows = []
    for r in summary:
        gp = r.get('gamesPlayed', 0)
        if gp == 0:
            continue
        pp_pts = r.get('ppPoints', 0) or 0
        pp_goals = r.get('ppGoals', 0) or 0
        rows.append({
            'Player': r.get('skaterFullName', ''),
            'Team':   r.get('teamAbbrevs', ''),
            'GP':     gp,
            'TOI':    float(pp_pts) * 2.0,
        })
    df = pd.DataFrame(rows)
    path = os.path.join(FOLDER_NAME, 'power play.csv')
    df.to_csv(path, index=False, encoding='utf-8-sig')
    logger.info(f"  OK — {len(df)} joueurs")
    return df

def compute_hdca_from_cache(all_teams, game_ids_cache=None):
    """
    Calcule HDCA et HDCF par équipe depuis les PBP déjà en cache.
    Retourne {team_abbr: {'hdca': n, 'hdcf': n, 'gp': n}}
    game_ids_cache: dict {team_abbr: [game_ids]} — évite de re-appeler get_last_n_game_ids.
    """
    xg_model = get_xg_model()
    team_stats = defaultdict(lambda: {'hdca': 0, 'hdcf': 0, 'gp': set()})
    processed = set()

    for team_abbr in all_teams:
        if game_ids_cache and team_abbr in game_ids_cache:
            game_ids = game_ids_cache[team_abbr]
        else:
            game_ids = get_last_n_game_ids(team_abbr, n=10)
        for gid in game_ids:
            if gid in processed:
                continue
            processed.add(gid)
            cache_path = os.path.join(FOLDER_NAME, "cache", f"pbp_cache_{gid}.json")
            if not os.path.exists(cache_path):
                continue
            with open(cache_path) as f:
                pbp = json.load(f)

            home_id   = pbp.get('homeTeam', {}).get('id')
            home_abbr = pbp.get('homeTeam', {}).get('abbrev', '')
            away_abbr = pbp.get('awayTeam', {}).get('abbrev', '')

            for play in pbp.get('plays', []):
                t   = play.get('typeDescKey', '')
                det = play.get('details', {})
                if t not in ('shot-on-goal', 'goal', 'missed-shot', 'blocked-shot'):
                    continue
                x    = det.get('xCoord', 0)
                y    = det.get('yCoord', 0)
                zone = det.get('zoneCode', '')
                owner_id = det.get('eventOwnerTeamId')
                home_side = play.get('homeTeamDefendingSide', 'right')

                hd = is_high_danger(x, y, zone, home_side, owner_id, home_id)
                if not hd:
                    continue

                if owner_id == home_id:
                    att_abbr = home_abbr
                    def_abbr = away_abbr
                else:
                    att_abbr = away_abbr
                    def_abbr = home_abbr

                team_stats[att_abbr]['hdcf'] += 1
                team_stats[def_abbr]['hdca'] += 1
                team_stats[att_abbr]['gp'].add(gid)
                team_stats[def_abbr]['gp'].add(gid)

    return team_stats

def build_team_stats(all_teams=None, game_ids_cache=None):
    """Équivalent team.csv — GA/j, SA/j, CA/j, CF%, HDCA/j, PK%"""
    logger.info("  team.csv...")

    summary  = fetch_all("team/summary")
    pct      = fetch_all("team/percentages")
    realtime = fetch_all("team/realtime")
    pk_data  = fetch_all("team/penaltykill")

    pct_idx = {r['teamId']: r for r in pct}
    rt_idx  = {r['teamId']: r for r in realtime}
    pk_idx  = {r['teamId']: r for r in pk_data}

    hdca_data = {}
    if all_teams:
        logger.info("    Calcul HDCA depuis cache PBP...")
        hdca_data = compute_hdca_from_cache(all_teams, game_ids_cache)

    full_to_abbr = {v: k for k, v in {
        v2: k2 for k2, v2 in TEAM_FULL_TO_ABBR.items()
    }.items()}

    rows = []
    for r in summary:
        tid  = r['teamId']
        name = r.get('teamFullName', '')
        gp   = r.get('gamesPlayed', 0)
        if gp == 0:
            continue

        p  = pct_idx.get(tid, {})
        rt = rt_idx.get(tid, {})
        pk = pk_idx.get(tid, {})

        ga     = r.get('goalsAgainst', 0) or 0
        sa_g   = r.get('shotsAgainstPerGame', 28.0) or 28.0
        cf_pct = round(float(p.get('satPct') or 0.5) * 100, 2)
        pk_pct = round(float(pk.get('penaltyKillPct') or 0.80) * 100, 1)
        ca_total = float(rt.get('totalShotAttempts') or 0)

        abbr = TEAM_FULL_TO_ABBR.get(name, '')
        hd   = hdca_data.get(abbr, {})
        gp_pbp = max(1, len(hd.get('gp', {1})))
        hdca_val   = hd.get('hdca', 0)
        hdcf_val   = hd.get('hdcf', 0)
        hdca_total = hdca_val + hdcf_val
        hdcf_pct   = round(hdcf_val / hdca_total * 100, 2) if hdca_total > 0 else 50.0

        rows.append({
            'Team':   name,
            'GP':     gp,
            'GA':     ga,
            'SA':     round(sa_g * gp, 0),
            'CA':     ca_total,
            'CF%':    cf_pct,
            'HDCA':   hdca_val,
            'HDCF%':  hdcf_pct,
            'PK%':    pk_pct,
        })

    df = pd.DataFrame(rows)
    path = os.path.join(FOLDER_NAME, 'team.csv')
    df.to_csv(path, index=False, encoding='utf-8-sig')
    logger.info(f"  OK — {len(df)} équipes")
    return df

def build_pk():
    """Équivalent pk.csv — PK% par équipe"""
    logger.info("  pk.csv...")
    pk_data = fetch_all("team/penaltykill")
    rows = []
    for r in pk_data:
        name = r.get('teamFullName', '')
        rows.append({
            'Team':   name,
            'GP':     r.get('gamesPlayed', 0),
            'PK%':    round(float(r.get('penaltyKillPct') or 0.80) * 100, 1),
        })
    df = pd.DataFrame(rows)
    path = os.path.join(FOLDER_NAME, 'pk.csv')
    df.to_csv(path, index=False, encoding='utf-8-sig')
    logger.info(f"  OK — {len(df)} équipes")
    return df

def build_goalies():
    """Équivalent goalies.csv — GP, GAA, SV% par gardien"""
    logger.info("  goalies.csv...")
    data = fetch_all("goalie/summary",
                     exp=f"seasonId={SEASON_ID} and gameTypeId={GAME_TYPE}")
    rows = []
    for r in data:
        gp = r.get('gamesPlayed', 0)
        if gp == 0:
            continue
        rows.append({
            'Player':   r.get('goalieFullName', ''),
            'Team':     r.get('teamAbbrevs', ''),
            'Position': 'G',
            'GP':       gp,
            'GAA':      round(float(r.get('goalsAgainstAverage') or 0), 2),
            'SV%':      round(float(r.get('savePct') or 0), 3),
        })
    df = pd.DataFrame(rows)
    path = os.path.join(FOLDER_NAME, 'goalies.csv')
    df.to_csv(path, index=False, encoding='utf-8-sig')
    logger.info(f"  OK — {len(df)} gardiens")
    return df

def build_match_history():
    """Équivalent match.csv — historique matchs pour détection B2B"""
    logger.info("  match.csv...")
    rows = []
    for team_abbr in TEAM_FULL_TO_ABBR.values():
        url  = f"{BASE_WEB}/v1/club-schedule-season/{team_abbr}/{SEASON_ID}"
        data = api_get(url)
        if not data:
            continue
        games = data.get('games', [])
        full_name = next((k for k, v in TEAM_FULL_TO_ABBR.items() if v == team_abbr), team_abbr)
        for g in games:
            if g.get('gameState') != 'OFF' or g.get('gameType') != 2:
                continue
            date = g.get('gameDate', '')
            gid  = g.get('id', '')
            rows.append({
                'Game': f"{date} - Game {gid} {full_name} Limited Report",
                'Team': full_name,
                'Date': date,
            })
        time.sleep(0.5)

    df = pd.DataFrame(rows)
    path = os.path.join(FOLDER_NAME, 'match.csv')
    df.to_csv(path, index=False, encoding='utf-8-sig')
    logger.info(f"  OK — {len(df)} entrées")
    return df

def build_last10(all_teams):
    """Équivalent last 10.csv avec ixG et iHDCF calculés depuis PBP.
    Retourne (df, game_ids_cache) pour éviter de refetch les game_ids dans build_team_stats."""
    logger.info("  last 10.csv (via play-by-play — peut prendre 2-3 min)...")

    # Collecter les game_ids pour chaque équipe (réutilisés par compute_hdca_from_cache)
    game_ids_cache = {}
    for team_abbr in all_teams:
        game_ids_cache[team_abbr] = get_last_n_game_ids(team_abbr, n=10)

    df = compute_last10_stats(all_teams)
    df['Team'] = df['Team'].replace('', pd.NA)
    before = len(df)
    df = df.dropna(subset=['Team'])
    if before - len(df) > 0:
        logger.warning(f"  {before-len(df)} joueurs supprimés car team manquant")
    path = os.path.join(FOLDER_NAME, 'last 10.csv')
    df.to_csv(path, index=False, encoding='utf-8-sig')
    logger.info(f"  OK — {len(df)} joueurs")
    return df, game_ids_cache

def cleanup_pbp_cache():
    """Supprime les fichiers cache PBP de plus de 2 jours."""
    now = time.time()
    count = 0
    cache_dir = os.path.join(FOLDER_NAME, "cache")
    if not os.path.exists(cache_dir):
        return
    for f in os.listdir(cache_dir):
        if (f.startswith('pbp_cache_') or f.startswith('box_cache_')) and f.endswith('.json'):
            fpath = os.path.join(cache_dir, f)
            if now - os.path.getmtime(fpath) > 2 * 86400:
                os.remove(fpath)
                count += 1
    if count:
        logger.info(f"  Cache PBP: {count} fichiers supprimés")

def verify_outputs():
    files = [
        'Player Season Totals.csv', 'last 10.csv', 'power play.csv',
        'team.csv', 'on_ice.csv', 'goalies.csv', 'match.csv', 'pk.csv',
    ]
    all_ok = True
    for f in files:
        path = os.path.join(FOLDER_NAME, f)
        if not os.path.exists(path):
            logger.error(f"  MANQUANT: {f}")
            all_ok = False
        else:
            df = pd.read_csv(path)
            if len(df) == 0:
                logger.error(f"  VIDE: {f}")
                all_ok = False
            else:
                logger.info(f"  OK: {f} ({len(df)} lignes)")
    return all_ok

if __name__ == "__main__":
    logger.info("=" * 55)
    logger.info("  FICHIER_NHL — Stats 100% API NHL officielle")
    logger.info("=" * 55)

    ALL_TEAMS = list(TEAM_FULL_TO_ABBR.values())

    cleanup_pbp_cache()

    build_player_season_totals()
    build_on_ice()
    build_power_play()
    build_goalies()
    build_match_history()
    _, gid_cache = build_last10(ALL_TEAMS)       
    build_team_stats(ALL_TEAMS, game_ids_cache=gid_cache)   
    build_pk()

    logger.info("\nVérification des fichiers...")
    ok = verify_outputs()

    if ok:
        logger.info(f"\nTOUS LES FICHIERS OK dans : {os.path.abspath(FOLDER_NAME)}")
    else:
        logger.error("\n❌ Des fichiers sont manquants ou vides")
