import os
import sys
import pandas as pd
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(ROOT))

from mlb.core.database import DB_PATH, init_db, save_pitcher_stats_batch

def main():
    print(f"Initialisation de la base de donnees a: {DB_PATH}")
    init_db()
    
    csv_path = os.path.join(ROOT, "data", "dataset_strikeouts.csv")
    print(f"Chargement de {csv_path}...")
    
    if not os.path.exists(csv_path):
        print("Erreur : Fichier CSV non trouve.")
        return
        
    df = pd.read_csv(csv_path)
    
    # Check if 'game_pk' exists, if not create a mock one
    if 'game_pk' not in df.columns:
        df['game_pk'] = df.index
        
    if 'umpire' not in df.columns:
        df['umpire'] = None
        
    print(f"Sauvegarde de {len(df)} lignes dans SQLite...")
    save_pitcher_stats_batch(df)
    
    print("Termine.")

if __name__ == "__main__":
    main()
