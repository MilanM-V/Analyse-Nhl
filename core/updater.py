import requests
import logging
from datetime import datetime
from  core.database import get_connection

logger = logging.getLogger("NHL_Bot")

TEAM_MAPPING_API = {
    'ANA': 'ANA', 'BOS': 'BOS', 'BUF': 'BUF', 'CGY': 'CGY',
    'CAR': 'CAR', 'CHI': 'CHI', 'COL': 'COL', 'CBJ': 'CBJ',
    'DAL': 'DAL', 'DET': 'DET', 'EDM': 'EDM', 'FLA': 'FLA',
    'LAK': 'LAK', 'MIN': 'MIN', 'MTL': 'MTL', 'NSH': 'NSH',
    'NJD': 'NJD', 'NYI': 'NYI', 'NYR': 'NYR', 'OTT': 'OTT',
    'PHI': 'PHI', 'PIT': 'PIT', 'SJS': 'SJS', 'SEA': 'SEA',
    'STL': 'STL', 'TBL': 'TBL', 'TOR': 'TOR', 'VAN': 'VAN',
    'VGK': 'VGK', 'WSH': 'WSH', 'WPG': 'WPG', 'UTA': 'UTA'
}

def match_player_name(db_name, api_name):
    """
    db_name  : 'Alex Ovechkin'
    api_name : 'A. Ovechkin'
    """
    api_clean = api_name.strip()
    if "." in api_clean:
        initial = api_clean.split(".")[0].strip()
        last_name = api_clean.split(".")[1].strip()
        return db_name.startswith(initial) and db_name.endswith(last_name)
    else:
        return db_name.lower() == api_name.lower()

def update_pending_picks():
    """
    Scan la DB pour trouver les dates non-résolues (but IS NULL)
    et interroge l'API NHL pour valider si but=1 ou but=0.
    """
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT DISTINCT date FROM picks WHERE but IS NULL OR but = ''")
    dates_to_check = [r[0] for r in c.fetchall()]

    if not dates_to_check:
        logger.info("[Auto-ROI] Aucune donnée en attente de résolution.")
        conn.close()
        return 0

    logger.info(f"[Auto-ROI] Validation des résultats pour {len(dates_to_check)} date(s)...")

    resolved_count = 0

    for date_str in dates_to_check:
        try:

            sched = requests.get(f"https://api-web.nhle.com/v1/schedule/{date_str}", timeout=10).json()
            games = []
            for gw in sched.get("gameWeek", []):
                if gw["date"] == date_str:
                    games = gw.get("games", [])
                    break

            goals_map = {}
            for g in games:
                if g.get("gameState") not in ('OFF', 'FINAL', 'FINAL_OT', 'FINAL_SO'):
                    continue                         

                gid = g["id"]
                try:
                    box = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore", timeout=10).json()
                except:
                    continue

                for side in ["homeTeam", "awayTeam"]:
                    team_abbrev = g[side]["abbrev"]
                    players_data = box.get('playerByGameStats', {}).get(side, {})
                    all_players = players_data.get('forwards', []) + players_data.get('defense', [])

                    for p in all_players:
                        name = p.get('name', {}).get('default', '')
                        g_scored = p.get('goals', 0)

                        if team_abbrev not in goals_map:
                            goals_map[team_abbrev] = {}

                        goals_map[team_abbrev][name] = g_scored

            if not goals_map:
                logger.info(f"[Auto-ROI] Les matchs du {date_str} ne sont pas encore terminés ou indisponibles.")
                continue

            c.execute("SELECT id, joueur, equipe FROM picks WHERE date = ? AND (but IS NULL OR but = '')", (date_str,))
            picks_to_check = c.fetchall()

            for pick_id, joueur, equipe in picks_to_check:
                api_team = TEAM_MAPPING_API.get(equipe, equipe)

                if api_team in goals_map:

                    found_goals = None
                    for api_name, nb_goals in goals_map[api_team].items():
                        if match_player_name(joueur, api_name):
                            found_goals = nb_goals
                            break

                    if found_goals is not None:
                        but_value = 1 if found_goals > 0 else 0
                        c.execute("UPDATE picks SET but = ? WHERE id = ?", (but_value, pick_id))
                        resolved_count += 1

        except Exception as e:
            logger.error(f"[Auto-ROI] Erreur lors du fetch de la date {date_str} : {e}")

    conn.commit()
    conn.close()

    if resolved_count > 0:
        logger.info(f"[Auto-ROI] [OK] {resolved_count} pick(s) résolu(s) avec succès via API NHL !")
    return resolved_count
