"""
mlb/core/database.py — Gestion de la base de données SQLite MLB.

Gère le stockage persistant des statistiques Statcast (historique des lancers)
pour éviter de tout retélécharger à chaque entraînement.
"""

import sqlite3
import os
import pandas as pd
import logging
from typing import List

logger = logging.getLogger("MLB_DB")

# Chemin vers la base de données SQLite MLB
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DB_DIR, "mlb_database.db")

def init_db():
    """Initialise la base de données SQLite et crée les tables si nécessaires."""
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Table HistoricalPitcherStats (aggrégation par match et par lanceur)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS HistoricalPitcherStats (
        game_date TEXT,
        game_pk INTEGER,
        pitcher INTEGER,
        player_name TEXT,
        pitcher_team TEXT,
        opp_team TEXT,
        is_home INTEGER,
        total_batters_faced INTEGER,
        strikeouts INTEGER,
        avg_release_speed REAL,
        avg_spin_rate REAL,
        swinging_strike_pct REAL,
        umpire TEXT,
        PRIMARY KEY (game_pk, pitcher)
    )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Base de données MLB initialisée avec succès.")

def save_pitcher_stats_batch(df: pd.DataFrame):
    """
    Insère ou met à jour un batch de statistiques de lanceurs dans la base de données.
    Args:
        df: DataFrame contenant les colonnes exactes de la table HistoricalPitcherStats.
    """
    if df.empty:
        return
        
    conn = sqlite3.connect(DB_PATH)
    
    # On s'assure que les colonnes du DataFrame correspondent exactement à la table
    cols = [
        'game_date', 'game_pk', 'pitcher', 'player_name', 'pitcher_team', 'opp_team', 
        'is_home', 'total_batters_faced', 'strikeouts', 'avg_release_speed', 
        'avg_spin_rate', 'swinging_strike_pct', 'umpire'
    ]
    
    # Remplir les colonnes manquantes avec des NaN/Null
    for c in cols:
        if c not in df.columns:
            df[c] = None
            
    df_to_insert = df[cols]
    
    try:
        df_to_insert.to_sql('HistoricalPitcherStats', conn, if_exists='append', index=False)
        logger.info(f"{len(df)} entrées ajoutées à la base de données SQLite.")
    except sqlite3.IntegrityError:
        # En cas de doublons (game_pk, pitcher), on gère ligne par ligne via REPLACE
        logger.info("Doublons détectés, mise à jour via REPLACE...")
        records = df_to_insert.to_dict('records')
        cursor = conn.cursor()
        
        sql = '''
        INSERT OR REPLACE INTO HistoricalPitcherStats 
        (game_date, game_pk, pitcher, player_name, pitcher_team, opp_team, is_home, total_batters_faced, strikeouts, avg_release_speed, avg_spin_rate, swinging_strike_pct, umpire)
        VALUES (:game_date, :game_pk, :pitcher, :player_name, :pitcher_team, :opp_team, :is_home, :total_batters_faced, :strikeouts, :avg_release_speed, :avg_spin_rate, :swinging_strike_pct, :umpire)
        '''
        cursor.executemany(sql, records)
        conn.commit()
        logger.info(f"{len(records)} entrées mises à jour dans SQLite.")
        
    conn.close()

def load_all_pitcher_stats() -> pd.DataFrame:
    """
    Charge l'intégralité de l'historique des lanceurs pour l'entraînement du modèle.
    Returns:
        DataFrame contenant tout l'historique.
    """
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM HistoricalPitcherStats ORDER BY player_name, game_date", conn)
    conn.close()
    return df

def get_latest_game_date() -> str:
    """Récupère la date du dernier match en base pour faire une mise à jour incrémentale."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(game_date) FROM HistoricalPitcherStats")
    result = cursor.fetchone()[0]
    conn.close()
    return result if result else None
