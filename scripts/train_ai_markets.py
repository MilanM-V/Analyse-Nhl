
import sqlite3
import pandas as pd
import numpy as np
import joblib
from xgboost import XGBClassifier
import os
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("AI_Trainer")

DB_PATH = "bot_database.db"
MODELS_DIR = "models"

if not os.path.exists(MODELS_DIR):
    os.makedirs(MODELS_DIR)

def get_training_data(target_col):
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
        
    conn = sqlite3.connect(DB_PATH)
    # On prend toutes les données où le résultat cible est renseigné
    query = f"SELECT * FROM players WHERE {target_col} IS NOT NULL AND {target_col} != ''"
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    if df.empty:
        return pd.DataFrame()

    # Features de base
    mapping = {
        'ixg': 'ixg_l10', 'hdcf': 'hdcf_l10', 'sog': 'sog_l10', 'atoi': 'atoi_l10',
        'season_g': 'season_g', 'ga_g': 'ga_g', 'hdca_g': 'hdca_g', 'consec_goals': 'consec_goals'
    }
    df = df.rename(columns=mapping)
    
    # Conversions types
    for col in ['pp1', 'is_home', 'b2b', 'opp_b2b', target_col]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
            
    df['is_b2b'] = df['b2b']
    df['opp_is_b2b'] = df.get('opp_b2b', 0)
    df['target'] = df[target_col].apply(lambda x: 1 if x > 0 else 0)
    
    # Ajout des features d'interaction
    df['luck_factor'] = 1.0 
    df['ixg_x_hdcf'] = df['ixg_l10'] * df['hdcf_l10']
    df['sog_x_atoi'] = df['sog_l10'] * df['atoi_l10']
    df['ixg_x_ga']   = df['ixg_l10'] * df['ga_g']
    df['streak_x_ixg'] = df['consec_goals'] * df['ixg_l10']
    
    # Note: On utilise le score_but comme feature de base même pour assist/point 
    # car c'est un bon indicateur de la qualité globale du joueur.
    df['qs_v10'] = df['score_but'] 

    features = [
        'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 'season_g',
        'ga_g', 'hdca_g', 'pp1', 'is_home', 'is_b2b', 'opp_is_b2b',
        'consec_goals', 'qs_v10',
        'luck_factor', 'ixg_x_hdcf', 'sog_x_atoi', 'ixg_x_ga', 'streak_x_ixg'
    ]
    
    return df[features + ['target']].dropna().copy(), features

def train_model(target_name, target_col, filename):
    logger.info(f"Entraînement du modèle : {target_name}...")
    df, features = get_training_data(target_col)
    
    if len(df) < 50:
        logger.warning(f"Pas assez de données pour {target_name} ({len(df)})")
        return False

    X = df[features].values
    y = df['target'].values
    
    scale = (len(y) - y.sum()) / max(1, y.sum())
    
    model = XGBClassifier(
        n_estimators=150, max_depth=4, learning_rate=0.04,
        scale_pos_weight=scale, eval_metric='logloss', random_state=42
    )
    
    model.fit(X, y)
    
    path = os.path.join(MODELS_DIR, filename)
    joblib.dump({
        'model': model,
        'features': features,
        'version': f'v14.3_{target_name}_{datetime.now().strftime("%Y%m%d")}'
    }, path)
    
    logger.info(f"✅ Modèle {target_name} sauvegardé ({len(df)} lignes, target positive: {y.sum()})")
    return True

def main():
    success = True
    success &= train_model("BUTS", "but", "xg_model_but.pkl")
    success &= train_model("ASSISTS", "assist", "xg_model_assist.pkl")
    success &= train_model("POINTS", "point", "xg_model_point.pkl")
    
    if success:
        logger.info("FÉLICITATIONS : Les 3 modèles IA sont prêts.")

if __name__ == '__main__':
    main()
