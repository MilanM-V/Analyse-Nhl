import sqlite3
import pandas as pd
import numpy as np
import os
import joblib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "bot_database.db")
MODELS_DIR = os.path.join(ROOT, "models")

def load_models():
    models = {}
    for cat in ['but', 'ast', 'pts']:
        path = os.path.join(MODELS_DIR, f'xg_model_{cat}.pkl')
        if os.path.exists(path):
            models[cat] = joblib.load(path)
    return models

def get_real_picks():
    conn = sqlite3.connect(DB_PATH)
    dfs = []
    queries = [
        ("picks", "but"),
        ("picks_assists", "ast"),
        ("picks_points", "pts")
    ]
    
    for table, cat in queries:
        target_col = 'but' if cat == 'but' else ('assist' if cat == 'ast' else 'point')
        
        # On ne prend QUE les paris avec une VRAIE cote du bookmaker (pas d'imputation)
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
        except Exception as e:
            pass
            
    conn.close()
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

def prepare_features(df, features_list):
    df_f = pd.DataFrame()
    
    # Remplissage sécurisé
    df_f['ixg_l10'] = pd.to_numeric(df['ixg'], errors='coerce').fillna(0)
    df_f['hdcf_l10'] = pd.to_numeric(df['hdcf'], errors='coerce').fillna(0)
    df_f['sog_l10'] = pd.to_numeric(df['sog'], errors='coerce').fillna(0)
    df_f['atoi_l10'] = pd.to_numeric(df['atoi'], errors='coerce').fillna(0)
    
    df_f['season_g'] = pd.to_numeric(df['season_g'], errors='coerce').fillna(0)
    df_f['season_a'] = pd.to_numeric(df['season_a'], errors='coerce').fillna(0)
    df_f['season_pts'] = pd.to_numeric(df['season_pts'], errors='coerce').fillna(0)
    
    df_f['ga_g'] = pd.to_numeric(df['ga_g'], errors='coerce').fillna(0)
    df_f['hdca_g'] = pd.to_numeric(df['hdca_g'], errors='coerce').fillna(0)
    
    df_f['pp1'] = pd.to_numeric(df['pp1'], errors='coerce').fillna(0).astype(int)
    df_f['is_home'] = pd.to_numeric(df['is_home'], errors='coerce').fillna(0).astype(int)
    df_f['is_b2b'] = pd.to_numeric(df['b2b'], errors='coerce').fillna(0).astype(int)
    df_f['opp_is_b2b'] = pd.to_numeric(df.get('opp_b2b', 0), errors='coerce').fillna(0).astype(int)
    df_f['consec_goals'] = pd.to_numeric(df.get('consec_goals', 0), errors='coerce').fillna(0)
    
    # Interactions
    df_f['ixg_x_hdcf'] = df_f['ixg_l10'] * df_f['hdcf_l10']
    df_f['sog_x_atoi'] = df_f['sog_l10'] * df_f['atoi_l10']
    df_f['ixg_x_ga'] = df_f['ixg_l10'] * df_f['ga_g']
    
    # Garantir l'ordre exact des features pour XGBoost
    return df_f[features_list].values

def calculate_kelly(proba, cote, fraction=0.125, max_bet=2.0):
    b = cote - 1.0
    f = (proba * b - (1 - proba)) / b
    if f <= 0: return 0.0
    bet = f * fraction * 100
    return min(bet, max_bet)

def simulate_real_profit():
    models = load_models()
    if not models:
        print("Modeles introuvables.")
        return
        
    df = get_real_picks()
    if df.empty:
        print("Aucune donnee de pari trouvee.")
        return
        
    print(f"Evaluation de {len(df)} opportunites avec de VRAIES cotes historiques...")
    
    results = []
    
    for cat in ['but', 'ast', 'pts']:
        cat_df = df[df['cat'] == cat].copy()
        if cat_df.empty or cat not in models: continue
        
        m_data = models[cat]
        X = prepare_features(cat_df, m_data['features'])
        probas = m_data['model'].predict_proba(X)[:, 1]
        
        cat_df['proba_ia'] = probas
        cat_df['ev'] = (cat_df['proba_ia'] * cat_df['cote']) - 1.0
        
        for _, row in cat_df.iterrows():
            # FILTRE STRICT: On ne parie que si l'IA trouve une EV > 5%
            if row['ev'] > 0.05:
                won = pd.to_numeric(row['result'], errors='coerce') > 0
                # Gestion très prudente du capital (1/8 de Kelly)
                mise = calculate_kelly(row['proba_ia'], row['cote'], fraction=0.125) 
                
                if mise > 0:
                    gain = (row['cote'] * mise - mise) if won else -mise
                    results.append({
                        'date': row['date'], 'joueur': row['joueur'], 'cat': cat,
                        'cote': row['cote'], 'proba': row['proba_ia'], 'ev': row['ev'],
                        'mise': mise, 'gain': gain, 'won': won
                    })
                    
    df_res = pd.DataFrame(results)
    if df_res.empty:
        print("\nAucun pari ne passe le filtre strict d'EV > 5%. Le modele vous a protege de perdre de l'argent.")
        return
        
    total_mise = df_res['mise'].sum()
    total_gain = df_res['gain'].sum()
    roi = (total_gain / total_mise) * 100
    winrate = df_res['won'].mean() * 100
    
    print("\n" + "="*50)
    print(" RESULTAT REEL (Avec le nouveau cerveau IA)")
    print("="*50)
    print(f" Volume: {len(df_res)} paris (EV moyenne: +{df_res['ev'].mean()*100:.1f}%)")
    print(f" Winrate: {winrate:.1f}%")
    print(f" Mise Totale: {total_mise:.1f} U")
    print(f" Profit Net: {total_gain:+.2f} U")
    print(f" ROI: {roi:+.1f}%")
    
    print("\n Details par Categorie:")
    for c in ['but', 'ast', 'pts']:
        c_df = df_res[df_res['cat'] == c]
        if not c_df.empty:
            c_roi = (c_df['gain'].sum() / c_df['mise'].sum()) * 100
            print(f" - {c.upper()}: {len(c_df)} paris, {c_df['gain'].sum():+.1f} U (ROI: {c_roi:+.1f}%)")
            
    # Simulation Combinés (Duo) sur les picks rentables
    print("\n" + "="*50)
    print(" SIMULATION DE COMBINES (DUO PARLAYS)")
    print(" (Uniquement sur AST et PTS avec EV > 5%)")
    print("="*50)
    
    # On filtre les buteurs car ils sont perdants
    df_parlay = df_res[df_res['cat'] != 'but'].copy()
    
    total_parlay_mise = 0
    total_parlay_gain = 0
    parlays_won = 0
    parlays_total = 0
    
    for date, group in df_parlay.groupby('date'):
        picks = group.to_dict('records')
        np.random.shuffle(picks)
        
        # Combiner par paires
        for i in range(0, len(picks)-1, 2):
            p1 = picks[i]
            p2 = picks[i+1]
            
            # Ne pas combiner deux joueurs de la même équipe ou du même match si possible (simplifié ici par sécurité)
            if p1['joueur'] == p2['joueur']: continue
            
            cote_totale = p1['cote'] * p2['cote']
            mise = 1.0 # Mise fixe de 1 U pour les combinés
            
            won = p1['won'] and p2['won']
            
            total_parlay_mise += mise
            if won:
                total_parlay_gain += (cote_totale * mise - mise)
                parlays_won += 1
            else:
                total_parlay_gain -= mise
            parlays_total += 1
            
    if parlays_total > 0:
        parlay_roi = (total_parlay_gain / total_parlay_mise) * 100
        parlay_wr = (parlays_won / parlays_total) * 100
        print(f" Volume: {parlays_total} Combines")
        print(f" Winrate: {parlay_wr:.1f}%")
        print(f" Profit Net: {total_parlay_gain:+.2f} U")
        print(f" ROI: {parlay_roi:+.1f}%")
        if parlay_roi > roi:
            print("\n => CONCLUSION: Les combines AUGMENTENT la rentabilite !")
        else:
            print("\n => CONCLUSION: Les combines SONT MOINS RENTABLES que les paris simples (a cause de la variance).")
    else:
        print(" Pas assez de paris le meme jour pour faire des combines.")

if __name__ == "__main__":
    simulate_real_profit()
