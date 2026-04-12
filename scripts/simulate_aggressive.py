"""
Simulation AGGRESSIVE sur 2 semaines (50% de mise par pick).
"""
import sqlite3
import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.predictor_v14 import get_xgb_prod_model

def simulate_aggressive():
    conn = sqlite3.connect('./bot_database.db')
    query = """
    SELECT date, joueur, score_but, but as won, is_home, cote, atoi, season_g, sog, 
           l10_g, hdcf, pp1, b2b, opp_b2b, ga_g, hdca_g, consec_goals
    FROM players
    WHERE but IS NOT NULL AND but != ''
    ORDER BY date ASC
    """
    df = pd.read_sql(query, conn)
    conn.close()

    df['cote'] = pd.to_numeric(df['cote'], errors='coerce')
    mc_but = df[df['cote'] > 0]['cote'].mean() if not df[df['cote'] > 0].empty else 2.50
    df['cote'] = df['cote'].fillna(mc_but)
    df['won'] = pd.to_numeric(df['won'], errors='coerce').fillna(0).apply(lambda x: 1 if x > 0 else 0)

    model_data = get_xgb_prod_model()
    m = model_data['model']

    bankroll = 10.0
    initial_bankroll = 10.0
    daily_stats = []
    
    for date, group in df.groupby('date'):
        day_profit = 0
        day_picks_count = 0
        day_wins = 0
        
        group_eligible = group[group['score_but'] >= 9.0]
        
        for _, row in group_eligible.iterrows():
            # Reconstruction du vecteur X (Même logique que le bot)
            ixg_val = (row['ixg'] if 'ixg' in row and pd.notna(row['ixg']) else 0.15)
            X = np.array([[
                ixg_val, row['hdcf'] or 0.5, row['sog'] or 2.5, row['atoi'] or 18.0, row['season_g'] or 0.2,
                row['ga_g'] or 2.8, row['hdca_g'] or 8.0, int(row['pp1'] or 0), int(row['is_home'] or 0),
                int(row['b2b'] or 0), int(row['opp_b2b'] or 0), row['consec_goals'] or 0, row['score_but'],
                1.0, ixg_val * (row['hdcf'] or 0.5), (row['sog'] or 2.5) * (row['atoi'] or 18.0), 
                ixg_val * (row['ga_g'] or 2.8), (row['consec_goals'] or 0) * ixg_val
            ]])
            
            proba = float(m.predict_proba(X)[0][1])
            cote = float(row['cote'])
            ev = (proba * cote) - 1.0
            
            if ev < 0.02:
                continue
                
            day_picks_count += 1
            
            # MISE AGGRESSIVE : 50% de la Bankroll actuelle
            mise_euros = bankroll * 0.50
            if bankroll <= 0: break

            if row['won'] == 1:
                day_wins += 1
                gain = mise_euros * (cote - 1.0)
                bankroll += gain
                day_profit += gain
            else:
                bankroll -= mise_euros
                day_profit -= mise_euros

        daily_stats.append({
            'Date': date, 'Picks': day_picks_count, 'Wins': day_wins,
            'Gain Jour (€)': round(day_profit, 2), 'Bankroll (€)': round(bankroll, 2)
        })

    res_df = pd.DataFrame(daily_stats)
    print(res_df.to_markdown(index=False))
    print(f"\nProfit Total: {bankroll - initial_bankroll:.2f}€")
    print(f"ROI Final: {((bankroll - initial_bankroll)/initial_bankroll)*100:.2f}%")

if __name__ == "__main__":
    simulate_aggressive()
