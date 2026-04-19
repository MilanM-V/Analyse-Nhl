import requests
import sqlite3
import datetime
import time
import os
import logging
import sys

# ==========================================
# LOGGING CONFIGURATION
# ==========================================
logger = logging.getLogger("MLB-Harvester")
logger.setLevel(logging.INFO)
fmt = logging.Formatter('%(asctime)s - HARVESTER - %(levelname)s - %(message)s')
sh = logging.StreamHandler(sys.stdout)
sh.setFormatter(fmt)
logger.addHandler(sh)

DB_PATH = "mlb_database.db"

def init_db():
    logger.info("Vérification et initialisation de la base de données (mlb_database.db)...")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS mlb_batters (
            game_date TEXT,
            player_id INTEGER,
            player_name TEXT,
            team TEXT,
            opp TEXT,
            is_home INTEGER,
            ab INTEGER,
            runs INTEGER,
            hits INTEGER,
            home_runs INTEGER,
            rbi INTEGER,
            bb INTEGER,
            k INTEGER,
            avg TEXT,
            obp TEXT,
            slg TEXT,
            ops TEXT,
            UNIQUE(game_date, player_id) ON CONFLICT REPLACE
        );
        CREATE TABLE IF NOT EXISTS mlb_pitchers (
            game_date TEXT,
            player_id INTEGER,
            player_name TEXT,
            team TEXT,
            opp TEXT,
            is_home INTEGER,
            innings_pitched TEXT,
            hits INTEGER,
            runs INTEGER,
            earned_runs INTEGER,
            bb INTEGER,
            strikeouts INTEGER,
            home_runs INTEGER,
            era TEXT,
            whip TEXT,
            UNIQUE(game_date, player_id) ON CONFLICT REPLACE
        );
    """)
    conn.commit()
    conn.close()

def fetch_mlb_day(date_str: str):
    """
    Récupère les scores et stats individuelles (Boxscore) d'une journée précise.
    date_str format: YYYY-MM-DD
    """
    logger.info(f"Début du scraping MLB API pour la date : {date_str}")
    url_sched = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}"
    
    try:
        r = requests.get(url_sched, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.error(f"Erreur lors du téléchargement du schedule MLB : {e}")
        return

    if data["totalGames"] == 0:
        logger.info(f"Aucun match trouvé pour la date du {date_str}.")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    games = data["dates"][0]["games"]
    logger.info(f"-> {len(games)} matchs trouvés pour cette date.")

    for g in games:
        game_pk = g["gamePk"]
        away_team = g["teams"]["away"]["team"]["name"]
        home_team = g["teams"]["home"]["team"]["name"]

        # Boxscore API pour les stats des joueurs
        box_url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
        try:
            r_box = requests.get(box_url, timeout=10)
            if r_box.status_code != 200: continue
            box = r_box.json()
        except:
            continue

        for team_side in ["away", "home"]:
            is_home = 1 if team_side == "home" else 0
            team_name = home_team if is_home else away_team
            opp_name = away_team if is_home else home_team
            
            players = box["teams"][team_side]["players"]
            for pid_key, p_data in players.items():
                person = p_data.get("person", {})
                player_id = person.get("id")
                player_name = person.get("fullName")
                stats = p_data.get("stats", {})

                # 1. Batting Stats (Cibles: Runs, Home Runs, Hits)
                if "batting" in stats:
                    bstats = stats["batting"]
                    # On ignore ceux qui ne sont pas passés au bâton
                    if bstats.get("plateAppearances", 0) > 0:
                        c.execute("""
                            INSERT INTO mlb_batters
                            (game_date, player_id, player_name, team, opp, is_home, ab, runs, hits, home_runs, rbi, bb, k, avg, obp, slg, ops)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            date_str, player_id, player_name, team_name, opp_name, is_home,
                            bstats.get("atBats", 0), bstats.get("runs", 0), bstats.get("hits", 0),
                            bstats.get("homeRuns", 0), bstats.get("rbi", 0), bstats.get("baseOnBalls", 0),
                            bstats.get("strikeOuts", 0),
                            stats.get("seasonStats", {}).get("batting", {}).get("avg", "0.000"),
                            stats.get("seasonStats", {}).get("batting", {}).get("obp", "0.000"),
                            stats.get("seasonStats", {}).get("batting", {}).get("slg", "0.000"),
                            stats.get("seasonStats", {}).get("batting", {}).get("ops", "0.000")
                        ))

                # 2. Pitching Stats (Cibles: Strikeouts, ERA)
                if "pitching" in stats:
                    pstats = stats["pitching"]
                    # On ignore ceux qui n'ont pas lancé
                    if float(str(pstats.get("inningsPitched", "0.0"))) > 0:
                        c.execute("""
                            INSERT INTO mlb_pitchers
                            (game_date, player_id, player_name, team, opp, is_home, innings_pitched, hits, runs, earned_runs, bb, strikeouts, home_runs, era, whip)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            date_str, player_id, player_name, team_name, opp_name, is_home,
                            str(pstats.get("inningsPitched", "0.0")),
                            pstats.get("hits", 0), pstats.get("runs", 0), pstats.get("earnedRuns", 0),
                            pstats.get("baseOnBalls", 0), pstats.get("strikeOuts", 0), pstats.get("homeRuns", 0),
                            stats.get("seasonStats", {}).get("pitching", {}).get("era", "0.00"),
                            stats.get("seasonStats", {}).get("pitching", {}).get("whip", "0.00")
                        ))

    conn.commit()
    conn.close()
    logger.info(f"Données MLB du {date_str} sauvegardées avec succès !")
    sys.stdout.flush()

if __name__ == "__main__":
    init_db()

    import schedule

    def job():
        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info(f"Déclenchement automatique de la tâche MLB quotidienne du {yesterday}...")
        try:
            fetch_mlb_day(yesterday)
        except Exception as e:
            logger.error(f"Erreur inattendue pendant la tâche quotidienne : {e}")

    # Planification automatique locale tous les jours à 16h30 (Heure de ton PC)
    schedule.every().day.at("16:30").do(job)

    logger.info("=====================================================")
    logger.info("   ⚾ MLB Harvester activé (Daemon) ")
    logger.info("   L'extracteur est démarré et surveille l'heure.")
    logger.info("   Démarrage initial réussi, prochain scan à 16:30.")
    logger.info("=====================================================")
    sys.stdout.flush()

    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except KeyboardInterrupt:
            logger.info("Arrêt manuel du Harvester MLB.")
            break
        except Exception as e:
            logger.error(f"Erreur inattendue dans la boucle : {e}")
            sys.stdout.flush()
            time.sleep(60)
