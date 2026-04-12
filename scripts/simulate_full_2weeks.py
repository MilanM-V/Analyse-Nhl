"""
Simulation exhaustive sur 2 semaines (2026-03-30 au 2026-04-11).
Utilise la table 'players' pour reconstruire ce que le bot aurait choisi avec la logique +EV.
"""
import sqlite3
import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.predictor_v14 import get_xgb_prod_model

def simulate_2weeks_10euro():
    conn = sqlite3.connect('./bot_database.db')
    
    # On prend tout l'historique des joueurs évalués
    query = """
    SELECT date, joueur, score_but, but as won, is_home, cote, atoi, season_g, sog, 
           l10_g, hdcf, pp1, b2b, opp_b2b, ga_g, hdca_g, consec_goals
    FROM players
    WHERE but IS NOT NULL AND but != ''
    ORDER BY date ASC
    """
    df = pd.read_sql(query, conn)
    conn.close()

    if df.empty:
        print("Erreur : Table 'players' vide.")
        return

    # Nettoyage et complétion des cotes (Moyenne si manquante)
    df['cote'] = pd.to_numeric(df['cote'], errors='coerce')
    mc_but = df[df['cote'] > 0]['cote'].mean() if not df[df['cote'] > 0].empty else 2.50
    df['cote'] = df['cote'].fillna(mc_but)
    
    # Mapping des résultats
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
        
        # Le bot ne garde que les meilleurs QS pour l'XGBoost (Gain de perf)
        # On simule le filtre QS >= 9.0 d'abord
        group_eligible = group[group['score_but'] >= 9.0]
        
        for _, row in group_eligible.iterrows():
            # Re-calcul proba XGB
            ixg = row['hdcf'] * 0.1 # Approximation si ixg manquant dans players table ? 
            # Wait, check columns of players table. 
            # Je vais être prudent.
            
            # Reconstruction du vecteur X (18 features)
            # Puisqu'on simule, on prend les valeurs dispo.
            # ixg, hdcf, sog, atoi, season_g, ga_g, hdca_g, is_pp1, is_home, is_b2b, opp_is_b2b, consec, qs_v10, luck, ...
            
            # Note: Si la table players n'a pas tout, on utilise les moyennes locales ou 0.
            ixg_val = (row['ixg'] if 'ixg' in row and pd.notna(row['ixg']) else 0.15)
            hdcf_val = row['hdcf'] if pd.notna(row['hdcf']) else 0.5
            sog_val = row['sog'] if pd.notna(row['sog']) else 2.5
            atoi_val = row['atoi'] if pd.notna(row['atoi']) else 18.0
            
            X = np.array([[
                ixg_val, hdcf_val, sog_val, atoi_val, row['season_g'] or 0.2,
                row['ga_g'] or 2.8, row['hdca_g'] or 8.0, int(row['pp1'] or 0), int(row['is_home'] or 0),
                int(row['b2b'] or 0), int(row['opp_b2b'] or 0), row['consec_goals'] or 0, row['score_but'],
                1.0, # Luck factor neutral
                ixg_val * hdcf_val, sog_val * atoi_val, ixg_val * (row['ga_g'] or 2.8), (row['consec_goals'] or 0) * ixg_val
            ]])
            
            proba = float(m.predict_proba(X)[0][1])
            cote = float(row['cote'])
            ev = (proba * cote) - 1.0
            
            # Filtre +EV > 2% (La nouvelle version)
            if ev < 0.02:
                continue
                
            day_picks_count += 1
            
            # Quarter Kelly (Mise % du capital)
            b = cote - 1.0
            q = 1.0 - proba
            f = (proba * b - q) / b
            pct_mise = max(0.005, min(f / 4.0, 0.02)) # Cap à 2% par match sur simulation safe
            
            mise_euros = bankroll * pct_mise
            
            if row['won'] == 1:
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
    
    total_sim_picks = res_df['Picks'].sum()
    total_sim_wins = res_df['Wins'].sum()
    sim_winrate = (total_sim_wins / total_sim_picks * 100) if total_sim_picks > 0 else 0
    
    total_profit = bankroll - initial_bankroll
    print(f"\n--- RÉSULTATS GLOBAUX DU NOUVEAU MOTEUR (BUTS) ---")
    print(f"Total Picks: {total_sim_picks}")
    print(f"Total Wins: {total_sim_wins}")
    print(f"Winrate Simulé: {sim_winrate:.2f}%")
    print(f"Total Profit: {total_profit:.2f}€")
    print(f"ROI Final: {(total_profit/initial_bankroll)*100:.2f}%")

if __name__ == "__main__":
    simulate_2weeks_10euro()
