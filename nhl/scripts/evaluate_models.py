import sqlite3
import pandas as pd
import numpy as np
import os
from xgboost import XGBClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import log_loss, roc_auc_score, brier_score_loss

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "bot_database.db")

FEATURES = [
    'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 
    'season_g', 'season_a', 'season_pts',
    'ga_g', 'hdca_g', 'pp1', 'is_home', 
    'is_b2b', 'opp_is_b2b', 'consec_goals',
    'ixg_x_hdcf', 'sog_x_atoi', 'ixg_x_ga'
]

def load_data():
    conn = sqlite3.connect(DB_PATH)
    # 1. Load players
    df = pd.read_sql("SELECT * FROM players WHERE but IS NOT NULL AND but != ''", conn)
    
    # 2. Load odds from picks tables
    try:
        picks_but = pd.read_sql("SELECT date, joueur, cote, closing_cote FROM picks WHERE cote IS NOT NULL", conn)
        picks_but['market'] = 'but'
    except:
        picks_but = pd.DataFrame(columns=['date', 'joueur', 'cote', 'closing_cote', 'market'])

    try:
        picks_ast = pd.read_sql("SELECT date, joueur, cote, closing_cote FROM picks_assists WHERE cote IS NOT NULL", conn)
        picks_ast['market'] = 'ast'
    except:
        picks_ast = pd.DataFrame(columns=['date', 'joueur', 'cote', 'closing_cote', 'market'])

    try:
        picks_pts = pd.read_sql("SELECT date, joueur, cote, closing_cote FROM picks_points WHERE cote IS NOT NULL", conn)
        picks_pts['market'] = 'pts'
    except:
        picks_pts = pd.DataFrame(columns=['date', 'joueur', 'cote', 'closing_cote', 'market'])

    conn.close()
    
    odds_df = pd.concat([picks_but, picks_ast, picks_pts], ignore_index=True)
    odds_df['date'] = pd.to_datetime(odds_df['date']).dt.date
    
    df['date_dt'] = pd.to_datetime(df['date'])
    df = df.sort_values('date_dt').reset_index(drop=True)
    df['date_str'] = df['date_dt'].dt.date
    
    # Features preprocessing
    for col in ['ixg', 'hdcf', 'sog', 'atoi', 'season_g', 'season_a', 'season_pts', 'ga_g', 'hdca_g']:
        name = col + '_l10' if col in ['ixg', 'hdcf', 'sog', 'atoi'] else col
        df[name] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
    df['pp1'] = pd.to_numeric(df['pp1'], errors='coerce').fillna(0).astype(int)
    df['is_home'] = pd.to_numeric(df['is_home'], errors='coerce').fillna(0).astype(int)
    df['is_b2b'] = pd.to_numeric(df['b2b'], errors='coerce').fillna(0).astype(int)
    df['opp_is_b2b'] = pd.to_numeric(df.get('opp_b2b', 0), errors='coerce').fillna(0).astype(int)
    df['consec_goals'] = pd.to_numeric(df.get('consec_goals', 0), errors='coerce').fillna(0)
    
    df['ixg_x_hdcf'] = df['ixg_l10'] * df['hdcf_l10']
    df['sog_x_atoi'] = df['sog_l10'] * df['atoi_l10']
    df['ixg_x_ga'] = df['ixg_l10'] * df['ga_g']
    
    df['target_but'] = (pd.to_numeric(df['but'], errors='coerce').fillna(0) > 0).astype(int)
    df['target_ast'] = (pd.to_numeric(df['assist'], errors='coerce').fillna(0) > 0).astype(int)
    df['target_pts'] = (pd.to_numeric(df['point'], errors='coerce').fillna(0) > 0).astype(int)
    
    return df, odds_df

def evaluate_market(df, odds_df, target_col, market_name):
    print(f"\n{'='*60}\nEVALUATION MARCHE : {market_name.upper()}\n{'='*60}")
    
    X = df[FEATURES].values
    y = df[target_col].values
    
    tscv = TimeSeriesSplit(n_splits=5)
    
    # Initialisation des colonnes de prédiction OOS
    df[f'pred_xgb_{market_name}'] = np.nan
    df[f'pred_rf_{market_name}'] = np.nan
    df[f'pred_lr_{market_name}'] = np.nan
    
    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        X_train, y_train = X[train_idx], y[train_idx]
        X_test, y_test = X[test_idx], y[test_idx]
        
        # XGBoost
        scale_pos = (len(y_train) - sum(y_train)) / max(1, sum(y_train))
        xgb = XGBClassifier(
            n_estimators=100, max_depth=3, learning_rate=0.05,
            scale_pos_weight=scale_pos, eval_metric='logloss',
            random_state=42, subsample=0.8, colsample_bytree=0.8
        )
        xgb.fit(X_train, y_train)
        df.iloc[test_idx, df.columns.get_loc(f'pred_xgb_{market_name}')] = xgb.predict_proba(X_test)[:, 1]
        
        # Random Forest
        rf = RandomForestClassifier(
            n_estimators=100, max_depth=5, class_weight='balanced',
            random_state=42, n_jobs=-1
        )
        rf.fit(X_train, y_train)
        df.iloc[test_idx, df.columns.get_loc(f'pred_rf_{market_name}')] = rf.predict_proba(X_test)[:, 1]
        
        # Logistic Regression (needs scaling)
        scaler = StandardScaler()
        X_train_sc = scaler.fit_transform(X_train)
        X_test_sc = scaler.transform(X_test)
        
        lr = LogisticRegression(class_weight='balanced', max_iter=1000, random_state=42)
        lr.fit(X_train_sc, y_train)
        df.iloc[test_idx, df.columns.get_loc(f'pred_lr_{market_name}')] = lr.predict_proba(X_test_sc)[:, 1]

    # Metrics on Out-of-sample data (the nan values are the first fold which is used only for training)
    oos_mask = ~df[f'pred_xgb_{market_name}'].isna()
    df_oos = df[oos_mask].copy()
    y_oos = df_oos[target_col].values
    
    models = ['xgb', 'rf', 'lr']
    
    print("\n--- METRIQUES PURES (Toute la base OOS) ---")
    for m in models:
        preds = df_oos[f'pred_{m}_{market_name}'].values
        if sum(y_oos) > 0 and len(np.unique(y_oos)) > 1:
            auc = roc_auc_score(y_oos, preds)
            brier = brier_score_loss(y_oos, preds)
            print(f"[{m.upper()}] AUC: {auc:.3f} | Brier: {brier:.4f}")

    print("\n--- SIMULATION ROI (Sur les matchs avec cotes) ---")
    # Join with odds
    market_odds = odds_df[odds_df['market'] == market_name]
    # Drop cote from df_oos to avoid collision
    if 'cote' in df_oos.columns:
        df_oos = df_oos.drop(columns=['cote', 'closing_cote'])
        
    df_sim = df_oos.merge(market_odds, left_on=['date_str', 'joueur'], right_on=['date', 'joueur'], how='inner')
    
    if len(df_sim) == 0:
        print("-> Aucune cote disponible pour ce marché pour la simulation OOS.")
        return
        
    for m in models:
        preds = df_sim[f'pred_{m}_{market_name}']
        cotes = df_sim['cote']
        
        # EV threshold = 1.05 (5% edge)
        bets_mask = (preds * cotes) > 1.05
        bets_df = df_sim[bets_mask]
        
        n_bets = len(bets_df)
        if n_bets == 0:
            print(f"[{m.upper()}] Nombre de paris: 0")
            continue
            
        wins = bets_df[target_col].sum()
        winrate = wins / n_bets * 100
        
        # Profit en unités fixes (1 U)
        profit = (bets_df[target_col] * bets_df['cote'] - 1).sum()
        roi = profit / n_bets * 100
        
        print(f"[{m.upper():>3}] Paris: {n_bets:>3} | Win: {wins:>3} ({winrate:>5.1f}%) | Profit: {profit:>6.2f} U | ROI: {roi:>6.2f}%")

if __name__ == "__main__":
    print("Chargement des donnees...")
    df, odds_df = load_data()
    print(f"Total joueurs-matchs : {len(df)}")
    print(f"Total cotes disponibles : {len(odds_df)}")
    
    evaluate_market(df, odds_df, 'target_but', 'but')
    evaluate_market(df, odds_df, 'target_ast', 'ast')
    evaluate_market(df, odds_df, 'target_pts', 'pts')
