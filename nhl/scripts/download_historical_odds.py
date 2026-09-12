import argparse
import requests
import sqlite3
import json
import os
import sys
import logging
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("OddsDownloader")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT_DIR, "nhl", "data", "odds")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "historical_odds.db")

load_dotenv(os.path.join(ROOT_DIR, ".env"))

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_cache (
            snapshot_time TEXT,
            event_id TEXT,
            json_response TEXT,
            downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (snapshot_time, event_id)
        )
    ''')
    conn.commit()
    conn.close()

def is_cached(snapshot_time, event_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT json_response FROM api_cache WHERE snapshot_time = ? AND event_id = ?", (snapshot_time, event_id))
    result = cursor.fetchone()
    conn.close()
    if not result:
        return False
    if event_id == "EVENTS":
        return True
    try:
        data = json.loads(result[0])
        match_data = data.get("data", {})
        if "bookmakers" not in match_data or not match_data["bookmakers"]:
            return True
        for bm in match_data.get("bookmakers", []):
            for m in bm.get("markets", []):
                if m.get("key") == "player_points":
                    return True
        return False # Missing player_points, needs redownload
    except:
        return True

def save_to_cache(snapshot_time, event_id, json_data):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO api_cache (snapshot_time, event_id, json_response) VALUES (?, ?, ?)",
                   (snapshot_time, event_id, json.dumps(json_data)))
    conn.commit()
    conn.close()

def fetch_events_for_date(api_key, snapshot_time):
    """Récupère la liste des événements actifs pour une date (à midi UTC)."""
    # On vérifie si la liste des matchs de ce jour est en cache
    if is_cached(snapshot_time, "EVENTS"):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT json_response FROM api_cache WHERE snapshot_time = ? AND event_id = ?", (snapshot_time, "EVENTS"))
        cached_data = cursor.fetchone()[0]
        conn.close()
        return json.loads(cached_data).get('data', [])

    url = f"https://api.the-odds-api.com/v4/historical/sports/icehockey_nhl/events"
    params = {'apiKey': api_key, 'date': snapshot_time}
    res = requests.get(url, params=params)
    if res.status_code != 200:
        logger.error(f"Erreur API Events {res.status_code}: {res.text}")
        return []
    
    data = res.json()
    save_to_cache(snapshot_time, "EVENTS", data)
    return data.get('data', [])

def fetch_event_odds(api_key, event_id, snapshot_time):
    """Télécharge les Player Props pour un événement à une minute précise."""
    if is_cached(snapshot_time, event_id):
        logger.info(f"⏭️ Cache utilisé pour {event_id} à {snapshot_time}")
        return True, 'N/A'

    url = f"https://api.the-odds-api.com/v4/historical/sports/icehockey_nhl/events/{event_id}/odds"
    params = {
        'apiKey': api_key,
        'regions': 'us,eu', 
        'markets': 'player_goal_scorer_anytime,player_assists,player_points',
        'date': snapshot_time,
        'oddsFormat': 'decimal'
    }

    res = requests.get(url, params=params)
    
    if res.status_code in (404, 422):
        # Marché indisponible ou événement annulé/déplacé. On l'ignore sans planter.
        logger.warning(f"Marché/Event indisponible pour l'événement {event_id} (Code {res.status_code}). On passe.")
        save_to_cache(snapshot_time, event_id, {})
        return True, 'N/A'

    if res.status_code != 200:
        logger.error(f"Erreur API HTTP {res.status_code}: {res.text}")
        return False, 'N/A'

    data = res.json()
    save_to_cache(snapshot_time, event_id, data)
    
    req_used = res.headers.get('x-requests-used', 'N/A')
    req_rem = res.headers.get('x-requests-remaining', 'N/A')
    logger.info(f"✅ Téléchargé: {event_id} | Crédits restants: {req_rem}")
    
    return True, req_used

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--full", action="store_true", help="Lance le téléchargement massif")
    parser.add_argument("--limit-credits", type=int, default=10000, help="Limite maximale de crédits à consommer lors de cette exécution")
    args = parser.parse_args()

    api_key = os.getenv("api_odds")
    if not api_key:
        sys.exit(1)

    init_db()

    if args.test:
        logger.info("Test déjà validé.")
        sys.exit(0)

    if args.full:
        start_date = datetime(2023, 5, 3)
        end_date = datetime.now()
        
        current_date = start_date
        total_days = (end_date - start_date).days
        
        logger.info(f"🚀 DÉMARRAGE DU TÉLÉCHARGEMENT MASSIF ({total_days} jours à traiter)")
        logger.info(f"🛑 Limite de crédits pour cette session: {args.limit_credits}")
        
        initial_requests_used = None

        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            logger.info(f"\n--- Traitement de la journée du {date_str} ---")
            
            snapshot_events = f"{date_str}T12:00:00Z"
            events = fetch_events_for_date(api_key, snapshot_events)
            if not events:
                logger.info("Aucun match ce jour.")
                current_date += timedelta(days=1)
                continue
                
            for event in events:
                # Calculer la "Closing Line" : 10 minutes avant le début du match
                try:
                    commence_dt = datetime.strptime(event['commence_time'], "%Y-%m-%dT%H:%M:%SZ")
                    target_snapshot = (commence_dt - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception as e:
                    logger.error(f"Erreur de date pour {event['id']}: {e}")
                    continue
                
                success, req_used = fetch_event_odds(api_key, event['id'], target_snapshot)
                if not success:
                    logger.error("Arrêt du script suite à une erreur (plus de crédits ou ban IP ?)")
                    sys.exit(1)
                
                if req_used != 'N/A':
                    if initial_requests_used is None:
                        initial_requests_used = int(req_used)
                    
                    session_used = int(req_used) - initial_requests_used
                    if session_used >= args.limit_credits:
                        logger.warning(f"🛑 Limite de crédits atteinte ({session_used} >= {args.limit_credits}). Arrêt du script.")
                        sys.exit(0)

                time.sleep(0.2) # Courtoisie pour ne pas surcharger l'API (5 requêtes/sec max)

            current_date += timedelta(days=1)
            
        logger.info("\n🎉 TÉLÉCHARGEMENT TERMINÉ AVEC SUCCÈS ! Les données sont sécurisées dans SQLite.")

if __name__ == "__main__":
    main()
