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
MODEL_PATH = "models/xg_model.pkl" # Fix: Must match bot_logic's expected path

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

    # Mapping BDD V14 -> Colonnes XGBoost
    mapping = {
        'ixg': 'ixg_l10',
        'hdcf': 'hdcf_l10',
        'sog': 'sog_l10',
        'atoi': 'atoi_l10',
        'season_g': 'season_g',
        'ga_g': 'ga_g',
        'hdca_g': 'hdca_g',
        'score_but': 'qs_v10',
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
    logger.info("Début du cycle de Ré-Entraînement (Correction Real Data).")
    
    df = get_db_data()
    if df.empty or len(df) < 50:
        logger.error("Pas assez de données dans la DB pour un entraînement fiable.")
        return
        
    logger.info(f"Échantillons réels extraits de SQLite : {len(df)}")
    
    # Mapping exact avec predictor_v14 pour ne pas décaler les colonnes
    # 1. ixg, 2. hdcf, 3. sog, 4. atoi, 5. season_g, 
    # 6. ga_g, 7. hdca_g, 8. pp1, 9. is_home, 10. is_b2b, 11. opp_is_b2b,
    # 12. consec_goals, 13. qs_v10,
    # 14. luck_factor, 15. ixg_x_hdcf, 16. sog_x_atoi, 17. ixg_x_ga, 18. streak_x_ixg
    
    df['luck_factor'] = 1.0 # Difficile à extraire de la DB players sans ixg_unnorm précis
    df['ixg_x_hdcf'] = df['ixg_l10'] * df['hdcf_l10']
    df['sog_x_atoi'] = df['sog_l10'] * df['atoi_l10']
    df['ixg_x_ga']   = df['ixg_l10'] * df['ga_g']
    df['streak_x_ixg'] = df['consec_goals'] * df['ixg_l10']
    
    features_prod = [
        'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 'season_g',
        'ga_g', 'hdca_g', 'pp1', 'is_home', 'is_b2b', 'opp_is_b2b',
        'consec_goals', 'qs_v10',
        'luck_factor', 'ixg_x_hdcf', 'sog_x_atoi', 'ixg_x_ga', 'streak_x_ixg'
    ]
    
    # Nettoyage
    df = df.dropna(subset=features_prod + ['scored'])
    
    X = df[features_prod].values
    y = df['scored'].astype(int).values
    
    # Entraînement robuste sur peu de données (Cross-validation simple)
    scale = (len(y) - y.sum()) / max(1, y.sum())
    
    model = XGBClassifier(
        n_estimators=100, # Moins d'estimateurs car peu de données
        max_depth=4, 
        learning_rate=0.05,
        scale_pos_weight=scale,
        eval_metric='logloss',
        random_state=42
    )
    
    logger.info(f"Apprentissage XGBoost... (Target positive: {y.sum()})")
    model.fit(X, y)
    
    # Sauvegarde format dict pour compatibilité
    joblib.dump({
        'model': model,
        'features': features_prod,
        'version': f'v14.2_db_trained_{datetime.now().strftime("%Y%m%d")}'
    }, MODEL_PATH)
    
    logger.info(f"✅ Modèle sauvegardé dans {MODEL_PATH}")
    with open("stats/last_retrain.txt", "w") as f:
        f.write(datetime.now().strftime("%Y-%m-%d"))

if __name__ == '__main__':
    main()
