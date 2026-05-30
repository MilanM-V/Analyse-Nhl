import sqlite3
import pandas as pd
import numpy as np
import os
import joblib
from itertools import combinations
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)
sys.path.append(os.path.dirname(ROOT))
from shared.kelly import calculate_quarter_kelly

DB_PATH = os.path.join(ROOT, "bot_database.db")
MODELS_DIR = os.path.join(ROOT, "models")

def get_real_picks(cat):
    conn = sqlite3.connect(DB_PATH)
    table_map = {'but': 'picks', 'ast': 'picks_assists'}
    target_map = {'but': 'but', 'ast': 'assist'}
    table = table_map[cat]
    target_col = target_map[cat]
    
    q = f"""
        SELECT p.date, p.joueur, p.equipe, p.adversaire, p.cote, p.{target_col} as result, 
               pl.ixg, pl.hdcf, pl.sog, pl.atoi, pl.season_g, pl.season_a, pl.season_pts,
               pl.ga_g, pl.hdca_g, pl.pp1, pl.is_home, pl.b2b, pl.opp_b2b, pl.consec_goals,
               pl.pk_pct, pl.cf_pct, pl.pdo
        FROM {table} p
        JOIN players pl ON p.date = pl.date AND p.joueur = pl.joueur
        WHERE p.cote IS NOT NULL AND p.cote > 1.05
    """
    df = pd.read_sql(q, conn)
    conn.close()
    
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        for col in ['ixg', 'hdcf', 'sog', 'atoi', 'season_g', 'season_a', 'season_pts', 'ga_g', 'hdca_g', 'pp1', 'is_home', 'b2b', 'opp_b2b', 'consec_goals', 'pk_pct', 'cf_pct', 'pdo']:
            df[col] = pd.to_numeric(df.get(col, 0), errors='coerce').fillna(0)
            
        df['target'] = (pd.to_numeric(df['result'], errors='coerce').fillna(0) > 0).astype(int)
        
        df['ixg_x_hdcf'] = df['ixg'] * df['hdcf']
        df['sog_x_atoi'] = df['sog'] * df['atoi']
        df['ixg_x_ga'] = df['ixg'] * df['ga_g']
    return df

def simulate():
    models = {}
    for cat in ['but', 'ast']:
        path = os.path.join(MODELS_DIR, f'ml_model_{cat}.pkl')
        if os.path.exists(path):
            models[cat] = joblib.load(path)
            
    print("="*60)
    print(" SIMULATION COMPLETE DU NOUVEAU MOTEUR")
    print("="*60)
    
    total_gains = 0.0
    total_mises = 0.0
    total_paris = 0
    total_won = 0
    
    ev_picks = []
    
    for cat in ['but', 'ast']:
        if cat not in models: continue
        df = get_real_picks(cat)
        if df.empty: continue
        
        m_data = models[cat]
        feats = m_data.get('features_list', m_data.get('features', []))
        
        # Ensure all features exist
        for f in feats:
            if f not in df.columns:
                df[f] = 0.0
                
        X = df[feats].values
        if 'scaler' in m_data:
            X = m_data['scaler'].transform(X)
            
        preds = m_data['model'].predict_proba(X)[:, 1]
        
        df_sim = df.copy()
        df_sim['proba'] = preds
        df_sim['ev'] = (df_sim['proba'] * df_sim['cote']) - 1.0
        print(f"[{cat.upper()}] EV Stats -> Min: {df_sim['ev'].min():.4f}, Max: {df_sim['ev'].max():.4f}, Mean: {df_sim['ev'].mean():.4f}")
        print(f"[{cat.upper()}] Probas -> Min: {df_sim['proba'].min():.4f}, Max: {df_sim['proba'].max():.4f}, Mean: {df_sim['proba'].mean():.4f}")
        
        # Kelly logic EV > 0.05
        df_play = df_sim[df_sim['ev'] > 0.05].copy()
        cat_gains, cat_mises, cat_paris, cat_won = 0.0, 0.0, 0, 0
        
        for _, row in df_play.iterrows():
            kelly_str = calculate_quarter_kelly(row['proba'], row['cote'], categorie="PASSEUR" if cat == "ast" else "BUTEUR")
            try:
                mise = float(kelly_str.replace('U', '').strip())
            except:
                mise = 0.0
                
            if mise > 0:
                cat_mises += mise
                cat_paris += 1
                
                ev_picks.append({
                    'date': row['date'], 'joueur': row['joueur'], 'equipe': row['equipe'],
                    'cote': float(row['cote']), 'won': bool(row['target']), 'cat': cat
                })
                
                if row['target'] == 1:
                    cat_gains += (row['cote'] * mise - mise)
                    cat_won += 1
                else:
                    cat_gains -= mise
                    
        cat_roi = (cat_gains / cat_mises * 100) if cat_mises > 0 else 0
        print(f"[{cat.upper()}] Paris: {cat_paris} | Winrate: {cat_won/max(1, cat_paris)*100:.1f}% | Mises: {cat_mises:.2f} U | Profit: {cat_gains:+.2f} U | ROI: {cat_roi:+.1f}%")
        
        total_gains += cat_gains
        total_mises += cat_mises
        total_paris += cat_paris
        total_won += cat_won
        
    print("-" * 60)
    total_roi = (total_gains / total_mises * 100) if total_mises > 0 else 0
    print(f"[TOTAL PARIS SIMPLES] Paris: {total_paris} | Winrate: {total_won/max(1, total_paris)*100:.1f}% | Profit: {total_gains:+.2f} U | ROI: {total_roi:+.1f}%\n")
    
    # === SIMULATION DES COMBINES (PASSEUR+PASSEUR MEME EQUIPE) ===
    print("="*60)
    print(" SIMULATION DES COMBINES SYNERGIQUES (PASSEUR + PASSEUR)")
    print("="*60)
    df_picks = pd.DataFrame(ev_picks)
    if df_picks.empty:
        print("Aucun pick disponible pour les combinés.")
        return
        
    combo_gains, combo_mises, combo_paris, combo_won = 0.0, 0.0, 0, 0
    
    for date, day_group in df_picks.groupby('date'):
        day = day_group.to_dict('records')
        asts = [p for p in day if p['cat'] == 'ast']
        for a1, a2 in combinations(asts, 2):
            if a1['equipe'] == a2['equipe']:
                combo_paris += 1
                mise = 1.0 # 1 U flat bet for combos
                combo_mises += mise
                
                cote_tot = a1['cote'] * a2['cote']
                if a1['won'] and a2['won']:
                    combo_gains += (cote_tot * mise - mise)
                    combo_won += 1
                else:
                    combo_gains -= mise
                    
    combo_roi = (combo_gains / combo_mises * 100) if combo_mises > 0 else 0
    print(f"[COMBINES] Paris: {combo_paris} | Winrate: {combo_won/max(1, combo_paris)*100:.1f}% | Mises: {combo_mises:.2f} U | Profit: {combo_gains:+.2f} U | ROI: {combo_roi:+.1f}%")

if __name__ == "__main__":
    simulate()
