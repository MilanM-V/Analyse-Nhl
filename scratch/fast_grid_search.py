"""
Fast Grid Search for v19.7 optimization
Tests millions of configurations in seconds using Pandas vectorization.
"""
import sqlite3, json, math, os, sys, itertools
import pandas as pd
import numpy as np
from time import time

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot_database.db")
OUTPUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "best_scenarios.json")

# v19.7 Probas & Quarter Kelly
PROBAS = {"buteur": 0.35, "passeur": 0.50, "pointeur": 0.65}
KELLY_FRACTION = 0.25

def load_data_df():
    conn = sqlite3.connect(DB_PATH)
    players = pd.read_sql("""
        SELECT date, joueur, equipe, adversaire, is_home, pp1, opp_b2b,
               CAST(season_g AS FLOAT) as season_g, CAST(sog AS FLOAT) as sog, CAST(hdcf AS FLOAT) as hdcf,
               CAST(season_a AS FLOAT) as season_a, CAST(l10_a AS FLOAT) as l10_a,
               CAST(season_pts AS FLOAT) as season_pts, CAST(l10_pts AS FLOAT) as l10_pts,
               CAST(atoi AS FLOAT) as atoi, CAST(ga_g AS FLOAT) as ga_g,
               CAST(but AS INTEGER) as but, CAST(assist AS INTEGER) as assist, CAST(point AS INTEGER) as point
        FROM players 
        WHERE but IS NOT NULL AND but != '' AND l10_a IS NOT NULL AND season_a IS NOT NULL
    """, conn)
    
    # Fill NAs
    for col in ['season_g', 'sog', 'hdcf', 'season_a', 'l10_a', 'season_pts', 'l10_pts', 'atoi', 'ga_g']:
        players[col] = players[col].fillna(0)
    for col in ['but', 'assist', 'point']:
        players[col] = players[col].fillna(0)
        
    cotes_b = pd.read_sql("SELECT date, joueur, cote as cote_b FROM picks WHERE cote IS NOT NULL AND cote > 0", conn)
    cotes_a = pd.read_sql("SELECT date, joueur, cote as cote_a FROM picks_assists WHERE cote IS NOT NULL AND cote > 0", conn)
    cotes_p = pd.read_sql("SELECT date, joueur, cote as cote_p FROM picks_points WHERE cote IS NOT NULL AND cote > 0", conn)
    conn.close()

    # Deduplicate players
    players = players.drop_duplicates(subset=['date', 'joueur'])

    # Merge cotes
    df = players.merge(cotes_b, on=['date', 'joueur'], how='left')
    df = df.merge(cotes_a, on=['date', 'joueur'], how='left')
    df = df.merge(cotes_p, on=['date', 'joueur'], how='left')

    avg_b = 3.20
    avg_a = 1.96
    avg_p = 1.64

    df['cote_b'] = df['cote_b'].fillna(avg_b)
    df['cote_a'] = df['cote_a'].fillna(avg_a)
    df['cote_p'] = df['cote_p'].fillna(avg_p)
    
    # Do not pre-filter is_home here. Let it be a grid parameter or ignore it entirely
    df['is_def'] = False  # Pas de colonne pos dans la DB, on assume F pour l'optimisation
    
    # The simulation previously ran with home_only = False (due to playoff mode override)
    # Let's grid search both home_only = True and home_only = False

    return df, avg_b, avg_a, avg_p

def calc_kelly_gains(df, proba, cote_col, res_col, caps, is_def_penalty=False):
    """Precompute units and gains for each player for a set of kelly caps."""
    b = df[cote_col] - 1.0
    p = np.where(df['is_def'] & is_def_penalty, proba * 0.6, proba)
    q = 1.0 - p
    f = (p * b - q) / b
    
    valid_f = f > 0
    quarter_f = np.where(valid_f, f / 4.0, 0)
    units_raw = np.round(quarter_f * 100 * 2) / 2
    
    res = {}
    for cap in caps:
        u = np.clip(units_raw, 0.5, cap)
        u = np.where(valid_f, u, 0.0)
        u = np.where(df[cote_col] <= 1.05, 0.0, u) # Reject low odds
        
        won = df[res_col] > 0
        gain = np.where(won, (df[cote_col] - 1.0) * u, -u)
        
        # DataFrame boolean mask for fast filtering
        res[cap] = {'u': u, 'gain': gain}
    return res

def optimize_buteurs(df):
    probas = PROBAS['buteur']
    caps = [2.0, 3.0, 4.0, 5.0]
    kelly_data = calc_kelly_gains(df, probas, 'cote_b', 'but', caps)
    
    # Grid
    s_g = [0.30, 0.40, 0.50]
    sog = [2.5, 3.0, 3.5]
    hdcf = [1.5, 2.0, 2.5]
    opp_ga = [2.5, 2.8, 3.0]
    cote_min = [0.0, 2.5, 3.0]
    home_only_opts = [True, False]
    
    best_configs = []
    
    for sg, s, h, oga, cmin, h_only in itertools.product(s_g, sog, hdcf, opp_ga, cote_min, home_only_opts):
        mask = (df['season_g'] >= sg) & (df['sog'] >= s) & (df['hdcf'] >= h) & (df['ga_g'] >= oga) & (df['cote_b'] >= cmin)
        if h_only:
            mask = mask & (df['is_home'] == 1)
            
        if not mask.any(): continue
        
        for cap in caps:
            u = kelly_data[cap]['u'][mask]
            g = kelly_data[cap]['gain'][mask]
            
            valid = u > 0
            picks = valid.sum()
            if picks < 10: continue
            
            profit = g[valid].sum()
            mise = u[valid].sum()
            roi = (profit/mise)*100 if mise > 0 else 0
            
            if profit > 15: # Minimum profit threshold to save memory
                best_configs.append({
                    'profit': round(profit, 1), 'roi': round(roi, 1), 'picks': int(picks),
                    'cfg': {'season_g': sg, 'sog': s, 'hdcf': h, 'opp_ga': oga, 'cote_min': cmin, 'home_only': h_only, 'cap': cap}
                })
    
    best_configs.sort(key=lambda x: x['profit'], reverse=True)
    return best_configs[:5]

def optimize_passeurs(df):
    probas = PROBAS['passeur']
    caps = [2.0, 3.0, 4.0]
    kelly_data = calc_kelly_gains(df, probas, 'cote_a', 'assist', caps)
    
    s_a = [0.30, 0.40, 0.50, 0.60]
    l10_a = [0.60, 0.80, 1.00]
    atoi = [16.0, 17.0, 18.0]
    opp_ga = [2.6, 2.8, 3.0]
    cote_min = [0.0, 2.0, 2.2]
    home_only_opts = [True, False]
    
    best_configs = []
    for sa, la, at, oga, cmin, h_only in itertools.product(s_a, l10_a, atoi, opp_ga, cote_min, home_only_opts):
        mask = (df['season_a'] >= sa) & (df['l10_a'] >= la) & (df['atoi'] >= at) & (df['ga_g'] >= oga) & (df['cote_a'] >= cmin)
        if h_only:
            mask = mask & (df['is_home'] == 1)
            
        if not mask.any(): continue
        
        for cap in caps:
            u = kelly_data[cap]['u'][mask]
            g = kelly_data[cap]['gain'][mask]
            valid = u > 0; picks = valid.sum()
            if picks < 10: continue
            
            profit = g[valid].sum(); mise = u[valid].sum()
            if profit > 10:
                best_configs.append({
                    'profit': round(profit, 1), 'roi': round((profit/mise)*100, 1), 'picks': int(picks),
                    'cfg': {'season_a': sa, 'l10_a': la, 'atoi': at, 'opp_ga': oga, 'cote_min': cmin, 'home_only': h_only, 'cap': cap}
                })
    best_configs.sort(key=lambda x: x['profit'], reverse=True)
    return best_configs[:5]

def optimize_pointeurs(df):
    probas = PROBAS['pointeur']
    caps = [2.0, 3.0, 4.0]
    kelly_data = calc_kelly_gains(df, probas, 'cote_p', 'point', caps)
    
    s_pts = [0.70, 0.80, 0.90, 1.00]
    l10_pts = [0.60, 0.80, 0.90]
    atoi = [15.0, 16.0, 17.0]
    opp_ga = [2.6, 2.8, 3.0]
    cote_min = [0.0, 1.5]
    home_only_opts = [True, False]
    
    best_configs = []
    for spts, lpts, at, oga, cmin, h_only in itertools.product(s_pts, l10_pts, atoi, opp_ga, cote_min, home_only_opts):
        mask = (df['season_pts'] >= spts) & (df['l10_pts'] >= lpts) & (df['atoi'] >= at) & (df['ga_g'] >= oga) & (df['cote_p'] >= cmin)
        if h_only:
            mask = mask & (df['is_home'] == 1)
            
        if not mask.any(): continue
        
        for cap in caps:
            u = kelly_data[cap]['u'][mask]
            g = kelly_data[cap]['gain'][mask]
            valid = u > 0; picks = valid.sum()
            if picks < 20: continue
            
            profit = g[valid].sum(); mise = u[valid].sum()
            if profit > 15:
                best_configs.append({
                    'profit': round(profit, 1), 'roi': round((profit/mise)*100, 1), 'picks': int(picks),
                    'cfg': {'season_pts': spts, 'l10_pts': lpts, 'atoi': at, 'opp_ga': oga, 'cote_min': cmin, 'home_only': h_only, 'cap': cap}
                })
    best_configs.sort(key=lambda x: x['profit'], reverse=True)
    return best_configs[:5]

if __name__ == "__main__":
    t0 = time()
    df, ab, aa, ap = load_data_df()
    print(f"Data loaded: {len(df)} total players.")
    
    print("Optimizing Buteurs...")
    best_but = optimize_buteurs(df)
    
    print("Optimizing Passeurs...")
    best_ast = optimize_passeurs(df)
    
    print("Optimizing Pointeurs...")
    best_pts = optimize_pointeurs(df)
    
    # Calculate best combined scenario
    best_combo = {
        'profit': round((best_but[0]['profit'] if best_but else 0) + 
                        (best_ast[0]['profit'] if best_ast else 0) + 
                        (best_pts[0]['profit'] if best_pts else 0), 1),
        'buteurs': best_but[0] if best_but else None,
        'passeurs': best_ast[0] if best_ast else None,
        'pointeurs': best_pts[0] if best_pts else None
    }
    
    out = {
        'best_combo': best_combo,
        'top_buteurs': best_but,
        'top_passeurs': best_ast,
        'top_pointeurs': best_pts,
        'time_sec': round(time() - t0, 2)
    }
    
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(out, f, indent=2)
    
    print(f"\nDone in {out['time_sec']}s. Best total profit: +{best_combo['profit']} U")
    print(f"Results saved to {OUTPUT_JSON}")
