import sqlite3
import pandas as pd
import numpy as np
import os
from sklearn.model_selection import TimeSeriesSplit
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, roc_auc_score
from xgboost import XGBClassifier
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)
sys.path.append(os.path.dirname(ROOT))
from shared.kelly import calculate_quarter_kelly

DB_PATH = os.path.join(ROOT, "bot_database.db")

def get_data(cat):
    conn = sqlite3.connect(DB_PATH)
    table = 'picks' if cat == 'but' else 'picks_assists'
    target = 'but' if cat == 'but' else 'assist'
    q = f"""
        SELECT p.date, p.cote, p.{target} as result, 
               pl.ixg, pl.hdcf, pl.sog, pl.atoi, pl.season_g, pl.season_a, pl.season_pts,
               pl.ga_g, pl.hdca_g, pl.pp1, pl.is_home, pl.b2b, pl.opp_b2b, pl.consec_goals
        FROM {table} p
        JOIN players pl ON p.date = pl.date AND p.joueur = pl.joueur
        WHERE p.cote > 1.05
    """
    df = pd.read_sql(q, conn)
    conn.close()
    if df.empty: return df
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df['target'] = (pd.to_numeric(df['result'], errors='coerce').fillna(0) > 0).astype(int)
    for col in ['ixg', 'hdcf', 'sog', 'atoi', 'season_g', 'season_a', 'season_pts', 'ga_g', 'hdca_g', 'pp1', 'is_home', 'b2b', 'opp_b2b', 'consec_goals']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    df['ixg_x_hdcf'] = df['ixg'] * df['hdcf']
    df['sog_x_atoi'] = df['sog'] * df['atoi']
    df['ixg_x_ga'] = df['ixg'] * df['ga_g']
    return df

features_but = [
    'ixg', 'hdcf', 'sog', 'atoi', 'season_g', 'season_pts', # sans season_a
    'ga_g', 'hdca_g', 'pp1', 'is_home', 'b2b', 'opp_b2b', 'consec_goals',
    'ixg_x_hdcf', 'sog_x_atoi', 'ixg_x_ga'
]
features_ast = features_but + ['season_a']

def test_model(cat, name, model, calibrate=False, kelly_fraction=8.0):
    df = get_data(cat)
    feats = features_but if cat == 'but' else features_ast
    X = df[feats].values
    y = df['target'].values
    cotes = df['cote'].values
    
    tscv = TimeSeriesSplit(n_splits=4)
    preds = np.zeros(len(y))
    
    if calibrate:
        model = CalibratedClassifierCV(model, method='isotonic', cv=3)
        
    for train_idx, test_idx in tscv.split(X):
        model.fit(X[train_idx], y[train_idx])
        preds[test_idx] = model.predict_proba(X[test_idx])[:, 1]
        
    mask = preds > 0
    df_sim = df[mask].copy()
    df_sim['proba'] = preds[mask]
    df_sim['ev'] = (df_sim['proba'] * df_sim['cote']) - 1.0
    
    # Grid search sur EV Threshold et fraction de Kelly
    print(f"\n--- {cat.upper()} | {name} | Calibrated: {calibrate} ---")
    best_roi, best_th, best_gains = -999, 0, 0
    for th in [0.0, 0.02, 0.05, 0.08, 0.1]:
        play_mask = df_sim['ev'] > th
        df_play = df_sim[play_mask].copy()
        
        gains, mises, won = 0.0, 0.0, 0
        for _, row in df_play.iterrows():
            b = row['cote'] - 1.0
            p = row['proba']
            q = 1.0 - p
            f = (p * b - q) / b
            if f > 0:
                units = max(0.5, min(f / kelly_fraction * 100, 2.0))
                mises += units
                if row['target'] == 1:
                    gains += (row['cote'] * units - units)
                    won += 1
                else:
                    gains -= units
                    
        roi = (gains / mises * 100) if mises > 0 else 0
        paris = len(df_play)
        print(f"EV>{th*100:.0f}% -> Paris:{paris} | ROI:{roi:+.1f}% | Profit:{gains:+.2f}U")
        if roi > best_roi and paris >= 10:
            best_roi = roi
            best_th = th
            best_gains = gains

if __name__ == "__main__":
    print("Recherche d'optimisations de rentabilité...")
    # Buteurs
    scale_but = 4.0 # approximatif
    xgb_but = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.05, scale_pos_weight=scale_but, eval_metric='logloss')
    test_model('but', 'XGBoost', xgb_but, calibrate=False, kelly_fraction=8.0)
    test_model('but', 'XGBoost', xgb_but, calibrate=True, kelly_fraction=8.0) # Calibré
    test_model('but', 'XGBoost', xgb_but, calibrate=True, kelly_fraction=16.0) # Ultra-conservateur Kelly
    
    # Passeurs
    scale_ast = 4.0
    xgb_ast = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.05, scale_pos_weight=scale_ast, eval_metric='logloss')
    test_model('ast', 'XGBoost (Remplacement LogReg)', xgb_ast, calibrate=False, kelly_fraction=8.0)
    test_model('ast', 'XGBoost', xgb_ast, calibrate=True, kelly_fraction=8.0)
