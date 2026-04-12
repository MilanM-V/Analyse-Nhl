"""
Simulation de gains sur 2 semaines avec 10€ de départ.
Stratégie: +EV (>2%) + Quarter Kelly (1 Unit = 1% Bankroll).
"""
import sqlite3
import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.predictor_v14 import get_xgb_prod_model

def simulate_10euro():
    conn = sqlite3.connect('./bot_database.db')
    # On récupère les colonnes nécessaires pour reconstruire le XGBoost
    df = pd.read_sql("""
        SELECT date, joueur, score, cote, but, ixg, hdcf, sog, atoi, 
               season_g, ga_g, hdca_g, pp1, is_home, b2b, opp_b2b, 
               consec_goals, l10_g, verdict
        FROM picks 
        WHERE cote IS NOT NULL AND cote > 1.05
    """, conn)
    conn.close()

    if df.empty:
        print("Aucune donnée pour la simulation.")
        return

    model_data = get_xgb_prod_model()
    m = model_data['model']

    bankroll = 10.0
    initial_bankroll = 10.0
    
    daily_stats = []
    
    # On traite par jour
    for date, group in df.groupby('date'):
        day_profit = 0
        day_picks_count = 0
        day_wins = 0
        
        for _, row in group.iterrows():
            # Re-calcul de la proba XGBoost pour être fidèle à "cette version"
            ixg = row['ixg'] or 0.0
            X = np.array([[
                ixg, row['hdcf'] or 0.0, row['sog'] or 0.0, row['atoi'] or 0.0, row['season_g'] or 0.0,
                row['ga_g'] or 0.0, row['hdca_g'] or 0.0, row['pp1'] or 0, row['is_home'] or 0, 
                row['b2b'] or 0, row['opp_b2b'] or 0, row['consec_goals'] or 0, row['score'],
                (row['l10_g']*10) / max(ixg*10, 0.01) if ixg>0 else 1.0, 
                ixg * (row['hdcf'] or 0), (row['sog'] or 0) * (row['atoi'] or 0), 
                ixg * (row['ga_g'] or 0), (row['consec_goals'] or 0) * ixg
            ]])
            
            proba = float(m.predict_proba(X)[0][1])
            cote = float(row['cote'])
            ev = (proba * cote) - 1.0
            
            # Filtre +EV > 2%
            if ev < 0.02:
                continue
                
            day_picks_count += 1
            
            # Calcul mise (Quarter Kelly)
            b = cote - 1.0
            q = 1.0 - proba
            f = (proba * b - q) / b
            quarter_f = f / 4.0
            
            # On suit la logique du bot : 1 Unit = 1% du capital actuel (Compound)
            # quarter_f * 100 donne les "Units"
            pct_mise = max(0.005, min(quarter_f, 0.05)) # Max 5% par pick par sécurité
            mise_euros = bankroll * pct_mise
            
            won = 1 if pd.notna(row['but']) and int(row['but']) > 0 else 0
            if won:
                day_wins += 1
                gain = mise_euros * b
                bankroll += gain
                day_profit += gain
            else:
                bankroll -= mise_euros
                day_profit -= mise_euros

        daily_stats.append({
            'Date': date,
            'Picks': day_picks_count,
            'Wins': day_wins,
            'Gain Jour (€)': round(day_profit, 2),
            'Bankroll (€)': round(bankroll, 2)
        })

    res_df = pd.DataFrame(daily_stats)
    print(res_df.to_markdown(index=False))
    
    total_profit = bankroll - initial_bankroll
    roi = (total_profit / initial_bankroll) * 100
    print(f"\nTotal Profit: {total_profit:.2f}€")
    print(f"ROI Final: {roi:.2f}%")

if __name__ == "__main__":
    simulate_10euro()
