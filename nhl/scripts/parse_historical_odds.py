import sqlite3
import json
import pandas as pd
import os
import unicodedata
import string
import numpy as np

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(ROOT_DIR, "nhl", "data", "odds")
DB_PATH = os.path.join(DATA_DIR, "historical_odds.db")
OUTPUT_CSV = os.path.join(DATA_DIR, "historical_odds_parsed.csv")

def normalize_name(name):
    """Normalise un nom pour faciliter le matching (minuscules, sans accents, sans ponctuation)."""
    if not isinstance(name, str):
        return ""
    # Enlever les accents
    name = ''.join(c for c in unicodedata.normalize('NFD', name) if unicodedata.category(c) != 'Mn')
    name = name.lower()
    # Remplacer la ponctuation par des espaces
    for p in string.punctuation:
        name = name.replace(p, ' ')
    # Garder seulement nom et prénom (gérer les cas comme "Alex Ovechkin" vs "Alexander Ovechkin")
    parts = name.split()
    if len(parts) >= 2:
        # On renvoie la première lettre du prénom + nom complet pour maximiser le match
        # ex: "c mcdavid" au lieu de "connor mcdavid"
        return f"{parts[0][0]} {' '.join(parts[1:])}"
    return name.replace(' ', '')

def parse_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT json_response FROM api_cache WHERE event_id != 'EVENTS'")
    rows = cursor.fetchall()
    conn.close()

    print(f"Extraction de {len(rows)} matchs depuis SQLite...")

    records = []
    
    for row in rows:
        data_root = json.loads(row[0])
        if not data_root or 'data' not in data_root:
            continue
            
        match_data = data_root['data']
        if not match_data or 'bookmakers' not in match_data:
            continue
            
        commence_time = match_data.get('commence_time')
        if not commence_time:
            continue
            
        dt = pd.to_datetime(commence_time)
        if dt.tzinfo is None:
            dt = dt.tz_localize('UTC')
        date_str = dt.tz_convert('US/Eastern').strftime('%Y-%m-%d')
        
        # Structure temporaire pour grouper les cotes par joueur et marché
        # player_name -> market -> [prices]
        match_odds = {}
        
        for bookmaker in match_data.get('bookmakers', []):
            for market in bookmaker.get('markets', []):
                market_key = market.get('key')
                # Simplifier le nom du marché pour correspondre à notre dataset ("but", "ast", "pts")
                market_name = "but" if "goal" in market_key else "ast" if "assist" in market_key else "pts" if "points" in market_key else market_key
                
                for outcome in market.get('outcomes', []):
                    outcome_type = outcome.get('name', '')
                    
                    # Ignorer les paris Under/No (on ne cherche que l'Over/Anytime Yes)
                    if outcome_type not in ('Over', 'Yes'):
                        continue
                        
                    player_raw = outcome.get('description', '')
                    if not player_raw:
                        continue
                        
                    price = outcome.get('price')
                        
                    norm_name = normalize_name(player_raw)
                    
                    if norm_name not in match_odds:
                        match_odds[norm_name] = {}
                    if market_name not in match_odds[norm_name]:
                        match_odds[norm_name][market_name] = []
                        
                    match_odds[norm_name][market_name].append(price)
                    
        # Agréger par la médiane
        for norm_name, markets in match_odds.items():
            for mkt, prices in markets.items():
                if prices:
                    median_price = np.median(prices)
                    records.append({
                        'date': date_str,
                        'player_norm': norm_name,
                        'market': mkt,
                        'median_odds': median_price,
                        'implied_prob': 1.0 / median_price
                    })
                    
    df = pd.DataFrame(records)
    print(f"Génération de {len(df)} cotes unifiées.")
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Sauvegardé dans {OUTPUT_CSV}")

if __name__ == "__main__":
    parse_db()
