
import sqlite3
import pandas as pd
import numpy as np
import joblib
import os
import sys

# Setup Path
root = "c:\\Users\\2507m\\Desktop\\Milan\\code\bet2"
sys.path.append(root)

def validate():
    conn = sqlite3.connect('bot_database.db')
    # On teste sur les 2 dernières semaines
    query = "SELECT * FROM players WHERE date >= '2026-03-30' AND date <= '2026-04-12'"
    df = pd.read_sql(query, conn)
    conn.close()
    
    df = df.sort_values(['date', 'joueur', 'score_but'], ascending=False).drop_duplicates(['date', 'joueur'])
    df['cote'] = pd.to_numeric(df['cote'], errors='coerce').fillna(2.0)

    # Charger les 3 modèles
    m_but = joblib.load('models/xg_model_but.pkl')['model']
    m_ast = joblib.load('models/xg_model_assist.pkl')['model']
    m_pts = joblib.load('models/xg_model_point.pkl')['model']

    results = []

    for _, row in df.iterrows():
        # Features communes
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

        # 1. ANCIENNE LOGIQUE (Heuristique du plan sniper equilibre)
        # Buteur V14.1 (déjà IA)
        p_but_old = float(m_but.predict_proba(X)[0][1])
        if row['score_but'] >= 9.75 and p_but_old >= 0.65:
            results.append({'version': 'ANCIENNE', 'cat': 'BUT', 'won': row['but'] > 0})
        
        # Assist Old (Celle d'hier)
        if row['score_assist'] >= 10.25:
            p_ast_old = min(row['score_assist'] / 15.0, 0.75)
            if (p_ast_old * row['cote']) - 1.0 >= 0.02:
                results.append({'version': 'ANCIENNE', 'cat': 'ASSIST', 'won': row['assist'] > 0})
                
        # Point Old (Celle d'hier)
        if row['score_point'] >= 10.75:
            p_pts_old = min(row['score_point'] / 15.0, 0.75)
            if (p_pts_old * row['cote']) - 1.0 >= 0.02:
                results.append({'version': 'ANCIENNE', 'cat': 'POINT', 'won': row['point'] > 0})

        # 2. NOUVELLE LOGIQUE (100% IA)
        # Buteur (Seuil 10.0 + IA 0.65)
        p_but_new = float(m_but.predict_proba(X)[0][1])
        if row['score_but'] >= 10.0 and p_but_new >= 0.65:
            results.append({'version': 'NOUVELLE (IA)', 'cat': 'BUT', 'won': row['but'] > 0})
            
        # Assist IA (Seuil 10.5 + IA 0.55)
        p_ast_new = float(m_ast.predict_proba(X)[0][1])
        if row['score_assist'] >= 10.5 and p_ast_new >= 0.55:
            if (p_ast_new * row['cote']) - 1.0 >= 0.02:
                results.append({'version': 'NOUVELLE (IA)', 'cat': 'ASSIST', 'won': row['assist'] > 0})

        # Point IA (Seuil 11.0 + IA 0.60)
        p_pts_new = float(m_pts.predict_proba(X)[0][1])
        if row['score_point'] >= 11.0 and p_pts_new >= 0.60:
            if (p_pts_new * row['cote']) - 1.0 >= 0.02:
                results.append({'version': 'NOUVELLE (IA)', 'cat': 'POINT', 'won': row['point'] > 0})

    res_df = pd.DataFrame(results)
    stats = res_df.groupby(['version', 'cat']).agg(Picks=('won', 'count'), Wins=('won', 'sum'))
    stats['Winrate'] = (stats['Wins'] / stats['Picks'] * 100).round(1)
    
    print("\n=== COMPARAISON PERFORMANCE (2 SEMAINES) ===")
    print(stats.to_markdown())

if __name__ == "__main__":
    validate()
