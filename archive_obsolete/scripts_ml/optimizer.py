"""
Script d'optimisation (Grid Search) pour NHL Bet Bot.
Simule des milliers de combinaisons de paramètres sur l'historique du bot (table players)
afin de trouver les seuils optimaux (QS et malus) maximisant le ROI / Profit.
"""

import sqlite3
import pandas as pd
import numpy as np
import itertools
from concurrent.futures import ProcessPoolExecutor
import time
import os

# Paramètres de simulation
INITIAL_BANKROLL = 10.0
RATIO = 0.70  # On mise 70% de la BR disponible

def fetch_data():
    conn = sqlite3.connect('./bot_database.db')
    
    # Buteur (needs goal)
    query_but = """
    SELECT date, joueur, score_but, but as won, is_home, cote, atoi, season_g, sog
    FROM players
    WHERE but IS NOT NULL AND but != '' AND score_but > 0
    """
    df_but = pd.read_sql(query_but, conn)
    
    # Passeur
    query_ast = """
    SELECT date, joueur, score_assist, assist as won, is_home, cote, atoi, season_a
    FROM players
    WHERE assist IS NOT NULL AND assist != '' AND score_assist > 0
    """
    df_ast = pd.read_sql(query_ast, conn)
    
    # Pointeur
    query_pts = """
    SELECT date, joueur, score_point, point as won, is_home, cote, atoi, season_pts
    FROM players
    WHERE point IS NOT NULL AND point != '' AND score_point > 0
    """
    df_pts = pd.read_sql(query_pts, conn)
    
    conn.close()

    # Nettoyage des cotes
    for df in [df_but, df_ast, df_pts]:
        df['cote'] = pd.to_numeric(df['cote'], errors='coerce')
        df['won'] = pd.to_numeric(df['won'], errors='coerce').fillna(0).astype(int)
        df['won'] = df['won'].apply(lambda x: 1 if x > 0 else 0)
        df['date'] = pd.to_datetime(df['date'])

    # Application d'une cote moyenne par défaut pour les joueurs non-pickés
    mc_b = df_but['cote'].mean() if pd.notna(df_but['cote'].mean()) else 2.50
    df_but['cote'] = df_but['cote'].fillna(mc_b)
    
    mc_a = df_ast['cote'].mean() if pd.notna(df_ast['cote'].mean()) else 1.90
    df_ast['cote'] = df_ast['cote'].fillna(mc_a)
    
    mc_p = df_pts['cote'].mean() if pd.notna(df_pts['cote'].mean()) else 1.65
    df_pts['cote'] = df_pts['cote'].fillna(mc_p)

    return df_but, df_ast, df_pts

def simulate_scenario(params):
    df_but, df_ast, df_pts, thresh_but, thresh_ast, malus_ast, thresh_pts, malus_pts = params
    
    # Filtre de base commun (ATOI > 13.0)
    # Note: Dans la DB players, on a atoi, season_g, season_a, season_pts, sog
    df_but = df_but[(df_but['atoi'] >= 13.0) & (df_but['season_g'] >= 0.20) & (df_but['sog'] >= 2.0)]
    df_ast = df_ast[(df_ast['atoi'] >= 13.0) & (df_ast['season_a'] >= 0.35)]
    df_pts = df_pts[(df_pts['atoi'] >= 13.0) & (df_pts['season_pts'] >= 0.65)]
    
    # Filtre Buteurs
    picks_but = df_but[df_but['score_but'] >= thresh_but].copy()
    
    # Filtre Passeurs
    adj_score_ast = np.where(df_ast['is_home'] == 1, df_ast['score_assist'], df_ast['score_assist'] - malus_ast)
    picks_ast = df_ast[adj_score_ast >= thresh_ast].copy()
    
    # Filtre Pointeurs
    adj_score_pts = np.where(df_pts['is_home'] == 1, df_pts['score_point'], df_pts['score_point'] - malus_pts)
    picks_pts = df_pts[adj_score_pts >= thresh_pts].copy()
    
    # Combiner l'ensemble des picks
    all_picks = pd.concat([
        picks_but[['date', 'joueur', 'cote', 'won']],
        picks_ast[['date', 'joueur', 'cote', 'won']],
        picks_pts[['date', 'joueur', 'cote', 'won']]
    ])
    
    # Dédoublonner joueur/date pour ne pas miser 2 fois sur le même sur une journée
    all_picks = all_picks.drop_duplicates(subset=['date', 'joueur'])
    
    if all_picks.empty:
        return (thresh_but, thresh_ast, malus_ast, thresh_pts, malus_pts, 0, 0, 0, 10.0)

    # Flat betting au lieu du compound pour l'optimisation
    # Mise = 1 unité par pick
    total_mise = len(all_picks)
    total_retour = sum(row['cote'] for _, row in all_picks.iterrows() if row['won'] == 1)
    
    profit = total_retour - total_mise
    roi = (profit / total_mise) * 100 if total_mise > 0 else 0
    
    return (thresh_but, thresh_ast, malus_ast, thresh_pts, malus_pts, len(all_picks), all_picks['won'].sum(), roi, profit)

def main():
    print("Initialisation des donnees...")
    df_but, df_ast, df_pts = fetch_data()
    
    # Grille de recherche reduite
    grid_but_qs = np.arange(9.25, 11.25, 0.25)
    grid_ast_qs = np.arange(9.5, 11.25, 0.25)
    grid_ast_malus = [1.0]
    grid_pts_qs = np.arange(10.0, 11.25, 0.25)
    grid_pts_malus = [1.0]
    
    scenarios = list(itertools.product(
        grid_but_qs, grid_ast_qs, grid_ast_malus, grid_pts_qs, grid_pts_malus
    ))
    
    print(f"{len(scenarios)} scénarios à simuler. Lancement...", flush=True)
    t0 = time.time()
    
    results = []
    
    count = 0
    best_roi = -999
    
    for t_but, t_ast, m_ast, t_pts, m_pts in scenarios:
        res = simulate_scenario((df_but, df_ast, df_pts, t_but, t_ast, m_ast, t_pts, m_pts))
        results.append(res)
        count += 1
        
        if res[7] > best_roi and res[5] > 20: # Au moins 20 picks
            best_roi = res[7]
            
        if count % 100 == 0:
            print(f"Progression: {count}/{len(scenarios)} - Meilleur ROI (>=20 picks): {best_roi:.2f}%", flush=True)
            
    print(f"\nSimulation terminée en {time.time() - t0:.1f} sec.", flush=True)
    
    res_df = pd.DataFrame(results, columns=[
        'But_QS', 'Ast_QS', 'Ast_Malus', 'Pts_QS', 'Pts_Malus',
        'Picks', 'Wins', 'ROI', 'Bankroll'
    ])
    
    res_df = res_df[res_df['Picks'] >= 20].sort_values('ROI', ascending=False)
    
    print("="*60)
    print(" TOP 10 DES MEILLEURES CONFIGURATIONS ")
    print("="*60)
    print(res_df.head(10).to_string(index=False))
    
    res_df.to_csv('optimizer_results.csv', index=False)
    print("Résultats sauvegardés dans scripts/optimizer_results.csv")

if __name__ == '__main__':
    main()
