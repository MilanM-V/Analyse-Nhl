import sqlite3
import pandas as pd
import numpy as np
import os
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier
from itertools import combinations
import warnings
warnings.filterwarnings('ignore')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "bot_database.db")

def get_data(cat='but'):
    conn = sqlite3.connect(DB_PATH)
    table_map = {'but': 'picks', 'ast': 'picks_assists'}
    target_map = {'but': 'but', 'ast': 'assist'}
    
    table = table_map[cat]
    target_col = target_map[cat]
    
    q = f"""
        SELECT p.date, p.cote, p.{target_col} as result, 
               pl.ixg, pl.hdcf, pl.sog, pl.atoi, pl.season_g, pl.season_a, pl.season_pts,
               pl.ga_g, pl.hdca_g, pl.pp1, pl.is_home, pl.b2b, pl.opp_b2b, pl.consec_goals
        FROM {table} p
        JOIN players pl ON p.date = pl.date AND p.joueur = pl.joueur
        WHERE p.cote IS NOT NULL AND p.cote > 1.05
    """
    df = pd.read_sql(q, conn)
    conn.close()
    
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        for col in ['ixg', 'hdcf', 'sog', 'atoi', 'season_g', 'season_a', 'season_pts', 'ga_g', 'hdca_g', 'pp1', 'is_home', 'b2b', 'opp_b2b', 'consec_goals']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
        df['target'] = (pd.to_numeric(df['result'], errors='coerce').fillna(0) > 0).astype(int)
        
        df['ixg_x_hdcf'] = df['ixg'] * df['hdcf']
        df['sog_x_atoi'] = df['sog'] * df['atoi']
        df['ixg_x_ga'] = df['ixg'] * df['ga_g']
        
    return df

ALL_FEATURES = [
    'ixg', 'hdcf', 'sog', 'atoi', 'season_g', 'season_a', 'season_pts',
    'ga_g', 'hdca_g', 'pp1', 'is_home', 'b2b', 'opp_b2b', 'consec_goals',
    'ixg_x_hdcf', 'sog_x_atoi', 'ixg_x_ga'
]

def evaluate_model(X, y, cotes, tscv, model, threshold=0.05):
    preds = np.zeros(len(y))
    for train_idx, test_idx in tscv.split(X):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        model.fit(X_train, y_train)
        preds[test_idx] = model.predict_proba(X_test)[:, 1]
    
    # Eval from split 1 onwards
    mask = preds > 0
    
    if not np.any(mask): return 0.0, 0.0, 0, 0
    
    auc = roc_auc_score(y[mask], preds[mask])
    
    evs = (preds[mask] * cotes[mask]) - 1.0
    
    y_test_f = y[mask]
    cotes_test_f = cotes[mask]
    
    play_mask = evs > threshold
    if not np.any(play_mask): return auc, 0.0, 0, 0
    
    y_play = y_test_f[play_mask]
    c_play = cotes_test_f[play_mask]
    
    # Flat betting 1 unit
    gains = np.sum(np.where(y_play == 1, c_play - 1.0, -1.0))
    mises = len(y_play)
    roi = (gains / mises) * 100 if mises > 0 else 0.0
    
    return auc, roi, mises, gains

def grid_search_thresholds():
    print("\n" + "="*60)
    print(" RECHERCHE DE SEUIL EV OPTIMAL (Buteurs)")
    print("="*60)
    df = get_data('but')
    y = df['target'].values
    X = df[ALL_FEATURES].values
    cotes = df['cote'].values
    tscv = TimeSeriesSplit(n_splits=4)
    
    scale = (len(y) - sum(y)) / max(1, sum(y))
    model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.05, scale_pos_weight=scale, eval_metric='logloss', random_state=42)
    
    preds = np.zeros(len(y))
    for train_idx, test_idx in tscv.split(X):
        model.fit(X[train_idx], y[train_idx])
        preds[test_idx] = model.predict_proba(X[test_idx])[:, 1]
        
    mask = preds > 0
    y_test = y[mask]
    c_test = cotes[mask]
    evs = (preds[mask] * c_test) - 1.0
    
    best_roi = -999
    best_th = 0
    print(f"{'SEUIL EV':<10} | {'VOLUME':<8} | {'PROFIT':<8} | {'ROI':<8}")
    print("-" * 45)
    for th in [0.01, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15]:
        play_mask = evs > th
        mises = np.sum(play_mask)
        if mises < 10: continue
        gains = np.sum(np.where(y_test[play_mask] == 1, c_test[play_mask] - 1.0, -1.0))
        roi = (gains / mises) * 100
        print(f"> {th*100:04.1f}%     | {mises:<8} | {gains:>+6.2f} U | {roi:>+6.2f}%")
        if roi > best_roi and mises > 20: # need minimum volume
            best_roi = roi
            best_th = th
            
    print(f"\n=> MEILLEUR SEUIL EV: {best_th*100:.1f}% avec {best_roi:+.2f}% ROI")

def backward_ablation():
    print("\n" + "="*60)
    print(" ETUDE D'ABLATION (Backward Selection) - Buteurs")
    print("="*60)
    df = get_data('but')
    y = df['target'].values
    cotes = df['cote'].values
    tscv = TimeSeriesSplit(n_splits=4)
    scale = (len(y) - sum(y)) / max(1, sum(y))
    model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.05, scale_pos_weight=scale, eval_metric='logloss', random_state=42)
    
    # Base
    X_base = df[ALL_FEATURES].values
    auc_base, roi_base, vol_base, _ = evaluate_model(X_base, y, cotes, tscv, model, threshold=0.05)
    print(f"BASELINE (Toutes features) -> ROI: {roi_base:+.2f}% | AUC: {auc_base:.4f}")
    
    best_roi = roi_base
    toxic_feature = None
    
    for feat in ALL_FEATURES:
        feats_to_keep = [f for f in ALL_FEATURES if f != feat]
        X = df[feats_to_keep].values
        auc, roi, vol, _ = evaluate_model(X, y, cotes, tscv, model, threshold=0.05)
        
        indicator = "+++" if roi > roi_base + 5 else ("++" if roi > roi_base else "--")
        print(f"Sans '{feat:<15}' -> ROI: {roi:>+6.2f}% | {indicator} | Vol: {vol}")
        
        if roi > best_roi:
            best_roi = roi
            toxic_feature = feat
            
    if toxic_feature:
        print(f"\n=> VARIABLE TOXIQUE IDENTIFIEE : {toxic_feature}")
        print(f"La retirer fait monter le ROI de {roi_base:+.2f}% a {best_roi:+.2f}%")
    else:
        print("\n=> AUCUNE VARIABLE TOXIQUE. Le modele actuel est parfait.")

if __name__ == "__main__":
    grid_search_thresholds()
    backward_ablation()
