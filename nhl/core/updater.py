import requests
import logging
import unicodedata
import os
import sys
from datetime import datetime

# Ajout du dossier racine au sys.path pour permettre l'exécution standalone
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from  core.database import get_connection
from core.services import safe_get

logger = logging.getLogger("NHL_Bot")

# Import centralisé depuis la source unique
from config.constants import ALL_ABBRS

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

    c.execute("""
        SELECT DISTINCT date FROM picks WHERE but IS NULL OR but = ''
        UNION
        SELECT DISTINCT date FROM picks_assists WHERE assist IS NULL OR assist = ''
        UNION
        SELECT DISTINCT date FROM picks_points WHERE point IS NULL OR point = ''
    """)
    dates_to_check = [r[0] for r in c.fetchall()]

    if not dates_to_check:
        logger.info("[Auto-ROI] Aucune donnée en attente de résolution.")
        conn.close()
        return 0

    logger.info(f"[Auto-ROI] Validation des résultats pour {len(dates_to_check)} date(s)...")

    resolved_count = 0

    for date_str in dates_to_check:
        try:
            sched_resp = safe_get(f"https://api-web.nhle.com/v1/schedule/{date_str}", timeout=10)
            sched = sched_resp.json()
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
                    box_resp = safe_get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore", timeout=10)
                    box = box_resp.json()
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
                        goals_map[team_abbrev][name] = {
                            'goals': p.get('goals', 0),
                            'assists': p.get('assists', 0),
                            'points': p.get('points', 0),
                            'shots': p.get('shots', 0)
                        }

            if not goals_map:
                logger.info(f"[Auto-ROI] Les matchs du {date_str} ne sont pas encore terminés ou indisponibles.")
                continue

            # 1. Update table 'picks' (BUTS)
            c.execute("SELECT id, joueur, equipe, verdict FROM picks WHERE date = ? AND (but IS NULL OR but = '')", (date_str,))
            for pick_id, joueur, equipe, verdict in c.fetchall():
                if equipe in goals_map:
                    for api_name, stats in goals_map[equipe].items():
                        if match_player_name(joueur, api_name):
                            val = 1 if stats['goals'] > 0 else 0
                            c.execute("UPDATE picks SET but = ? WHERE id = ?", (val, pick_id))
                            resolved_count += 1
                            break

            # 2. Update table 'picks_assists'
            c.execute("SELECT id, joueur, equipe FROM picks_assists WHERE date = ? AND (assist IS NULL OR assist = '')", (date_str,))
            for pick_id, joueur, equipe in c.fetchall():
                if equipe in goals_map:
                    for api_name, stats in goals_map[equipe].items():
                        if match_player_name(joueur, api_name):
                            val = 1 if stats['assists'] > 0 else 0
                            c.execute("UPDATE picks_assists SET assist = ? WHERE id = ?", (val, pick_id))
                            resolved_count += 1
                            break

            # 3. Update table 'picks_points'
            c.execute("SELECT id, joueur, equipe FROM picks_points WHERE date = ? AND (point IS NULL OR point = '')", (date_str,))
            for pick_id, joueur, equipe in c.fetchall():
                if equipe in goals_map:
                    for api_name, stats in goals_map[equipe].items():
                        if match_player_name(joueur, api_name):
                            val = 1 if stats['points'] > 0 else 0
                            c.execute("UPDATE picks_points SET point = ? WHERE id = ?", (val, pick_id))
                            resolved_count += 1
                            break

            # 4. Update unified 'players' table
            c.execute("SELECT id, joueur, equipe FROM players WHERE date = ? AND (but IS NULL OR but = '')", (date_str,))
            for p_id, joueur, equipe in c.fetchall():
                if equipe in goals_map:
                    for api_name, stats in goals_map[equipe].items():
                        if match_player_name(joueur, api_name):
                            c.execute("UPDATE players SET but = ?, assist = ?, point = ? WHERE id = ?", 
                                      (stats['goals'], stats['assists'], stats['points'], p_id))
                            break

        except Exception as e:
            logger.error(f"[Auto-ROI] Erreur lors du fetch de la date {date_str} : {e}")

    conn.commit()
    conn.close()

    if resolved_count > 0:
        logger.info(f"[Auto-ROI] [OK] {resolved_count} pick(s) résolu(s) avec succès via API NHL !")
    return resolved_count

async def log_closing_lines() -> None:
    """
    (V18.2) Scrape the current odds for today's unresolved picks and update their closing_cote.
    Can be run as a cron job 10 minutes before matches start to get the actual CLV.
    """
    import asyncio
    from core.database import get_connection
    from core.odds_scraper import fetch_multiple_odds
    
    logger.info("[CLV] Démarrage du tracking des cotes de clôture (Closing Lines)...")
    from datetime import datetime
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    conn = get_connection()
    c = conn.cursor()
    
    # Collect unsolved picks for today
    players_to_check = set()
    for table in ["picks", "picks_assists", "picks_points"]:
        col = table.split('_')[-1] if '_' in table else "but"
        # Check all non-resolved
        c.execute(f"SELECT joueur FROM {table} WHERE date = ? AND ({col} IS NULL OR {col} = '')", (today_str,))
        for row in c.fetchall():
            players_to_check.add(row[0])
            
    if not players_to_check:
        logger.info("[CLV] Aucun match en attente pour récupérer les Closing Lines.")
        conn.close()
        return
        
    logger.info(f"[CLV] Vérification de {len(players_to_check)} joueurs...")
    p_list = list(players_to_check)
    odds_map = await fetch_multiple_odds(p_list)
    
    if not odds_map:
        logger.warning("[CLV] Échec du scraping ou aucune cote trouvée.")
        conn.close()
        return
        
    # Update DB
    updates = 0
    for player in odds_map:
        data = odds_map[player]
        g_cote = data.get("BUTS")
        a_cote = data.get("ASSISTS")
        p_cote = data.get("POINTS")
        
        if g_cote:
            c.execute("UPDATE picks SET closing_cote = ? WHERE joueur = ? AND date = ? AND (but IS NULL OR but = '')", (g_cote, player, today_str))
        if a_cote:
            c.execute("UPDATE picks_assists SET closing_cote = ? WHERE joueur = ? AND date = ? AND (assist IS NULL OR assist = '')", (a_cote, player, today_str))
        if p_cote:
            c.execute("UPDATE picks_points SET closing_cote = ? WHERE joueur = ? AND date = ? AND (point IS NULL OR point = '')", (p_cote, player, today_str))
            
        updates += 1
        
    conn.commit()
    conn.close()
    logger.info(f"[CLV] Terminé ! {updates} profils de cotes de clôture mis à jour dans la base.")

