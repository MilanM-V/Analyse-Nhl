
import sqlite3
import pandas as pd
import numpy as np
import joblib
import os
import sys

# Setup Path
root = "c:\\Users\\2507m\\Desktop\\Milan\\code\\bet2"
sys.path.append(root)

def find_sniper_configs():
    conn = sqlite3.connect('bot_database.db')
    # Simulation sur les 2 dernières semaines (période de référence)
    query = "SELECT * FROM players WHERE date >= '2026-03-30' AND date <= '2026-04-12'"
    df = pd.read_sql(query, conn)
    conn.close()
    
    # Déduplication : on prend le meilleur scan par match/joueur
    df = df.sort_values(['date', 'joueur', 'score_but'], ascending=False).drop_duplicates(['date', 'joueur'])
    df['cote'] = pd.to_numeric(df['cote'], errors='coerce').fillna(0)

    # Charger les 3 modèles V14.3
    m_but = joblib.load('models/xg_model_but.pkl')['model']
    m_ast = joblib.load('models/xg_model_assist.pkl')['model']
    m_pts = joblib.load('models/xg_model_point.pkl')['model']

    results = []
    
    # On calcule les probas IA pour TOUS les joueurs une seule fois
    players_data = []
    for _, row in df.iterrows():
        ixg = row['ixg'] if pd.notna(row['ixg']) else 0.15
        hdcf = row['hdcf'] if pd.notna(row['hdcf']) else 0.5
        sog = row['sog'] if pd.notna(row['sog']) else 2.5
        atoi = row['atoi'] if pd.notna(row['atoi']) else 18.0
        X = np.array([[
            ixg, hdcf, sog, atoi, row['season_g'] or 0.2,
            row['ga_g'] or 2.8, row['hdca_g'] or 8.0, int(row['pp1'] or 0), int(row['is_home'] or 0),
            int(row['b2b'] or 0), int(row['opp_b2b'] or 0), row['consec_goals'] or 0, row['score_but'],
            1.0, ixg * hdcf, sog * atoi, ixg * (row['ga_g'] or 2.8), (row['consec_goals'] or 0) * ixg
        ]])
        
        players_data.append({
            'date': row['date'],
            'joueur': row['joueur'],
            'score_but': row['score_but'],
            'score_assist': row['score_assist'],
            'score_point': row['score_point'],
            'but_win': 1 if row['but'] > 0 else 0,
            'ast_win': 1 if row['assist'] > 0 else 0,
            'pts_win': 1 if row['point'] > 0 else 0,
            'cote': row['cote'],
            'p_but': float(m_but.predict_proba(X)[0][1]),
            'p_ast': float(m_ast.predict_proba(X)[0][1]),
            'p_pts': float(m_pts.predict_proba(X)[0][1])
        })
    
    sim_df = pd.DataFrame(players_data)

    # --- RECHERCHE SNIPER BUTS ---
    # On cherche le seuil qui donne le plus de picks à 100% WR
    best_but = {'picks': 0, 'wr': 0, 'qs': 0, 'proba': 0, 'cote_avg': 0}
    for qs in [9.5, 9.75, 10.0, 10.25]:
        for p in [0.60, 0.65, 0.70]:
            subset = sim_df[(sim_df['score_but'] >= qs) & (sim_df['p_but'] >= p)]
            if len(subset) >= 5:
                wr = (subset['but_win'].sum() / len(subset)) * 100
                if wr >= best_but['wr']:
                    # Priorité au plus grand nombre de picks si le WR est égal
                    if wr > best_but['wr'] or len(subset) >= best_but['picks']:
                        best_but = {'picks': len(subset), 'wr': wr, 'qs': qs, 'proba': p, 'cote_avg': subset[subset['cote']>0]['cote'].mean()}

    # --- RECHERCHE SNIPER ASSISTS ---
    best_ast = {'picks': 0, 'wr': 0, 'qs': 0, 'proba': 0, 'cote_avg': 0}
    for qs in [10.0, 10.25, 10.5, 10.75]:
        for p in [0.60, 0.65, 0.70]:
            subset = sim_df[(sim_df['score_assist'] >= qs) & (sim_df['p_ast'] >= p)]
            if len(subset) >= 5:
                wr = (subset['ast_win'].sum() / len(subset)) * 100
                if wr >= best_ast['wr']:
                    if wr > best_ast['wr'] or len(subset) >= best_ast['picks']:
                        best_ast = {'picks': len(subset), 'wr': wr, 'qs': qs, 'proba': p, 'cote_avg': subset[subset['cote']>0]['cote'].mean()}

    # --- RECHERCHE SNIPER POINTS ---
    best_pts = {'picks': 0, 'wr': 0, 'qs': 0, 'proba': 0, 'cote_avg': 0}
    for qs in [10.5, 10.75, 11.0, 11.25]:
        for p in [0.65, 0.70, 0.75, 0.80]:
            subset = sim_df[(sim_df['score_point'] >= qs) & (sim_df['p_pts'] >= p)]
            if len(subset) >= 5:
                wr = (subset['pts_win'].sum() / len(subset)) * 100
                if wr >= best_pts['wr']:
                    if wr > best_pts['wr'] or len(subset) >= best_pts['picks']:
                        best_pts = {'picks': len(subset), 'wr': wr, 'qs': qs, 'proba': p, 'cote_avg': subset[subset['cote']>0]['cote'].mean()}

    print("\n=== CONFIGURATIONS SNIPER OPTIMALES (V14.3) ===")
    print(f"BUTS    : Seuil QS {best_but['qs']}, Proba IA {best_but['proba']} -> {best_but['picks']} picks, {best_but['wr']:.1f}% WR, Cote Moy: {best_but['cote_avg']:.2f}")
    print(f"ASSISTS : Seuil QS {best_ast['qs']}, Proba IA {best_ast['proba']} -> {best_ast['picks']} picks, {best_ast['wr']:.1f}% WR, Cote Moy: {best_ast['cote_avg']:.2f}")
    print(f"POINTS  : Seuil QS {best_pts['qs']}, Proba IA {best_pts['proba']} -> {best_pts['picks']} picks, {best_pts['wr']:.1f}% WR, Cote Moy: {best_pts['cote_avg']:.2f}")

if __name__ == "__main__":
    find_sniper_configs()
