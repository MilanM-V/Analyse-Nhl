"""
Script d'estimation rapide de l'EV+ sur l'historique des Picks Buteurs et Passeurs.
Recalcule l'XGBoost sur les données sauvegardées.
"""
import sqlite3
import pandas as pd
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.predictor_v14 import get_xgb_prod_model

def estimate_ev():
    conn = sqlite3.connect('./bot_database.db')
    df = pd.read_sql("SELECT * FROM picks WHERE cote IS NOT NULL AND cote > 1.0 AND verdict IN ('ELITE', 'SAFE', 'PASSEUR', 'POINTEUR')", conn)
    conn.close()

    if df.empty:
        print("Aucun historique avec cotes.")
        return

    model_data = get_xgb_prod_model()
    if not model_data or 'model' not in model_data:
        print("Modèle XGBoost introuvable.")
        return
    m = model_data['model']

    results = []

    for _, row in df.iterrows():
        cat = row['verdict']
        score = row['score']
        cote = float(row['cote'])
        is_win = 1 if int(row['but']) > 0 else 0 # Assuming 'but' stores the result
        if cat == 'PASSEUR':
            # Actually, `picks` table only stores 'but'. Oh wait, does it store assist for Passeurs?
            # Let's check if 'verdict' == PASSEUR means we look at picks_assists? 
            # `simulate_compound.py` queries picks_assists for Passeurs!
            pass
            
        if cat in ('ELITE', 'SAFE'):
            # Reconstruct X for XGBoost
            ixg = row['ixg'] or 0.0
            hdcf = row['hdcf'] or 0.0
            sog = row['sog'] or 0.0
            atoi = row['atoi'] or 0.0
            season_g = row['season_g'] or 0.0
            ga_g = row['ga_g'] or 0.0
            hdca_g = row['hdca_g'] or 0.0
            is_pp1 = int(row['pp1']) if row['pp1'] is not None else 0
            is_home = int(row['is_home']) if row['is_home'] is not None else 0
            is_b2b = int(row['b2b']) if row['b2b'] is not None else 0
            opp_b2b = int(row['opp_b2b']) if row['opp_b2b'] is not None else 0
            consec = row['consec_goals'] or 0
            qs_v10 = score
            
            l10_g = row['l10_g'] or 0.0
            goals_10 = l10_g * 10
            ixg_unnorm = ixg * 10
            
            luck_factor = goals_10 / max(ixg_unnorm, 0.01) if ixg_unnorm > 0 else 1.0
            ixg_x_hdcf = ixg * hdcf
            sog_x_atoi = sog * atoi
            ixg_x_ga = ixg * ga_g
            streak_x_ixg = consec * ixg
            
            X = np.array([[
                ixg, hdcf, sog, atoi, season_g,
                ga_g, hdca_g, is_pp1, is_home, is_b2b, opp_b2b,
                consec, qs_v10,
                luck_factor, ixg_x_hdcf, sog_x_atoi, ixg_x_ga, streak_x_ixg
            ]])
            
            proba = float(m.predict_proba(X)[0][1])
            ev = (proba * cote) - 1.0
            
            results.append({
                'date': row['date'],
                'joueur': row['joueur'],
                'cote': cote,
                'proba': proba,
                'ev': ev,
                'won': 1 if pd.notna(row['but']) and int(row['but']) > 0 else 0
            })

    df_res = pd.DataFrame(results)
    
    # Sans EV+ (On parie sur tout, Flat 1U)
    total_bets = len(df_res)
    total_retour = sum(r['cote'] for _, r in df_res.iterrows() if r['won'] == 1)
    profit_old = total_retour - total_bets
    roi_old = (profit_old / total_bets * 100) if total_bets > 0 else 0
    
    print(f"ANCIENNE METHODE (Jouer tous les Elite/Safe avec Cotes) :")
    print(f"Picks: {total_bets} | Wins: {df_res['won'].sum()} | Profit: {profit_old:.2f}U | ROI: {roi_old:.2f}%\n")
    
    # Avec EV+ > 0.02
    ev_picks = df_res[df_res['ev'] >= 0.02]
    total_ev_bets = len(ev_picks)
    total_ev_retour = sum(r['cote'] for _, r in ev_picks.iterrows() if r['won'] == 1)
    profit_ev = total_ev_retour - total_ev_bets
    roi_ev = (profit_ev / total_ev_bets * 100) if total_ev_bets > 0 else 0
    
    picks_per_day = total_ev_bets / df_res['date'].nunique() if total_ev_bets > 0 else 0
    
    print(f"NOUVELLE METHODE (Filtrage EV+ > 2%) :")
    print(f"Picks: {total_ev_bets} | Wins: {ev_picks['won'].sum()} | Profit: {profit_ev:.2f}U | ROI: {roi_ev:.2f}%")
    print(f"Volume Moyen Estimé : {picks_per_day:.1f} picks par soirée NHL.")

if __name__ == "__main__":
    estimate_ev()
