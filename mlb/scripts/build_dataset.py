"""
mlb/scripts/build_dataset.py — Création du dataset historique pour l'entraînement MLB (V2).

Ce script utilise pybaseball.statcast pour télécharger les données "pitch-by-pitch" 
sur une période donnée, et les aggréger par match et par lanceur pour trouver 
le nombre total de Strikeouts réalisés.

V2 : Ajout des variables Umpire, Vélocité, Spin Rate et Swinging Strike %.
"""

import os
import pandas as pd
import numpy as np
from pybaseball import statcast
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("MLB-Dataset")

def build_strikeout_dataset(start_date: str, end_date: str):
    """
    Télécharge les données Statcast, agrège les strikeouts par lanceur et sauvegarde en CSV.
    
    V2 Features ajoutées :
    - umpire : Nom de l'arbitre du match.
    - avg_release_speed : Vélocité moyenne du lanceur (mph).
    - avg_spin_rate : Spin rate moyen du lanceur (RPM).
    - swinging_strike_pct : % de swinging strikes (whiffs) du lanceur dans ce match.
    """
    logger.info(f"Téléchargement des données Statcast du {start_date} au {end_date}... (Cela peut prendre quelques minutes)")
    
    try:
        # Téléchargement des données pitch-by-pitch
        df = statcast(start_dt=start_date, end_dt=end_date)
    except Exception as e:
        logger.error(f"Erreur lors du téléchargement : {e}")
        return
        
    if df.empty:
        logger.warning("Aucune donnée trouvée pour cette période.")
        return
        
    logger.info(f"{len(df)} lancers (pitches) téléchargés. Traitement en cours...")
    
    # --- STATCAST V2 FEATURES (calculées AVANT le filtrage par events) ---
    # Ces métriques sont calculées sur TOUS les lancers, pas seulement les at-bats terminés.
    
    # Swinging Strike : description == 'swinging_strike' ou 'swinging_strike_blocked'
    df['is_swinging_strike'] = df['description'].isin([
        'swinging_strike', 'swinging_strike_blocked', 'foul_tip'
    ]).astype(int)
    
    # Agrégation des métriques Statcast par match + lanceur (tous les lancers)
    pitch_stats = df.groupby(['game_date', 'game_pk', 'pitcher', 'player_name']).agg(
        total_pitches=('description', 'count'),
        swinging_strikes=('is_swinging_strike', 'sum'),
        avg_release_speed=('release_speed', 'mean'),
        avg_spin_rate=('release_spin_rate', 'mean'),
        umpire=('umpire', 'first'),
    ).reset_index()
    
    pitch_stats['swinging_strike_pct'] = np.where(
        pitch_stats['total_pitches'] > 0,
        pitch_stats['swinging_strikes'] / pitch_stats['total_pitches'],
        0
    )
    
    # --- EVENTS (fin de passage au bâton) pour compter les Strikeouts ---
    events_df = df.dropna(subset=['events']).copy()
    events_df['is_strikeout'] = (events_df['events'] == 'strikeout').astype(int)
    
    # Agrégation par match (game_pk) et par lanceur (pitcher)
    dataset = events_df.groupby(['game_date', 'game_pk', 'pitcher', 'player_name']).agg(
        total_batters_faced=('events', 'count'),
        strikeouts=('is_strikeout', 'sum'),
        home_team=('home_team', 'first'),
        away_team=('away_team', 'first'),
        inning_topbot=('inning_topbot', 'first') # Top = away batting, Bot = home batting
    ).reset_index()
    
    # --- MERGE des features Statcast dans le dataset principal ---
    merge_keys = ['game_date', 'game_pk', 'pitcher', 'player_name']
    dataset = dataset.merge(
        pitch_stats[merge_keys + ['avg_release_speed', 'avg_spin_rate', 'swinging_strike_pct', 'umpire']],
        on=merge_keys,
        how='left'
    )
    
    # Déduire l'équipe du lanceur et l'équipe adverse
    def assign_teams(row):
        # Si le lanceur lance dans le 'Top' de la manche, il est dans l'équipe 'Home'
        if row['inning_topbot'] == 'Top':
            pitcher_team = row['home_team']
            opp_team = row['away_team']
        else:
            pitcher_team = row['away_team']
            opp_team = row['home_team']
            
        return pd.Series([pitcher_team, opp_team, pitcher_team == row['home_team']])
        
    dataset[['pitcher_team', 'opp_team', 'is_home']] = dataset.apply(assign_teams, axis=1)
    
    # On filtre pour ne garder que les lanceurs partants (Starting Pitchers).
    # Règle simple : un SP affronte généralement au moins 15 batteurs par match.
    sp_dataset = dataset[dataset['total_batters_faced'] >= 15].copy()
    
    # Nettoyage et sélection des colonnes utiles pour la BDD et XGBoost V2
    final_df = sp_dataset[[
        'game_date', 'game_pk', 'pitcher', 'player_name', 'pitcher_team', 'opp_team', 'is_home', 
        'total_batters_faced', 'strikeouts',
        'avg_release_speed', 'avg_spin_rate', 'swinging_strike_pct', 'umpire'
    ]].sort_values('game_date', ascending=True)
    
    # Remplir les NaN numériques
    for col in ['avg_release_speed', 'avg_spin_rate', 'swinging_strike_pct']:
        final_df[col] = final_df[col].fillna(final_df[col].median())
    
    # Sauvegarde dans SQLite
    from mlb.core.database import init_db, save_pitcher_stats_batch
    init_db()
    save_pitcher_stats_batch(final_df)
    
    # Stats du dataset
    n_umpires = final_df['umpire'].nunique()
    avg_velo = final_df['avg_release_speed'].mean()
    logger.info("✅ Mise à jour SQLite terminée.")
    logger.info(f"   📊 {len(final_df)} matchs de lanceurs partants ajoutés.")
    logger.info(f"   ⚡ Vélocité moyenne : {avg_velo:.1f} mph (avec {n_umpires} arbitres)")

if __name__ == "__main__":
    from mlb.core.database import init_db, get_latest_game_date
    init_db()
    
    latest_date = get_latest_game_date()
    from datetime import datetime, timedelta
    
    if latest_date:
        start_date = (datetime.strptime(latest_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info(f"Dernière date en base : {latest_date}. Reprise au {start_date}")
    else:
        # Initialisation sur le début de la saison
        start_date = "2024-03-28"
        
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    if start_date <= end_date:
        build_strikeout_dataset(start_date, end_date)
    else:
        logger.info("Base de données déjà à jour.")
