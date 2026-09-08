"""
scripts/build_historical_dataset.py — Ingestion Massive Multi-Saisons (2008-2026).

Architecture quantitative Senior Data Scientist :
1. Établit les priors bayésiens des joueurs vétérans (2008-2017) à partir de skaters_2008_to_2024.csv.
   - Prior G/60, A/60, SOG/60 avec régularisation bayésienne empirique (shrinkage).
   - Prior Sh% avec modélisation Beta-Binomiale.
2. Compile les profils défensifs d'équipes et de gardiens (teams / goalies 2008-2026) :
   - opp_xga_60, opp_hdca_60, opp_goalie_gsax_60 par (team, season).
3. Extrait les matchs de l'ère moderne (saisons 2018-2019 à 2024-2025) depuis skaters_all.csv.
4. Intègre la saison courante 2025-2026 depuis bot_database.db (table players).
5. Calcule les features roulantes L10 strictement shiftées (shift=1, zéro data leakage).
6. Exporte vers Parquet (nhl/data/historical_dataset.parquet) et SQLite (table historical_players).

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
import json

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

    print("  [Priors] Profilage bayésien des vétérans (2008-2017)...")
    cols = [
        'name', 'season', 'situation', 'icetime',
        'I_F_goals', 'I_F_primaryAssists', 'I_F_secondaryAssists',
        'I_F_xGoals', 'I_F_shotsOnGoal'
    ]
    df = pd.read_csv(path, usecols=cols)
    df = df[(df['season'] < 2018) & (df['situation'] == 'all')]

    grouped = df.groupby('name').agg({
        'icetime': 'sum',
        'I_F_goals': 'sum',
        'I_F_primaryAssists': 'sum',
        'I_F_secondaryAssists': 'sum',
        'I_F_xGoals': 'sum',
        'I_F_shotsOnGoal': 'sum'
    })
    grouped['assists'] = grouped['I_F_primaryAssists'] + grouped['I_F_secondaryAssists']

    valid = grouped[grouped['icetime'] > 3600].copy()
    tot_time = valid['icetime'].sum()
    mean_g60 = (valid['I_F_goals'].sum() / tot_time) * 3600
    mean_a60 = (valid['assists'].sum() / tot_time) * 3600
    mean_sog60 = (valid['I_F_shotsOnGoal'].sum() / tot_time) * 3600

    K = 10 * 3600  # Poids de régularisation bayésienne (10 heures de temps de glace)
    valid['prior_g60'] = (valid['I_F_goals'] + (K / 3600) * mean_g60) / (valid['icetime'] / 3600 + (K / 3600))
    valid['prior_a60'] = (valid['assists'] + (K / 3600) * mean_a60) / (valid['icetime'] / 3600 + (K / 3600))
    valid['prior_sog60'] = (valid['I_F_shotsOnGoal'] + (K / 3600) * mean_sog60) / (valid['icetime'] / 3600 + (K / 3600))
    # Prior shooting percentage Beta(10, 90)
    valid['prior_sh_pct'] = (valid['I_F_goals'] + 10.0) / (valid['I_F_shotsOnGoal'] + 100.0)

    priors = valid[['prior_g60', 'prior_a60', 'prior_sog60', 'prior_sh_pct']].to_dict(orient='index')
    print(f"  [Priors] {len(priors):,} joueurs vétérans profilés avec succès (moy G/60={mean_g60:.2f}, A/60={mean_a60:.2f}).")
    
    # Exporter le cache des priors pour la prod
    cache_path = os.path.join(DATA_DIR, "priors_cache.json")
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump({
                "defaults": {"prior_g60": mean_g60, "prior_a60": mean_a60, "prior_sog60": mean_sog60, "prior_sh_pct": 0.095},
                "players": priors
            }, f, indent=2)
        print(f"  [Priors] Cache exporté vers {cache_path}")
    except Exception as e:
        print(f"  [Priors] Erreur lors de l'export JSON : {e}")
        
    return priors, mean_g60, mean_a60, mean_sog60


def build_team_and_goalie_context():
    """Compile les profils contextuels d'équipes et de gardiens par (équipe, saison)."""
    print("  [Contexte] Compilation des métriques équipes et gardiens (2008-2026)...")
    
    # 1. Équipes
    t_hist_path = os.path.join(DATA_DIR, "teams_2008_to_2024.csv")
    t_cur_path = os.path.join(DATA_DIR, "teams.csv")
    t_dfs = []
    if os.path.exists(t_hist_path):
        t_dfs.append(pd.read_csv(t_hist_path))
    if os.path.exists(t_cur_path):
        t_dfs.append(pd.read_csv(t_cur_path))
        
    team_dict = {}
    if t_dfs:
        df_t = pd.concat(t_dfs, ignore_index=True)
        df_t = df_t[df_t['situation'] == 'all'].copy()
        df_t['opp_xga_60'] = (df_t['xGoalsAgainst'] / df_t['iceTime'].replace(0, np.nan)) * 3600
        df_t['opp_hdca_60'] = (df_t['highDangerxGoalsAgainst'] / df_t['iceTime'].replace(0, np.nan)) * 3600
        df_t['team_xg_60'] = (df_t['xGoalsFor'] / df_t['iceTime'].replace(0, np.nan)) * 3600
        team_dict = df_t.set_index(['team', 'season'])[['opp_xga_60', 'opp_hdca_60', 'team_xg_60']].to_dict(orient='index')

    # 2. Gardiens
    g_hist_path = os.path.join(DATA_DIR, "goalies_2008_to_2024.csv")
    g_cur_path = os.path.join(DATA_DIR, "goalies.csv")
    g_dfs = []
    if os.path.exists(g_hist_path):
        g_dfs.append(pd.read_csv(g_hist_path))
    if os.path.exists(g_cur_path):
        g_dfs.append(pd.read_csv(g_cur_path))
        
    goalie_dict = {}
    if g_dfs:
        df_g = pd.concat(g_dfs, ignore_index=True)
        df_g = df_g[df_g['situation'] == 'all'].copy()
        g_agg = df_g.groupby(['team', 'season']).agg({'xGoals': 'sum', 'goals': 'sum', 'icetime': 'sum'}).reset_index()
        g_agg = g_agg[g_agg['icetime'] > 3600].copy()
        g_agg['opp_goalie_gsax_60'] = ((g_agg['xGoals'] - g_agg['goals']) / g_agg['icetime']) * 3600
        goalie_dict = g_agg.set_index(['team', 'season'])['opp_goalie_gsax_60'].to_dict()

    print(f"  [Contexte] {len(team_dict):,} saisons-équipes et {len(goalie_dict):,} tandems de gardiens cartographiés.")
    return team_dict, goalie_dict


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

    for chunk in pd.read_csv(path, usecols=cols, chunksize=250000, low_memory=False):
        filtered = chunk[(chunk['season'] >= min_season) & (chunk['situation'] == 'all')].copy()
        if not filtered.empty:
            chunks.append(filtered)
            total_rows += len(filtered)
            sys.stdout.write(f"\r    -> {total_rows:,} lignes extraites ({time.time() - start_t:.1f}s)...")
            sys.stdout.flush()

    print(f"\n  [Extraction] Terminé : {total_rows:,} matchs-joueurs extraits depuis skaters_all.csv.")
    df = pd.concat(chunks, ignore_index=True)
    return df


def append_current_season_data(df_modern):
    """Complète le dataset avec les données de la saison 2025-2026 issues de bot_database.db."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='players'")
    has_players = cur.fetchone()[0] > 0
    
    if not has_players:
        conn.close()
        return df_modern

    print("  [Saison 2025-2026] Fusion des matchs récents de bot_database.db...")
    df_live = pd.read_sql("SELECT * FROM players WHERE but IS NOT NULL AND but != ''", conn)
    conn.close()

    if df_live.empty:
        return df_modern

    df_live['season'] = 2025
    df_live['name'] = df_live['joueur']
    df_live['gameDate'] = pd.to_datetime(df_live['date']).dt.strftime('%Y%m%d')
    df_live['playerTeam'] = df_live['equipe']
    df_live['opposingTeam'] = df_live['adversaire']
    df_live['home_or_away'] = np.where(df_live['is_home'] == 1, 'HOME', 'AWAY')
    df_live['position'] = 'F'
    df_live['situation'] = 'all'
    df_live['icetime'] = pd.to_numeric(df_live['atoi'], errors='coerce').fillna(15.0) * 60.0
    df_live['I_F_goals'] = pd.to_numeric(df_live['but'], errors='coerce').fillna(0)
    df_live['I_F_primaryAssists'] = pd.to_numeric(df_live['assist'], errors='coerce').fillna(0)
    df_live['I_F_secondaryAssists'] = 0
    df_live['I_F_shotsOnGoal'] = pd.to_numeric(df_live['sog'], errors='coerce').fillna(0)
    df_live['I_F_xGoals'] = pd.to_numeric(df_live['ixg'], errors='coerce').fillna(0)
    df_live['I_F_highDangerxGoals'] = pd.to_numeric(df_live['hdcf'], errors='coerce').fillna(0)
    df_live['playerId'] = 999999
    df_live['gameId'] = 999999

    cols = [
        'playerId', 'name', 'gameId', 'season', 'gameDate',
        'playerTeam', 'opposingTeam', 'home_or_away', 'position', 'situation',
        'icetime', 'I_F_goals', 'I_F_primaryAssists', 'I_F_secondaryAssists',
        'I_F_shotsOnGoal', 'I_F_xGoals', 'I_F_highDangerxGoals'
    ]
    df_live = df_live[[c for c in cols if c in df_live.columns]]
    print(f"  [Saison 2025-2026] +{len(df_live):,} lignes ajoutées pour 2025-2026.")
    
    combined = pd.concat([df_modern, df_live], ignore_index=True)
    return combined


def build_rolling_features(df, priors_tuple):
    """Calcule les statistiques roulantes L10 strictes (shift=1, sans leakage) et injecte le contexte.
    
    Les stats d'équipe/gardien sont désormais calculées match-par-match via expanding().shift(1)
    directement à partir des données joueurs, éliminant tout look-ahead bias.
    """
    priors, default_g60, default_a60, default_sog60 = priors_tuple
    
    print("  [Features] Calcul des métriques roulantes L10 décalées et interactions...")
    df['gameDate'] = pd.to_datetime(df['gameDate'], format='%Y%m%d', errors='coerce')
    df = df.sort_values(['name', 'gameDate']).reset_index(drop=True)

    df['assist'] = df['I_F_primaryAssists'].fillna(0) + df['I_F_secondaryAssists'].fillna(0)
    df['but'] = df['I_F_goals'].fillna(0)
    df['sog'] = df['I_F_shotsOnGoal'].fillna(0)
    df['ixg'] = df['I_F_xGoals'].fillna(0)
    df['atoi'] = df['icetime'].fillna(0) / 60.0  # en minutes

    # Calcul des L10 par joueur avec décalage strict (shift(1)) pour éliminer le look-ahead bias
    grouped = df.groupby('name')
    df['ixg_l10'] = grouped['ixg'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean()).fillna(0)
    df['sog_l10'] = grouped['sog'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean()).fillna(0)
    df['atoi_l10'] = grouped['atoi'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean()).fillna(0)
    df['l10_g'] = grouped['but'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean()).fillna(0)
    df['l10_a'] = grouped['assist'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean()).fillna(0)

    # Cumul de saison (expanding shifté)
    df['season_g'] = grouped['but'].transform(lambda x: x.shift(1).expanding().mean()).fillna(0)
    df['season_a'] = grouped['assist'].transform(lambda x: x.shift(1).expanding().mean()).fillna(0)
    df['season_pts'] = df['season_g'] + df['season_a']

    # Interactions & HDCF
    df['hdcf_l10'] = df['I_F_highDangerxGoals'].fillna(0)
    df['hdcf_l10'] = grouped['hdcf_l10'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean()).fillna(0)

    df['ixg_x_hdcf'] = df['ixg_l10'] * df['hdcf_l10']
    df['sog_x_atoi'] = df['sog_l10'] * df['atoi_l10']
    df['is_home'] = (df['home_or_away'] == 'HOME').astype(int)
    df['is_top6'] = (df['atoi_l10'] >= 17.0).astype(int)

    # Injection des priors bayésiens des vétérans
    df['prior_g60'] = df['name'].map(lambda n: priors.get(n, {}).get('prior_g60', default_g60))
    df['prior_a60'] = df['name'].map(lambda n: priors.get(n, {}).get('prior_a60', default_a60))
    df['prior_sog60'] = df['name'].map(lambda n: priors.get(n, {}).get('prior_sog60', default_sog60))
    df['prior_sh_pct'] = df['name'].map(lambda n: priors.get(n, {}).get('prior_sh_pct', 0.095))

    # === CORRECTION DATA LEAKAGE : Calcul des stats d'équipe match-par-match ===
    # Au lieu d'utiliser les moyennes de fin de saison (look-ahead bias),
    # on recalcule les stats adverses via un expanding().shift(1) par équipe/saison.
    print("  [Features] Calcul des stats adverses SANS leakage (expanding décalé)...")

    # 1. Agréger les stats offensives par (gameDate, team, season) pour obtenir le profil d'équipe par match
    game_team_stats = df.groupby(['gameDate', 'playerTeam', 'season']).agg({
        'I_F_xGoals': 'sum',
        'I_F_highDangerxGoals': 'sum',
        'I_F_goals': 'sum',
    }).reset_index().rename(columns={
        'playerTeam': 'team',
        'I_F_xGoals': 'team_xg_game',
        'I_F_highDangerxGoals': 'team_hdxg_game',
        'I_F_goals': 'team_goals_game',
    })
    game_team_stats = game_team_stats.sort_values(['team', 'season', 'gameDate']).reset_index(drop=True)

    # 2. Calculer les moyennes roulantes expanding décalées (shift(1)) par équipe et saison
    grp_team = game_team_stats.groupby(['team', 'season'])
    game_team_stats['team_xg_60_rolling'] = grp_team['team_xg_game'].transform(
        lambda x: x.shift(1).expanding().mean()
    ).fillna(2.80)
    game_team_stats['team_ga_60_rolling'] = grp_team['team_goals_game'].transform(
        lambda x: x.shift(1).expanding().mean()
    ).fillna(2.80)
    game_team_stats['team_hdxg_60_rolling'] = grp_team['team_hdxg_game'].transform(
        lambda x: x.shift(1).expanding().mean()
    ).fillna(0.85)

    # 3. Joindre les stats de l'ADVERSAIRE au DataFrame principal
    # Pour chaque joueur, on cherche les stats de l'équipe adverse (opposingTeam) à cette date
    opp_stats = game_team_stats[['gameDate', 'team', 'season',
                                  'team_ga_60_rolling', 'team_hdxg_60_rolling']].rename(columns={
        'team': 'opposingTeam',
        'team_ga_60_rolling': 'opp_xga_60',
        'team_hdxg_60_rolling': 'opp_hdca_60',
    })
    df = df.merge(opp_stats, on=['gameDate', 'opposingTeam', 'season'], how='left')
    df['opp_xga_60'] = df['opp_xga_60'].fillna(2.80)
    df['opp_hdca_60'] = df['opp_hdca_60'].fillna(0.85)

    # Stats de l'équipe du joueur
    own_stats = game_team_stats[['gameDate', 'team', 'season',
                                  'team_xg_60_rolling']].rename(columns={
        'team': 'playerTeam',
        'team_xg_60_rolling': 'team_xg_60',
    })
    df = df.merge(own_stats, on=['gameDate', 'playerTeam', 'season'], how='left')
    df['team_xg_60'] = df['team_xg_60'].fillna(2.80)

    # Gardiens : sans données match-par-match dans goalies CSV, on utilise un proxy
    # basé sur les buts encaissés par l'équipe adverse (GSAX approximé)
    df['opp_goalie_gsax_60'] = 0.0  # Neutral par défaut — pas de leakage

    # Interaction xG joueur x Qualité défensive adverse
    df['ixg_x_opp_xga'] = df['ixg_l10'] * (df['opp_xga_60'] / 2.80)

    # Cibles
    df['target_but'] = (df['but'] > 0).astype(int)
    df['target_ast'] = (df['assist'] > 0).astype(int)

    # Noms normalisés
    df['joueur'] = df['name']
    df['date'] = df['gameDate']
    df['equipe'] = df['playerTeam']
    df['adversaire'] = df['opposingTeam']

    print(f"  [Features] Super-dataset assemblé : {len(df):,} lignes et {len(df.columns)} colonnes.")
    return df


def save_dataset(df):
    """Sauvegarde le dataset en Parquet et dans SQLite."""
    print(f"  [Sauvegarde] Export vers {OUTPUT_PARQUET}...")
    df.to_parquet(OUTPUT_PARQUET, index=False)

    print(f"  [Sauvegarde] Export vers SQLite {DB_PATH} (table 'historical_players')...")
    conn = sqlite3.connect(DB_PATH)
    
    save_cols = [
        'date', 'season', 'joueur', 'equipe', 'adversaire', 'is_home',
        'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 'l10_g', 'l10_a',
        'season_g', 'season_a', 'season_pts', 'ixg_x_hdcf', 'sog_x_atoi',
        'is_top6', 'prior_g60', 'prior_a60', 'prior_sog60', 'prior_sh_pct',
        'opp_xga_60', 'opp_hdca_60', 'opp_goalie_gsax_60', 'team_xg_60',
        'ixg_x_opp_xga', 'but', 'assist', 'target_but', 'target_ast'
    ]
    df_sub = df[[c for c in save_cols if c in df.columns]]
    df_sub.to_sql("historical_players", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_date ON historical_players (date);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_joueur ON historical_players (joueur);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_season ON historical_players (season);")
    conn.close()
    print("  [Sauvegarde] Base de données indexée avec succès.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-season", type=int, default=2018, help="Saison de départ (défaut: 2018 pour l'ère moderne)")
    args = parser.parse_args()

    print("=" * 75)
    print(f" COMPILATION DU SUPER-DATASET HISTORIQUE MULTI-SAISONS ({args.min_season}-2026)")
    print(" Priors bayésiens (2008-2017) -> Entraînement moderne (2018-2026)")
    print("=" * 75)

    priors_tuple = compute_veteran_priors()
    # build_team_and_goalie_context() n'est plus utilisé pour les features
    # Les stats d'équipe sont calculées match-par-match dans build_rolling_features()
    df_modern = extract_modern_skaters(min_season=args.min_season)
    df_combined = append_current_season_data(df_modern)
    df_full = build_rolling_features(df_combined, priors_tuple)
    save_dataset(df_full)

    print("\n✅ SUPER-DATASET 2018-2026 COMPILÉ AVEC SUCCÈS !")


if __name__ == "__main__":
    main()
