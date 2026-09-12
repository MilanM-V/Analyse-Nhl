import sqlite3
import pandas as pd
import numpy as np
import os
from sklearn.model_selection import TimeSeriesSplit, cross_val_predict
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier
import warnings
warnings.filterwarnings('ignore')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "bot_database.db")

def get_real_picks(cat):
    conn = sqlite3.connect(DB_PATH)
    table_map = {'but': 'picks', 'ast': 'picks_assists', 'pts': 'picks_points'}
    target_map = {'but': 'but', 'ast': 'assist', 'pts': 'point'}
    
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
    try:
        df = pd.read_sql(q, conn)
    except Exception as e:
        print(f"Erreur SQL : {e}")
        df = pd.DataFrame()
    conn.close()
    
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        # Parse numeric
        for col in ['ixg', 'hdcf', 'sog', 'atoi', 'season_g', 'season_a', 'season_pts', 'ga_g', 'hdca_g', 'pp1', 'is_home', 'b2b', 'opp_b2b', 'consec_goals', 'pk_pct', 'cf_pct', 'pdo']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
        df['target'] = (pd.to_numeric(df['result'], errors='coerce').fillna(0) > 0).astype(int)
        
        # Base Features
        df['ixg_x_hdcf'] = df['ixg'] * df['hdcf']
        df['sog_x_atoi'] = df['sog'] * df['atoi']
        df['ixg_x_ga'] = df['ixg'] * df['ga_g']
        
        # Extended Features
        df['pp1_x_pk'] = df['pp1'] * df['pk_pct']
        df['cf_pct_adj'] = df['cf_pct'] - 50.0  # Center around 50%
        df['pdo_adj'] = df['pdo'] - 100.0  # Center around 100
        
    return df

BASE_FEATURES = [
    'ixg', 'hdcf', 'sog', 'atoi', 'season_g', 'season_a', 'season_pts',
    'ga_g', 'hdca_g', 'pp1', 'is_home', 'b2b', 'opp_b2b', 'consec_goals',
    'ixg_x_hdcf', 'sog_x_atoi', 'ixg_x_ga'
]

EXT_FEATURES = BASE_FEATURES + ['pk_pct', 'cf_pct_adj', 'pdo_adj', 'pp1_x_pk']

def calculate_kelly(proba, cote, fraction=0.125, max_bet=2.0):
    b = cote - 1.0
    f = (proba * b - (1 - proba)) / b
    if f <= 0: return 0.0
    return min(f * fraction * 100, max_bet)

def test_feature_engineering():
    print("\n" + "="*60)
    print(" TEST 1: FEATURE ENGINEERING (Nouvelles variables PK, CF, PDO)")
    print("="*60)
    
    df_ast = get_real_picks('ast')
    
    print(f"Dataset Passeurs : {len(df_ast)} paris historiques.")
    
    y = df_ast['target'].values
    tscv = TimeSeriesSplit(n_splits=3)
    
    def manual_cv_predict(X, y):
        preds = np.zeros(len(y))
        lr = LogisticRegression(class_weight='balanced')
        for train_idx, test_idx in tscv.split(X):
            lr.fit(X[train_idx], y[train_idx])
            preds[test_idx] = lr.predict_proba(X[test_idx])[:, 1]
        
        # We only evaluate on the predicted indices (from the 3 splits, meaning everything after the first train split)
        test_indices = []
        for _, test_idx in tscv.split(X):
            test_indices.extend(test_idx)
        return preds[test_indices], y[test_indices]
    
    # Baseline (Logistic Regression)
    print("\n-> Modele Baseline (Logistic Regression) sur Base Features")
    X_base = StandardScaler().fit_transform(df_ast[BASE_FEATURES].values)
    preds_base, y_eval_base = manual_cv_predict(X_base, y)
    
    auc_base = roc_auc_score(y_eval_base, preds_base)
    brier_base = brier_score_loss(y_eval_base, preds_base)
    print(f"   AUC: {auc_base:.4f} | Brier Score: {brier_base:.4f}")
    
    # Extended
    print("\n-> Modele Etendu (Logistic Regression) sur Extended Features")
    X_ext = StandardScaler().fit_transform(df_ast[EXT_FEATURES].values)
    preds_ext, y_eval_ext = manual_cv_predict(X_ext, y)
    
    auc_ext = roc_auc_score(y_eval_ext, preds_ext)
    brier_ext = brier_score_loss(y_eval_ext, preds_ext)
    print(f"   AUC: {auc_ext:.4f} | Brier Score: {brier_ext:.4f}")
    
    if auc_ext > auc_base and brier_ext < brier_base:
        print("   [+] CONCLUSION: Les nouvelles variables AMELIORENT la prediction des Passeurs.")
    else:
        print("   [-] CONCLUSION: Les nouvelles variables apportent du BRUIT (Overfitting) sur ce modele.")

def test_algorithms():
    print("\n" + "="*60)
    print(" TEST 2: NOUVEAUX ALGORITHMES (Buteurs)")
    print("="*60)
    
    df_but = get_real_picks('but')
    y = df_but['target'].values
    X = df_but[EXT_FEATURES].values
    cotes = df_but['cote'].values
    
    print(f"Dataset Buteurs : {len(df_but)} paris historiques.")
    
    tscv = TimeSeriesSplit(n_splits=4)
    
    final_scale = (len(y) - sum(y)) / max(1, sum(y))
    models = {
        'XGBoost (Baseline)': XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.05, scale_pos_weight=final_scale, eval_metric='logloss', random_state=42),
        'LightGBM (HistGradient)': HistGradientBoostingClassifier(learning_rate=0.05, max_depth=3, max_iter=100, class_weight='balanced', random_state=42)
    }
    
    for name, model in models.items():
        print(f"\n-> Test Algo : {name}")
        preds = np.zeros(len(y))
        
        for train_idx, test_idx in tscv.split(X):
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]
            model.fit(X_train, y_train)
            preds[test_idx] = model.predict_proba(X_test)[:, 1]
            
        # Simuler le ROI
        test_mask = preds > 0
        df_test = df_but.iloc[test_mask].copy()
        df_test['proba'] = preds[test_mask]
        df_test['ev'] = (df_test['proba'] * df_test['cote']) - 1.0
        
        gains = 0
        mises = 0
        for _, row in df_test.iterrows():
            if row['ev'] > 0.05:
                mise = calculate_kelly(row['proba'], row['cote'])
                if mise > 0:
                    mises += mise
                    if row['target'] == 1:
                        gains += (row['cote'] * mise - mise)
                    else:
                        gains -= mise
                        
        roi = (gains / mises * 100) if mises > 0 else 0
        print(f"   Paris joues (EV>5%): {len(df_test[df_test['ev'] > 0.05])}")
        print(f"   ROI: {roi:+.2f}% | Profit: {gains:+.2f} U")

def test_synergistic_combos():
    print("\n" + "="*60)
    print(" TEST 3: COMBINES SYNERGIQUES VS ALEATOIRES (Passeurs)")
    print("="*60)
    
    df_ast = get_real_picks('ast')
    
    # On va simuler que le modele avait raison sur certaines probas
    X = StandardScaler().fit_transform(df_ast[EXT_FEATURES].values)
    y = df_ast['target'].values
    
    tscv = TimeSeriesSplit(n_splits=3)
    preds = np.zeros(len(y))
    lr = LogisticRegression(class_weight='balanced')
    for train_idx, test_idx in tscv.split(X):
        lr.fit(X[train_idx], y[train_idx])
        preds[test_idx] = lr.predict_proba(X[test_idx])[:, 1]
        
    df_ast['proba'] = preds
    # We drop the training samples that were never predicted in test
    df_ast = df_ast[df_ast['proba'] > 0].copy()
    
    df_ast['ev'] = (df_ast['proba'] * df_ast['cote']) - 1.0
    
    df_play = df_ast[df_ast['ev'] > 0.05].copy()
    print(f"Base de {len(df_play)} paris 'value' (EV > 5%) sur les Passeurs.")
    
    # Random Combos
    random_mises, random_gains, random_won, random_tot = 0, 0, 0, 0
    syn_mises, syn_gains, syn_won, syn_tot = 0, 0, 0, 0
    
    for date, group in df_play.groupby('date'):
        picks = group.to_dict('records')
        
        # 1. Random Combos (shuffle)
        np.random.seed(42)
        random_picks = picks.copy()
        np.random.shuffle(random_picks)
        for i in range(0, len(random_picks)-1, 2):
            p1, p2 = random_picks[i], random_picks[i+1]
            if p1['equipe'] != p2['equipe']: # Assurance que c'est aleatoire (equipes diff)
                random_mises += 1
                random_tot += 1
                if p1['target'] == 1 and p2['target'] == 1:
                    random_gains += (p1['cote'] * p2['cote'] - 1)
                    random_won += 1
                else:
                    random_gains -= 1
                    
        # 2. Synergistic Combos (same team)
        # On groupe par equipe
        teams = set([p['equipe'] for p in picks])
        for t in teams:
            t_picks = [p for p in picks if p['equipe'] == t]
            for i in range(0, len(t_picks)-1, 2):
                p1, p2 = t_picks[i], t_picks[i+1]
                if p1['joueur'] != p2['joueur']:
                    syn_mises += 1
                    syn_tot += 1
                    if p1['target'] == 1 and p2['target'] == 1:
                        syn_gains += (p1['cote'] * p2['cote'] - 1)
                        syn_won += 1
                    else:
                        syn_gains -= 1
                        
    r_roi = (random_gains/random_mises)*100 if random_mises>0 else 0
    s_roi = (syn_gains/syn_mises)*100 if syn_mises>0 else 0
    
    print("\n-> Combines Aleatoires (Joueurs d'equipes differentes):")
    print(f"   Volume: {random_tot} combines | Winrate: {(random_won/max(1,random_tot))*100:.1f}%")
    print(f"   ROI: {r_roi:+.2f}%")
    
    print("\n-> Combines Synergiques (Joueurs de la MEME equipe):")
    print(f"   Volume: {syn_tot} combines | Winrate: {(syn_won/max(1,syn_tot))*100:.1f}%")
    print(f"   ROI: {s_roi:+.2f}%")

if __name__ == "__main__":
    test_feature_engineering()
    test_algorithms()
    test_synergistic_combos()
