
import sys
import os
import pandas as pd
import logging

# Setup paths
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(_ROOT)

from mlb.data.fetcher import get_todays_probables, get_pitcher_historical_stats, get_team_strikeout_rate
from mlb.core.market_filter import evaluate_pitcher_strikeouts

# Désactiver les logs verbeux pour y voir clair
logging.getLogger("MLB").setLevel(logging.WARNING)

def debug_scan():
    print("\n=== DIAGNOSTIC ANALYSE MLB DU SOIR ===\n")
    
    df = get_todays_probables()
    if df.empty:
        print("No games found today.")
        return
        
    for _, row in df.iterrows():
        pitcher = row['Pitcher']
        team = row['Team']
        opp = row['Opp']
        is_home = not str(opp).startswith('@')
        opp_clean = opp[1:] if not is_home else opp
        
        print(f"--- {pitcher} ({team}) vs {opp_clean} ---")
        
        stats = get_pitcher_historical_stats(pitcher)
        if not stats:
            print("   No historical data in DB (IA fallback used)")
            stats = {}
        else:
            print(f"   DB Stats: Avg K: {stats.get('avg_k',0):.1f}, K/9: {stats.get('k_per_9',0):.1f} ({stats.get('games_analyzed')} matches)")
            
        adv_k = get_team_strikeout_rate(opp_clean)
        print(f"   Opponent K-Rate: {adv_k:.1f} K/match")
        
        pick = evaluate_pitcher_strikeouts(pitcher, stats, adv_k, is_home=is_home)
        
        if pick:
            print(f"   IA VALIDATED: {pick['Predicted_K']:.1f} K predicted (Proba: {pick['Proba']:.1%})")
        else:
            from mlb.core.market_filter import _xgb_model
            if _xgb_model:
                k9 = stats.get("k_per_9", 0)
                f_dict = {
                    'is_home': int(is_home),
                    'L5_K9': k9,
                    'Opp_L10_K': adv_k,
                    'L5_Velo': stats.get("avg_velo", 93.0),
                    'L5_SwStr': stats.get("swstr_pct", 0.11),
                    'Umpire_K_Factor': 1.0
                }
                try:
                    exp_f = _xgb_model.get_booster().feature_names
                    f_df = pd.DataFrame([f_dict])
                    if exp_f:
                        f_df = f_df[[f for f in exp_f if f in f_df.columns]]
                    raw_k = float(_xgb_model.predict(f_df)[0])
                    print(f"   IA REJECTED: {raw_k:.1f} K predicted (Threshold: 5.5 K)")
                except:
                    print("   IA REJECTED: Prediction failed")
            else:
                print("   ERROR: IA Model not loaded.")
        print()

if __name__ == "__main__":
    debug_scan()
