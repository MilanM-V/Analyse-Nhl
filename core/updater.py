import requests
import logging
import unicodedata
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

def normalize_name(name):
    """Supprime les accents et normalise le texte pour faciliter la comparaison."""
    if not name: return ""
    # Décompose les caractères accentués (NFD) et filtre les marques de diacritiques
    normalized = unicodedata.normalize('NFD', name)
    return "".join(c for c in normalized if not unicodedata.combining(c)).strip()

def match_player_name(db_name, api_name):
    """
    db_name  : 'Alexis Lafrenière'
    api_name : 'A. Lafreniere' ou 'Alexis Lafreniere'
    """
    db_clean = normalize_name(db_name).lower()
    api_clean = normalize_name(api_name).lower()

    # 1. Correspondance exacte après normalisation
    if db_clean == api_clean:
        return True

    # 2. Correspondance Initiale + Nom (Format API classique 'J. Hughes')
    if "." in api_clean:
        parts = api_clean.split(".", 1)
        initial = parts[0].strip()
        last_name = parts[1].strip()
        
        # Vérifie si le db_name commence par l'initial et finit par le nom
        db_parts = db_clean.split()
        if len(db_parts) >= 2:
            # On vérifie l'initiale et le nom de famille (dernier mot)
            return db_clean.startswith(initial) and db_parts[-1] == last_name

    # 3. Correspondance Partielle (Initiale + Nom de famille identique)
    # Gère 'Alexander Ovechkin' vs 'Alex Ovechkin'
    db_parts = db_clean.split()
    api_parts = api_clean.split()
    if len(db_parts) >= 2 and len(api_parts) >= 2:
        return db_parts[0][0] == api_parts[0][0] and db_parts[-1] == api_parts[-1]

    return False

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

                    if team_abbrev not in goals_map:
                        goals_map[team_abbrev] = {}

                    for p in all_players:
                        name = p.get('name', {}).get('default', '')
                        g_scored = p.get('goals', 0)
                        sog_scored = p.get('shots', 0)
                        goals_map[team_abbrev][name] = {'goals': g_scored, 'shots': sog_scored}

            if not goals_map:
                logger.info(f"[Auto-ROI] Les matchs du {date_str} ne sont pas encore terminés ou indisponibles.")
                continue

            c.execute("SELECT id, joueur, equipe, verdict FROM picks WHERE date = ? AND (but IS NULL OR but = '')", (date_str,))
            picks_to_check = c.fetchall()

            for pick_id, joueur, equipe, verdict in picks_to_check:
                api_team = TEAM_MAPPING_API.get(equipe, equipe)

                if api_team in goals_map:
                    found_stats = None
                    for api_name, stats in goals_map[api_team].items():
                        if match_player_name(joueur, api_name):
                            found_stats = stats
                            break

                    if found_stats is not None:
                        if verdict == "TIREUR":
                            but_value = 1 if found_stats['shots'] >= 3 else 0
                        else:
                            but_value = 1 if found_stats['goals'] > 0 else 0
                            
                        c.execute("UPDATE picks SET but = ? WHERE id = ?", (but_value, pick_id))
                        resolved_count += 1

        except Exception as e:
            logger.error(f"[Auto-ROI] Erreur lors du fetch de la date {date_str} : {e}")

    conn.commit()
    conn.close()

    if resolved_count > 0:
        logger.info(f"[Auto-ROI] [OK] {resolved_count} pick(s) résolu(s) avec succès via API NHL !")
    return resolved_count
