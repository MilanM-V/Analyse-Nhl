"""
Script heuristique pour évaluer la rentabilité d'un système de tickets combinés (Parlay).
Il simule la création de combinés "Double" (2 sélections) sur les picks ayant une EV+ positive.
"""
import sqlite3
import pandas as pd
import numpy as np
from estimate_ev import get_xgb_prod_model

def simulate_parlays():
    conn = sqlite3.connect('./bot_database.db')
    df = pd.read_sql("SELECT * FROM picks WHERE cote IS NOT NULL AND verdict IN ('ELITE', 'SAFE')", conn)
    conn.close()

    model_data = get_xgb_prod_model()
    if not model_data or 'model' not in model_data:
        print("XGBoost manquant.")
        return
    m = model_data['model']

    # On refait les ev
    picks_valides = []
    for _, row in df.iterrows():
        cote = float(row['cote']) if row['cote'] else 0
        if cote < 1.05: continue
        
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
        ev = (proba * cote) - 1.0
        
        if ev >= 0.02:  # On ne garde que l'EV+ pour les combinés
            picks_valides.append({
                'date': row['date'], 'joueur': row['joueur'], 'equipe': row['equipe'],
                'cote': cote, 'proba': proba, 'won': 1 if pd.notna(row['but']) and int(row['but']) > 0 else 0
            })

    df_ev = pd.DataFrame(picks_valides)
    
    if df_ev.empty:
        print("Pas assez de données EV+ pour simuler.")
        return

    # Simulation de combinés par jour
    total_mise = 0
    total_retour = 0
    total_parlays = 0
    total_wins = 0

    print("=== EV+ DOUBLE PARLAY SIMULATOR ===")
    
    for date, group in df_ev.groupby('date'):
        # On tente de combiner par paires de 2 (sans Same Game Parlay strict)
        picks = group.to_dict('records')
        np.random.shuffle(picks) # Shuffle pour éviter biais
        
        for i in range(0, len(picks)-1, 2):
            p1, p2 = picks[i], picks[i+1]
            
            # Ne pas combiner deux joueurs de la même équipe
            if p1['equipe'] == p2['equipe']:
                continue
                
            cote_totale = p1['cote'] * p2['cote']
            won = 1 if (p1['won'] == 1 and p2['won'] == 1) else 0
            
            total_mise += 1.0
            if won:
                total_retour += cote_totale
                total_wins += 1
            total_parlays += 1

    profit = total_retour - total_mise
    roi = (profit / total_mise * 100) if total_mise > 0 else 0
    hit_rate = (total_wins / total_parlays * 100) if total_parlays > 0 else 0

    print(f"Combinaisons analysées : {total_parlays}")
    print(f"Combinés Gagnants : {total_wins} ({hit_rate:.1f}%)")
    print(f"Profit Net : {profit:.2f} U")
    print(f"ROI : {roi:.2f}%")
    print("-----------------------------------")
    print("Note : La variance d'un système combiné est colossale.")
    print("Les bookmakers l'adorent car la probabilité mathématique s'effondre très vite.")

if __name__ == "__main__":
    simulate_parlays()
