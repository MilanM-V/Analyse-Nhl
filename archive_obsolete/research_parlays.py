import sqlite3
import pandas as pd
from itertools import combinations
import os
import sys

# Compatibilité
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

def run_parlay_research():
    conn = sqlite3.connect('../bot_database.db')
    df = pd.read_sql_query("SELECT * FROM players WHERE but IS NOT NULL", conn)
    cotes_df_but = pd.read_sql_query("SELECT date, joueur, cote FROM picks WHERE cote IS NOT NULL", conn)
    cotes_df_ast = pd.read_sql_query("SELECT date, joueur, cote FROM picks_assists WHERE cote IS NOT NULL", conn)
    cotes_df_pts = pd.read_sql_query("SELECT date, joueur, cote FROM picks_points WHERE cote IS NOT NULL", conn)
    conn.close()

    df['date'] = pd.to_datetime(df['date'])
    cotes_but_dict = cotes_df_but.set_index(['date', 'joueur'])['cote'].to_dict()
    cotes_ast_dict = cotes_df_ast.set_index(['date', 'joueur'])['cote'].to_dict()
    cotes_pts_dict = cotes_df_pts.set_index(['date', 'joueur'])['cote'].to_dict()

    with open("../config/settings.toml", "rb") as f:
        cfg = tomllib.load(f)

    # 1. Collect all V18 valid picks per day
    daily_picks = {}
    for idx, row in df.iterrows():
        p_date = row['date'].strftime("%Y-%m-%d")
        joueur = row['joueur']
        equipe = row['equipe']
        adv = row['adversaire']
        key = (p_date, joueur)
        
        hdcf = float(row['hdcf']) if pd.notna(row['hdcf']) else 0
        atoi = float(row['atoi']) if pd.notna(row['atoi']) else 0
        opp_ga = float(row['ga_g']) if pd.notna(row['ga_g']) else 0
        season_g = float(row['season_g']) if pd.notna(row['season_g']) else 0
        season_a = float(row['season_a']) if pd.notna(row['season_a']) else 0
        season_pts = float(row['season_pts']) if pd.notna(row['season_pts']) else 0
        is_home = bool(row['is_home'])

        if p_date not in daily_picks: daily_picks[p_date] = []

        # Buteur
        bf = cfg["thresholds"].get("buteurs", {})
        if (hdcf >= bf.get("l10_hdcf_min", 0) and atoi >= bf.get("atoi_min", 13.0) and 
            opp_ga >= bf.get("opp_ga_min", 0) and season_g >= bf.get("season_g_min", 0)):
            cote = cotes_but_dict.get(key, 3.20)
            if cote >= bf.get("cote_min", 2.5):
                daily_picks[p_date].append({"j": joueur, "cat": "B", "eq": equipe, "adv": adv, "c": cote, "w": int(row['but']) > 0})

        # Passeur
        af = cfg["thresholds"].get("passeurs", {})
        if (atoi >= af.get("atoi_min", 0) and opp_ga >= af.get("opp_ga_min", 0) and season_a >= af.get("season_a_min", 0)):
            cote = cotes_ast_dict.get(key, 2.40)
            if cote >= af.get("cote_min", 2.0):
                daily_picks[p_date].append({"j": joueur, "cat": "A", "eq": equipe, "adv": adv, "c": cote, "w": int(row['assist']) > 0})

        # Pointeur
        pf = cfg["thresholds"].get("pointeurs", {})
        if (atoi >= pf.get("atoi_min", 0) and opp_ga >= pf.get("opp_ga_min", 0) and season_pts >= pf.get("season_pts_min", 0)):
            cote = cotes_pts_dict.get(key, 1.90)
            if cote >= pf.get("cote_min", 1.5):
                daily_picks[p_date].append({"j": joueur, "cat": "P", "eq": equipe, "adv": adv, "c": cote, "w": int(row['point']) > 0})

    # Test Strategies
    # Strat 1: Double Pointeur (already implemented but let's test globally)
    # Strat 2: Triples Pointeur
    # Strat 3: Buteur + Pointeur
    # Strat 4: Passeur + Pointeur
    # Strat 5: Cross-Cat "Safe" (Point + Point + Point)
    
    strats = {
        "Double Pointeur": {"cond": lambda combo: len(combo)==2 and all(x['cat'] == 'P' for x in combo)},
        "Triple Pointeur": {"cond": lambda combo: len(combo)==3 and all(x['cat'] == 'P' for x in combo)},
        "Double Buteur": {"cond": lambda combo: len(combo)==2 and all(x['cat'] == 'B' for x in combo)},
        "Buteur + Pointeur": {"cond": lambda combo: len(combo)==2 and sum(x['cat'] == 'B' for x in combo)==1 and sum(x['cat'] == 'P' for x in combo)==1},
        "Passeur + Pointeur": {"cond": lambda combo: len(combo)==2 and sum(x['cat'] == 'A' for x in combo)==1 and sum(x['cat'] == 'P' for x in combo)==1},
        "Multi-Cat Mix (3)": {"cond": lambda combo: len(combo)==3 and len(set(x['cat'] for x in combo))>=2}
    }
    
    results = {k: {"staked": 0, "returned": 0, "wins": 0, "total": 0} for k in strats}

    for date, raw_picks in daily_picks.items():
        # Keep highest cote per team to avoid massive combinatorics and realistic picks
        best_picks = {}
        for p in raw_picks:
            m_key = f"{p['eq']}_{p['adv']}_{p['cat']}"
            if m_key not in best_picks or p['c'] > best_picks[m_key]['c']:
                best_picks[m_key] = p
        
        picks = list(best_picks.values())

        # Test doubles
        for combo in combinations(picks, 2):
            # No same game
            if combo[0]['eq'] in (combo[1]['eq'], combo[1]['adv']): continue
            c_tot = combo[0]['c'] * combo[1]['c']
            c_won = combo[0]['w'] and combo[1]['w']
            
            for s_name, strat in strats.items():
                if strat["cond"](combo):
                    results[s_name]["staked"] += 1
                    results[s_name]["total"] += 1
                    if c_won:
                        results[s_name]["returned"] += c_tot
                        results[s_name]["wins"] += 1
                        
        # Test triples
        for combo in combinations(picks, 3):
            # No same game
            games = set()
            valid = True
            for x in combo:
                match_id = "-".join(sorted([x['eq'], x['adv']]))
                if match_id in games: valid = False
                games.add(match_id)
            if not valid: continue
            
            c_tot = combo[0]['c'] * combo[1]['c'] * combo[2]['c']
            c_won = combo[0]['w'] and combo[1]['w'] and combo[2]['w']
            
            for s_name, strat in strats.items():
                if strat["cond"](combo):
                    results[s_name]["staked"] += 1
                    results[s_name]["total"] += 1
                    if c_won:
                        results[s_name]["returned"] += c_tot
                        results[s_name]["wins"] += 1

    print("=== PROFITABILITE DES COMBINES ===")
    for s_name, data in results.items():
        roi = ((data['returned'] - data['staked']) / data['staked'] * 100) if data['staked'] > 0 else 0
        wr = (data['wins'] / data['total'] * 100) if data['total'] > 0 else 0
        print(f"[{s_name}]")
        print(f"  Volume : {data['total']} combinés")
        print(f"  Winrate: {wr:.1f}% ({data['wins']} gagnés)")
        print(f"  ROI    : {roi:+.1f}% (Net: +{(data['returned']-data['staked']):.2f} U)")
        print()

if __name__ == "__main__":
    run_parlay_research()
