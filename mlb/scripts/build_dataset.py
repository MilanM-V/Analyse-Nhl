"""
mlb/scripts/build_dataset.py — Création du dataset historique pour l'entraînement MLB.

Ce script utilise pybaseball.statcast pour télécharger les données "pitch-by-pitch" 
sur une période donnée, et les aggréger par match et par lanceur pour trouver 
le nombre total de Strikeouts réalisés.
"""

import os
import pandas as pd
from pybaseball import statcast
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("MLB-Dataset")

def build_strikeout_dataset(start_date: str, end_date: str, output_csv: str):
    """
    Télécharge les données Statcast, agrège les strikeouts par lanceur et sauvegarde en CSV.
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
    
    # On ne s'intéresse qu'aux événements de fin de passage au bâton (strikeout, hit, walk, etc.)
    events_df = df.dropna(subset=['events']).copy()
    
    # Création d'une colonne binaire 1/0 pour les strikeouts
    events_df['is_strikeout'] = (events_df['events'] == 'strikeout').astype(int)
    
    # Agrégation par match (game_pk) et par lanceur (pitcher)
    # On récupère aussi le nom du lanceur, l'équipe au bâton (batter team) et l'équipe au lancer
    dataset = events_df.groupby(['game_date', 'game_pk', 'pitcher', 'player_name']).agg(
        total_batters_faced=('events', 'count'),
        strikeouts=('is_strikeout', 'sum'),
        home_team=('home_team', 'first'),
        away_team=('away_team', 'first'),
        inning_topbot=('inning_topbot', 'first') # Top = away batting, Bot = home batting
    ).reset_index()
    
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
    
    # Nettoyage et sélection des colonnes utiles pour XGBoost
    final_df = sp_dataset[[
        'game_date', 'player_name', 'pitcher_team', 'opp_team', 'is_home', 
        'total_batters_faced', 'strikeouts'
    ]].sort_values('game_date', ascending=True)
    
    # Sauvegarde
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    final_df.to_csv(output_csv, index=False)
    logger.info(f"Dataset créé avec succès : {output_csv} ({len(final_df)} matchs de lanceurs partants)")

if __name__ == "__main__":
    # Téléchargement de 3 mois entiers de la saison 2024 pour avoir un dataset robuste
    build_strikeout_dataset("2024-03-28", "2024-06-30", "mlb/data/dataset_strikeouts.csv")
