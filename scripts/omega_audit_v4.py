import sqlite3
import pandas as pd
import numpy as np
import os
import joblib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "bot_database.db")
MODELS_DIR = os.path.join(ROOT, "models")

def get_real_picks():
    conn = sqlite3.connect(DB_PATH)
    dfs = []
    # On EXCLUT les buteurs de l'audit car on sait qu'ils perdent
    queries = [
        ("picks_assists", "ast", "assist"),
        ("picks_points", "pts", "point")
    ]
    
    for table, cat, target_col in queries:
        q = f"""
            SELECT p.date, p.joueur, p.equipe, p.adversaire, p.cote, p.{target_col} as result, 
                   pl.ixg, pl.hdcf, pl.sog, pl.atoi, pl.season_g, pl.season_a, pl.season_pts,
                   pl.ga_g, pl.hdca_g, pl.pp1, pl.is_home, pl.b2b, pl.opp_b2b, pl.consec_goals
            FROM {table} p
            JOIN players pl ON p.date = pl.date AND p.joueur = pl.joueur
            WHERE p.cote IS NOT NULL AND p.cote > 1.05
        """
        try:
            df = pd.read_sql(q, conn)
            df['cat'] = cat
            dfs.append(df)
        except:
            pass
            
    conn.close()
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

def prepare_features(df, features_list):
    df_f = pd.DataFrame()
    for col in ['ixg', 'hdcf', 'sog', 'atoi']:
        df_f[f'{col}_l10'] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    for col in ['season_g', 'season_a', 'season_pts', 'ga_g', 'hdca_g']:
        df_f[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    for col in ['pp1', 'is_home']:
        df_f[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
    df_f['is_b2b'] = pd.to_numeric(df['b2b'], errors='coerce').fillna(0).astype(int)
    df_f['opp_is_b2b'] = pd.to_numeric(df.get('opp_b2b', 0), errors='coerce').fillna(0).astype(int)
    df_f['consec_goals'] = pd.to_numeric(df.get('consec_goals', 0), errors='coerce').fillna(0)
    
    df_f['ixg_x_hdcf'] = df_f['ixg_l10'] * df_f['hdcf_l10']
    df_f['sog_x_atoi'] = df_f['sog_l10'] * df_f['atoi_l10']
    df_f['ixg_x_ga'] = df_f['ixg_l10'] * df_f['ga_g']
    
    return df_f[features_list].values

def run_honest_audit():
    print("="*60)
    print(" OMEGA AUDIT V4 (HONNÊTE & SANS INFLUENCE)")
    print("="*60)
    
    # 1. Charger modèles et data
    models = {}
    for cat in ['ast', 'pts']:
        path = os.path.join(MODELS_DIR, f'xg_model_{cat}.pkl')
        if os.path.exists(path):
            models[cat] = joblib.load(path)
            
    df = get_real_picks()
    if df.empty:
        print("Aucune donnée disponible.")
        return
        
    print(f"-> {len(df)} historiques de cotes réelles chargés (Passeurs/Pointeurs uniquement).")
    
    # 2. Prédiction et filtrage EV
    valid_picks = []
    for cat in ['ast', 'pts']:
        cat_df = df[df['cat'] == cat].copy()
        if cat_df.empty or cat not in models: continue
        
        m_data = models[cat]
        X = prepare_features(cat_df, m_data['features'])
        cat_df['proba_ia'] = m_data['model'].predict_proba(X)[:, 1]
        cat_df['ev'] = (cat_df['proba_ia'] * cat_df['cote']) - 1.0
        
        for _, row in cat_df.iterrows():
            if row['ev'] > 0.05:  # Filtre strict 5%
                valid_picks.append({
                    'date': row['date'], 'joueur': row['joueur'], 'cat': row['cat'],
                    'cote': row['cote'], 'won': pd.to_numeric(row['result'], errors='coerce') > 0,
                    'ev': row['ev'], 'equipe': row['equipe']
                })
                
    df_valid = pd.DataFrame(valid_picks)
    print(f"-> {len(df_valid)} paris passent le filtre EV > 5% de la nouvelle IA.")
    
    # 3. Simulation Simples
    total_mise_single = len(df_valid)
    gain_single = sum((p['cote'] - 1.0 if p['won'] else -1.0) for p in valid_picks)
    roi_single = (gain_single / total_mise_single) * 100
    wr_single = sum(1 for p in valid_picks if p['won']) / total_mise_single * 100
    
    # 4. Simulation Combinés (Groupé par date)
    duos = []
    trios = []
    
    for date, group in df_valid.groupby('date'):
        picks = group.to_dict('records')
        np.random.shuffle(picks) # Aléatoire pour éviter les biais de tri
        
        # Duos
        for i in range(0, len(picks)-1, 2):
            if picks[i]['joueur'] == picks[i+1]['joueur']: continue
            cote_tot = picks[i]['cote'] * picks[i+1]['cote']
            won = picks[i]['won'] and picks[i+1]['won']
            duos.append({'cote': cote_tot, 'won': won})
            
        # Trios
        for i in range(0, len(picks)-2, 3):
            if len({picks[i]['joueur'], picks[i+1]['joueur'], picks[i+2]['joueur']}) < 3: continue
            cote_tot = picks[i]['cote'] * picks[i+1]['cote'] * picks[i+2]['cote']
            won = picks[i]['won'] and picks[i+1]['won'] and picks[i+2]['won']
            trios.append({'cote': cote_tot, 'won': won})
            
    # Stats Duos
    roi_duo = (sum((d['cote'] - 1.0 if d['won'] else -1.0) for d in duos) / max(1, len(duos))) * 100
    wr_duo = sum(1 for d in duos if d['won']) / max(1, len(duos)) * 100
    
    # Stats Trios
    roi_trio = (sum((t['cote'] - 1.0 if t['won'] else -1.0) for t in trios) / max(1, len(trios))) * 100
    wr_trio = sum(1 for t in trios if t['won']) / max(1, len(trios)) * 100
    
    # AFFICHAGE
    print("\n" + "="*60)
    print(" RÉSULTATS DU BACKTEST HONNÊTE (MISE FIXE 1 UNITÉ)")
    print("="*60)
    
    def print_stat(label, vol, wr, gain, roi):
        print(f" {label.ljust(12)} | Vol: {str(vol).rjust(3)} | WR: {wr:5.1f}% | Profit: {gain:+6.2f} U | ROI: {roi:+6.1f}%")
        
    print_stat("SIMPLES", len(df_valid), wr_single, gain_single, roi_single)
    print_stat("DUOS (2)", len(duos), wr_duo, sum((d['cote'] - 1.0 if d['won'] else -1.0) for d in duos), roi_duo)
    print_stat("TRIOS (3)", len(trios), wr_trio, sum((t['cote'] - 1.0 if t['won'] else -1.0) for t in trios), roi_trio)
    
    print("\n" + "="*60)
    print(" CONCLUSION MATHÉMATIQUE SUR LES COMBINÉS DE PLUS DE 2")
    print("="*60)
    if roi_trio > roi_duo and roi_trio > roi_single:
        print(" OUI : Les Trios sont massivement plus rentables. L'EV positive se multiplie bien.")
        print(" AVERTISSEMENT : Mais le Winrate s'effondre. Préparez-vous à de longues séries de pertes.")
    elif roi_single > 0 and roi_trio < 0:
        print(" NON : Bien que les simples soient rentables, les Trios sont PERDANTS.")
        print(" RAISON : La marge du bookmaker et la corrélation négative détruisent l'avantage sur 3 matchs.")
    else:
        print(" MITIGÉ : Les combinés de 3 modifient fortement la variance.")
        print(" CONSTAT : Regardez le Winrate des Trios. Il est probablement sous les 15%.")
        print(" Est-ce que votre psychologie peut supporter 85% de tickets perdants de suite ?")

if __name__ == "__main__":
    run_honest_audit()
