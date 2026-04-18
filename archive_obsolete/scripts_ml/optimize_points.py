"""
Optimisation HONNETE du marche POINTEURS.
Examine le pouvoir predictif des features et fait un grid search temporel.
"""
import sqlite3
import pandas as pd
import numpy as np
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)
os.chdir(root)

DB_PATH = "bot_database.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    
    df = pd.read_sql(
        "SELECT * FROM players WHERE point IS NOT NULL AND point != ''",
        conn
    )
    conn.close()
    
    numeric_cols = ['ixg', 'hdcf', 'sog', 'atoi', 'season_g', 'season_a', 'season_pts',
                    'l10_g', 'l10_a', 'l10_pts', 'ga_g', 'cf_pct', 'hdca_g', 'pk_pct',
                    'pdo', 'consec_goals', 'score_but', 'score_assist', 'score_point',
                    'pp1', 'is_home', 'b2b', 'backup']
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    
    df['point'] = pd.to_numeric(df['point'], errors='coerce').fillna(0).astype(int)
    df['scored'] = (df['point'] > 0).astype(int)
    
    print("=" * 70)
    print("EXPLORATION DES DONNEES - MARCHE POINTEURS")
    print("=" * 70)
    print(f"Base rate (% de joueurs qui marquent 1 point): {df['scored'].mean()*100:.1f}%")
    
    # Grid Search
    qs_thresholds = [7.0, 8.0, 9.0, 10.0, 10.5, 11.0, 11.5, 12.0]
    sp_thresholds = [0.0, 0.40, 0.60, 0.70, 0.80] # season_pts
    l10p_thresholds = [0.0, 0.40, 0.60, 0.80, 1.00] # l10_pts
    home_filter = [None, True]
    
    results = []
    
    for qs_min in qs_thresholds:
        for sp_min in sp_thresholds:
            for l10p_min in l10p_thresholds:
                for home_only in home_filter:
                    mask = (
                        (df['score_point'] >= qs_min) &
                        (df['season_pts'] >= sp_min) &
                        (df['l10_pts'] >= l10p_min)
                    )
                    if home_only: mask &= (df['is_home'] == 1)
                    
                    subset = df[mask]
                    if len(subset) < 15: continue
                    
                    won = subset['scored'].sum()
                    total = len(subset)
                    wr = won / total * 100
                    
                    active_days = subset['date'].nunique()
                    picks_per_day = total / active_days if active_days > 0 else 0
                    
                    results.append({
                        'qs_min': qs_min,
                        'sp_min': sp_min,
                        'l10p_min': l10p_min,
                        'home_only': bool(home_only),
                        'total': total,
                        'won': won,
                        'winrate': wr,
                    })
    
    res_df = pd.DataFrame(results)
    if res_df.empty: return
    
    print("\n" + "=" * 70)
    print("TOP 10 EQUILIBRE (>30 picks)")
    print("=" * 70)
    # Average Break-even for Points is around 1.57 (63.5% WR needed)
    valid30 = res_df[res_df['total'] >= 30].sort_values('winrate', ascending=False).head(20)
    if not valid30.empty:
        for i, (_, r) in enumerate(valid30.iterrows()):
            roi = (r['winrate']/100 * 1.57 - 1) * 100
            print(f"#{i+1} WR: {r['winrate']:.1f}% ({r['won']:.0f}/{r['total']:.0f}) | ROI estime: {roi:+.1f}%")
            print(f"    QS>={r['qs_min']}, Season_Pts>={r['sp_min']}, L10_Pts>={r['l10p_min']}, Home={r['home_only']}")
    
if __name__ == "__main__":
    main()
