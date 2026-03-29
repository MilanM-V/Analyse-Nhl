import sqlite3
import pandas as pd
import numpy as np
import joblib
from xgboost import XGBClassifier
import os
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("Retrainer")

DB_PATH = "bot_database.db"
BACKTEST_PATH = "backtests/backtest_v4_features.csv"
MODEL_PATH = "models/prod_model_v5.pkl"

def get_db_data():
    if not os.path.exists(DB_PATH):
        logger.info("Base de données SQLite introuvable. Aucun ré-entrainement possible.")
        return pd.DataFrame()
        
    conn = sqlite3.connect(DB_PATH)
    # On prend tous les joueurs evalués dont on a le résultat du match
    df_db = pd.read_sql_query("SELECT * FROM players WHERE but IS NOT NULL AND but != ''", conn)
    conn.close()
    
    if df_db.empty:
        return pd.DataFrame()

    # Mapping BDD -> Colonnes XGBoost
    mapping = {
        'ixg': 'ixg_l10',
        'hdcf': 'hdcf_l10',
        'sog': 'sog_l10',
        'atoi': 'atoi_l10',
        'season_g': 'season_g',
        'ga_g': 'ga_g',
        'hdca_g': 'hdca_g',
        'score': 'qs_v10',
        'consec_goals': 'consec_goals'
    }
    df_db = df_db.rename(columns=mapping)
    
    # Conversions
    for col in ['pp1', 'is_home', 'b2b', 'opp_b2b', 'but']:
        if col in df_db.columns:
            df_db[col] = pd.to_numeric(df_db[col], errors='coerce').fillna(0).astype(int)
            
    df_db['is_b2b'] = df_db['b2b']
    if 'opp_b2b' in df_db.columns:
        df_db['opp_is_b2b'] = df_db['opp_b2b']
    else:
        df_db['opp_is_b2b'] = 0
            
    df_db['scored'] = df_db['but']
    
    features = [
        'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 'season_g',
        'ga_g', 'hdca_g', 'pp1', 'is_home', 'is_b2b', 'opp_is_b2b',
        'consec_goals', 'qs_v10', 'scored'
    ]
    
    # Remplir les colonnes manquantes avec 0 par sécurité et filtrer
    for f in features:
        if f not in df_db.columns:
            df_db[f] = 0
            
    return df_db[features].copy()

def main():
    logger.info("Début du cycle de Ré-Entraînement Hebdomadaire (Dimanche).")
    
    df_real = get_db_data()
    n_real = len(df_real)
    logger.info(f"Échantillons réels extraits de SQLite : {n_real}")
    
    if not os.path.exists(BACKTEST_PATH):
        logger.error(f"Fichier historique INTROUVABLE: {BACKTEST_PATH}")
        return
        
    df_history = pd.read_csv(BACKTEST_PATH)
    logger.info(f"Échantillons historiques extraits : {len(df_history)}")
    
    # Fusion des données réelles et historiques
    if not df_real.empty:
        df = pd.concat([df_history, df_real], ignore_index=True)
        logger.info("Fusion réussie des Datas d'Entraînement.")
    else:
        df = df_history
        logger.info("Pas de nouvelles données réelles. Entraînement sur l'historique pur.")
        
    # Création des features dérivées de production
    df['luck_factor'] = df['l10_goals'] / np.maximum(df['ixg_l10'], 0.01) if 'l10_goals' in df.columns else 1.0
    df['ixg_x_hdcf'] = df['ixg_l10'] * df['hdcf_l10']
    df['sog_x_atoi'] = df['sog_l10'] * df['atoi_l10']
    df['ixg_x_ga'] = df['ixg_l10'] * df['ga_g']
    df['streak_x_ixg'] = df['consec_goals'] * df['ixg_l10']
    
    features_prod = [
        'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 'season_g',
        'ga_g', 'hdca_g', 'pp1', 'is_home', 'is_b2b', 'opp_is_b2b',
        'consec_goals', 'qs_v10',
        'luck_factor', 'ixg_x_hdcf', 'sog_x_atoi', 'ixg_x_ga', 'streak_x_ixg'
    ]
    
    # Nettoyage Pandas
    df = df.dropna(subset=features_prod + ['scored'])
    
    X = df[features_prod].values
    y = df['scored'].astype(int).values
    
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    
    scale = (len(y_train) - y_train.sum()) / max(1, y_train.sum())
    
    model = XGBClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.03,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        scale_pos_weight=scale, eval_metric='logloss', random_state=42
    )
    
    logger.info("Apprentissage XGBoost en cours (V5 Hybride)...")
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
    
    # Benchmark Rapide
    test_df = df.iloc[split_idx:].copy()
    test_df['proba'] = model.predict_proba(X_test)[:, 1]
    
    v10_safe = test_df[test_df['qs_v10'] >= 10.5]
    if len(v10_safe) > 0:
        wr_base = v10_safe['scored'].mean() * 100
        v10_xgb = v10_safe[test_df['proba'] >= 0.55]
        wr_xgb = v10_xgb['scored'].mean() * 100 if len(v10_xgb) > 0 else 0
        
        diff = wr_xgb - wr_base
        logger.info(f"Analyse: WR Base={wr_base:.1f}% | WR XGBoost={wr_xgb:.1f}% | Delta={diff:+.1f}%")
        
        if diff >= 0:
            logger.info("Modèle validé. Sauvegarde en cours...")
            joblib.dump({
                'model': model,
                'features': features_prod,
                'version': 'v5_prod_retrained'
            }, MODEL_PATH)
            
            # Enregistrer la date du dernier retrain
            with open("stats/last_retrain.txt", "w") as f:
                f.write(datetime.now().strftime("%Y-%m-%d"))
                
            logger.info(f"✅ Fichier {MODEL_PATH} écrasé avec les nouveaux poids.")
        else:
            logger.warning("❌ Le nouveau modèle dégrade les performances. Refus de remplacement.")
    else:
        logger.warning("Pas assez d'échantillons de test.")

if __name__ == '__main__':
    main()
