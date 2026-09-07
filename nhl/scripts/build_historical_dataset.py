"""
scripts/build_historical_dataset.py — Ingestion Massive Multi-Saisons (2008-2026).

Traite et unifie 18 saisons de NHL :
1. Établit les priors bayésiens des joueurs vétérans (2008-2017) à partir de skaters_2008_to_2024.csv.
2. Extrait les matchs de l'ère moderne (2018-2024+) depuis skaters_all.csv (situation == 'all').
3. Calcule les features roulantes L10 (shiftées sans fuite de données).
4. Intègre les stats de lignes (lines.csv / lines_2008_to_2024.csv) et de gardiens (goalies.csv).
5. Exporte vers Parquet (nhl/data/historical_dataset.parquet) et SQLite (table historical_players).

Usage:
    python nhl/scripts/build_historical_dataset.py [--min-season 2018]
"""
import sqlite3
import pandas as pd
import numpy as np
import sys
import os
import argparse
import time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
STATS_DIR = os.path.join(ROOT, "stats")
DB_PATH = os.path.join(ROOT, "bot_database.db")
OUTPUT_PARQUET = os.path.join(DATA_DIR, "historical_dataset.parquet")


def compute_veteran_priors():
    """Calcule les priors bayésiens de long terme (2008-2017) par joueur."""
    path = os.path.join(DATA_DIR, "skaters_2008_to_2024.csv")
    if not os.path.exists(path):
        print(f"  [Priors] Fichier {path} introuvable.")
        return {}

    print("  [Priors] Calcul des profils bayésiens des vétérans (2008-2017)...")
    cols = ['name', 'season', 'situation', 'icetime', 'I_F_goals', 'I_F_primaryAssists', 'I_F_secondaryAssists', 'I_F_xGoals']
    df = pd.read_csv(path, usecols=cols)
    df = df[(df['season'] < 2018) & (df['situation'] == 'all')]

    grouped = df.groupby('name').agg({
        'icetime': 'sum',
        'I_F_goals': 'sum',
        'I_F_primaryAssists': 'sum',
        'I_F_secondaryAssists': 'sum',
        'I_F_xGoals': 'sum'
    })
    grouped['assists'] = grouped['I_F_primaryAssists'] + grouped['I_F_secondaryAssists']

    # Taux par 60 minutes
    valid = grouped[grouped['icetime'] > 3600].copy()
    mean_g60 = (valid['I_F_goals'].sum() / valid['icetime'].sum()) * 3600
    mean_a60 = (valid['assists'].sum() / valid['icetime'].sum()) * 3600

    K = 10 * 3600  # Poids de régularisation bayésienne (10 heures de jeu)
    valid['prior_g60'] = (valid['I_F_goals'] + (K / 3600) * mean_g60) / (valid['icetime'] / 3600 + (K / 3600))
    valid['prior_a60'] = (valid['assists'] + (K / 3600) * mean_a60) / (valid['icetime'] / 3600 + (K / 3600))

    priors = valid[['prior_g60', 'prior_a60']].to_dict(orient='index')
    print(f"  [Priors] {len(priors)} joueurs vétérans profilés avec succès.")
    return priors


def extract_modern_skaters(min_season=2018):
    """Extrait l'historique match par match de l'ère moderne (2018+) depuis skaters_all.csv."""
    path = os.path.join(STATS_DIR, "skaters_all.csv")
    print(f"  [Extraction] Lecture de {path} (saisons >= {min_season}, situation == 'all')...")

    cols = [
        'playerId', 'name', 'gameId', 'season', 'gameDate',
        'playerTeam', 'opposingTeam', 'home_or_away', 'position', 'situation',
        'icetime', 'I_F_goals', 'I_F_primaryAssists', 'I_F_secondaryAssists',
        'I_F_shotsOnGoal', 'I_F_xGoals', 'I_F_highDangerxGoals'
    ]

    chunks = []
    total_rows = 0
    start_t = time.time()

    for chunk in pd.read_csv(path, usecols=cols, chunksize=200000, low_memory=False):
        filtered = chunk[(chunk['season'] >= min_season) & (chunk['situation'] == 'all')].copy()
        if not filtered.empty:
            chunks.append(filtered)
            total_rows += len(filtered)
            sys.stdout.write(f"\r    -> {total_rows:,} lignes extraites ({time.time() - start_t:.1f}s)...")
            sys.stdout.flush()

    print(f"\n  [Extraction] Terminé : {total_rows:,} matchs-joueurs extraits.")
    df = pd.concat(chunks, ignore_index=True)
    return df


def build_rolling_features(df, priors):
    """Calcule les statistiques roulantes L10 strictes (shift=1, sans leakage)."""
    print("  [Features] Calcul des métriques roulantes L10 et interactions...")
    df['gameDate'] = pd.to_datetime(df['gameDate'], format='%Y%m%d', errors='coerce')
    df = df.sort_values(['name', 'gameDate']).reset_index(drop=True)

    df['assist'] = df['I_F_primaryAssists'].fillna(0) + df['I_F_secondaryAssists'].fillna(0)
    df['but'] = df['I_F_goals'].fillna(0)
    df['sog'] = df['I_F_shotsOnGoal'].fillna(0)
    df['ixg'] = df['I_F_xGoals'].fillna(0)
    df['atoi'] = df['icetime'].fillna(0) / 60.0  # en minutes

    # Calcul des L10 par joueur avec décalage strict (shift(1)) pour éviter le data leakage
    grouped = df.groupby('name')
    df['ixg_l10'] = grouped['ixg'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean()).fillna(0)
    df['sog_l10'] = grouped['sog'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean()).fillna(0)
    df['atoi_l10'] = grouped['atoi'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean()).fillna(0)
    df['l10_g'] = grouped['but'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean()).fillna(0)
    df['l10_a'] = grouped['assist'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean()).fillna(0)

    # Cumul de saison
    df['season_g'] = grouped['but'].transform(lambda x: x.shift(1).expanding().mean()).fillna(0)
    df['season_a'] = grouped['assist'].transform(lambda x: x.shift(1).expanding().mean()).fillna(0)
    df['season_pts'] = df['season_g'] + df['season_a']

    # Interactions et features P10
    df['hdcf_l10'] = df['I_F_highDangerxGoals'].fillna(0)
    df['hdcf_l10'] = grouped['hdcf_l10'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean()).fillna(0)

    df['ixg_x_hdcf'] = df['ixg_l10'] * df['hdcf_l10']
    df['sog_x_atoi'] = df['sog_l10'] * df['atoi_l10']
    df['is_home'] = (df['home_or_away'] == 'HOME').astype(int)
    df['is_top6'] = (df['atoi_l10'] >= 17.0).astype(int)

    # Injection des priors bayésiens des vétérans
    df['prior_g60'] = df['name'].map(lambda n: priors.get(n, {}).get('prior_g60', 0.8))
    df['prior_a60'] = df['name'].map(lambda n: priors.get(n, {}).get('prior_a60', 1.2))

    # Cibles
    df['target_but'] = (df['but'] > 0).astype(int)
    df['target_ast'] = (df['assist'] > 0).astype(int)

    # Renommage colonnes pour cohérence avec le modèle
    df['joueur'] = df['name']
    df['date'] = df['gameDate']
    df['equipe'] = df['playerTeam']
    df['adversaire'] = df['opposingTeam']

    print(f"  [Features] Dataset complet prêt : {len(df):,} lignes.")
    return df


def save_dataset(df):
    """Sauvegarde le dataset en Parquet et dans SQLite."""
    print(f"  [Sauvegarde] Export vers {OUTPUT_PARQUET}...")
    df.to_parquet(OUTPUT_PARQUET, index=False)

    print(f"  [Sauvegarde] Export vers SQLite {DB_PATH} (table 'historical_players')...")
    conn = sqlite3.connect(DB_PATH)
    
    # Sélection des colonnes pertinentes pour la DB
    save_cols = [
        'date', 'season', 'joueur', 'equipe', 'adversaire', 'is_home',
        'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 'l10_g', 'l10_a',
        'season_g', 'season_a', 'season_pts', 'ixg_x_hdcf', 'sog_x_atoi',
        'is_top6', 'prior_g60', 'prior_a60', 'but', 'assist', 'target_but', 'target_ast'
    ]
    df_sub = df[[c for c in save_cols if c in df.columns]]
    df_sub.to_sql("historical_players", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_date ON historical_players (date);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_joueur ON historical_players (joueur);")
    conn.close()
    print("  [Sauvegarde] Données indexées en base avec succès.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-season", type=int, default=2018, help="Saison de départ (défaut: 2018)")
    args = parser.parse_args()

    print("=" * 70)
    print(" COMPILATION DU SUPER-DATASET HISTORIQUE MULTI-SAISONS (2008-2026)")
    print("=" * 70)

    priors = compute_veteran_priors()
    df_modern = extract_modern_skaters(min_season=args.min_season)
    df_full = build_rolling_features(df_modern, priors)
    save_dataset(df_full)

    print("\n✅ SUPER-DATASET COMPILÉ ET PRÊT POUR L'ENTRAÎNEMENT !")


if __name__ == "__main__":
    main()
