"""
Simulation precise de croissance Quarter Kelly sur la bankroll.
"""
import sqlite3
import pandas as pd
import numpy as np
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot_database.db")

def main():
    conn = sqlite3.connect(DB_PATH)
    
    # On rassemble TOUS les picks selon les regles V17
    df = pd.read_sql("SELECT * FROM players", conn)
    conn.close()
    
    for c in ['score_but', 'sog', 'hdcf', 'season_g', 'season_a', 'season_pts', 'l10_a', 'l10_pts', 'is_home']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            
    df['but'] = pd.to_numeric(df['but'], errors='coerce').fillna(0).astype(int)
    df['assist'] = pd.to_numeric(df['assist'], errors='coerce').fillna(0).astype(int)
    df['point'] = pd.to_numeric(df['point'], errors='coerce').fillna(0).astype(int)
    
    picks = []
    
    # Buteurs
    b_mask = (df['score_but'] >= 11.5) & (df['sog'] >= 3.0) & (df['hdcf'] >= 2.0) & (df['season_g'] >= 0.4) & (df['is_home'] == 1)
    b_picks = df[b_mask].copy()
    b_picks['cat'] = 'BUTEUR'
    b_picks['cote_est'] = 3.27
    b_picks['won'] = b_picks['but'] > 0
    b_picks['proba_est'] = 0.455 # Proba estimee par le WR
    picks.append(b_picks)
    
    # Passeurs
    a_mask = (df['score_assist'] >= 10.0) & (df['season_a'] >= 0.5) & (df['l10_a'] >= 0.8) & (df['is_home'] == 1)
    a_picks = df[a_mask].copy()
    a_picks['cat'] = 'PASSEUR'
    a_picks['cote_est'] = 1.94
    a_picks['won'] = a_picks['assist'] > 0
    a_picks['proba_est'] = 0.554
    picks.append(a_picks)
    
    # Pointeurs
    p_mask = (df['score_point'] >= 10.0) & (df['season_pts'] >= 0.8) & (df['l10_pts'] >= 0.4) & (df['is_home'] == 1)
    p_picks = df[p_mask].copy()
    p_picks['cat'] = 'POINTEUR'
    p_picks['cote_est'] = 1.57
    p_picks['won'] = p_picks['point'] > 0
    p_picks['proba_est'] = 0.675
    picks.append(p_picks)
    
    all_picks = pd.concat(picks)
    all_picks = all_picks.sort_values(by=['date', 'cat'])
    
    # Simulation
    bankroll = 100.0 # Base 100
    history = [bankroll]
    
    for _, row in all_picks.iterrows():
        b = row['cote_est'] - 1
        p = row['proba_est']
        q = 1 - p
        
        # Formule Full Kelly (fraction du capital)
        kelly_fraction = (p * b - q) / b
        
        if kelly_fraction > 0:
            quarter_kelly = kelly_fraction / 4.0
            
            # Application de caps (par config)
            if row['cat'] == 'BUTEUR':
                max_bet = 0.03 # 3% max
            else:
                max_bet = 0.02 # 2% max
                
            bet_fraction = min(quarter_kelly, max_bet)
            mise = bankroll * bet_fraction
            
            if row['won']:
                bankroll += mise * b
            else:
                bankroll -= mise
                
            history.append(bankroll)

    print(f"\n--- SIMULATION QUARTER KELLY ---")
    print(f"Bankroll Initiale : 100 U")
    print(f"Bankroll Finale   : {bankroll:.2f} U")
    print(f"Profit Net        : {bankroll - 100:.2f} U")
    print(f"Croissance du cap.: {((bankroll/100)-1)*100:.1f} %\n")
    
    # Ratio Bankroll 10 -> arrivee
    br_10 = bankroll / 10.0
    print(f"Avec Bankroll 10 => Arrivee à {br_10:.2f} U")

if __name__ == "__main__":
    main()
