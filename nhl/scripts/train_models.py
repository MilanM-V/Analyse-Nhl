import sqlite3
import pandas as pd
import numpy as np
import os
import joblib
from xgboost import XGBClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import log_loss, roc_auc_score, brier_score_loss

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "bot_database.db")
MODELS_DIR = os.path.join(ROOT, "models")

os.makedirs(MODELS_DIR, exist_ok=True)

# Features propres sans fuite de données
FEATURES_BASE = [
    'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 
    'season_g', 'season_a', 'season_pts',
    'ga_g', 'hdca_g', 'pp1', 'is_home', 
    'is_b2b', 'opp_is_b2b', 'consec_goals',
    'ixg_x_hdcf', 'sog_x_atoi', 'ixg_x_ga'
]
FEATURES_BUT = [f for f in FEATURES_BASE if f != 'season_a']
FEATURES_AST = FEATURES_BASE

def load_clean_data():
    conn = sqlite3.connect(DB_PATH)
    # On charge les joueurs où on a au moins une cible définie
    df = pd.read_sql("SELECT * FROM players WHERE but IS NOT NULL AND but != ''", conn)
    conn.close()
    
    # Tri temporel OBLIGATOIRE pour TimeSeriesSplit
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    
    # Préparation des features
    df['ixg_l10'] = pd.to_numeric(df['ixg'], errors='coerce').fillna(0)
    df['hdcf_l10'] = pd.to_numeric(df['hdcf'], errors='coerce').fillna(0)
    df['sog_l10'] = pd.to_numeric(df['sog'], errors='coerce').fillna(0)
    df['atoi_l10'] = pd.to_numeric(df['atoi'], errors='coerce').fillna(0)
    
    df['season_g'] = pd.to_numeric(df['season_g'], errors='coerce').fillna(0)
    df['season_a'] = pd.to_numeric(df['season_a'], errors='coerce').fillna(0)
    df['season_pts'] = pd.to_numeric(df['season_pts'], errors='coerce').fillna(0)
    
    df['ga_g'] = pd.to_numeric(df['ga_g'], errors='coerce').fillna(0)
    df['hdca_g'] = pd.to_numeric(df['hdca_g'], errors='coerce').fillna(0)
    
    df['pp1'] = pd.to_numeric(df['pp1'], errors='coerce').fillna(0).astype(int)
    df['is_home'] = pd.to_numeric(df['is_home'], errors='coerce').fillna(0).astype(int)
    df['is_b2b'] = pd.to_numeric(df['b2b'], errors='coerce').fillna(0).astype(int)
    df['opp_is_b2b'] = pd.to_numeric(df.get('opp_b2b', 0), errors='coerce').fillna(0).astype(int)
    df['consec_goals'] = pd.to_numeric(df.get('consec_goals', 0), errors='coerce').fillna(0)
    
    # Feature Engineering (Interactions simples)
    df['ixg_x_hdcf'] = df['ixg_l10'] * df['hdcf_l10']
    df['sog_x_atoi'] = df['sog_l10'] * df['atoi_l10']
    df['ixg_x_ga'] = df['ixg_l10'] * df['ga_g']
    
    # Targets binaires
    df['target_but'] = (pd.to_numeric(df['but'], errors='coerce').fillna(0) > 0).astype(int)
    df['target_ast'] = (pd.to_numeric(df['assist'], errors='coerce').fillna(0) > 0).astype(int)
    
    return df

def train_xgboost_buteurs(df):
    print(f"\n{'='*50}\nENTRAINEMENT : BUTEURS (XGBoost)\n{'='*50}")
    
    X = df[FEATURES_BUT].values
    y = df['target_but'].values
    
    final_scale = 4.0 # Bridé pour optimiser le Kelly
    final_model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.05, 
                              scale_pos_weight=final_scale, eval_metric='logloss', random_state=42)
    final_model.fit(X, y)
    
    path = os.path.join(MODELS_DIR, 'ml_model_but.pkl')
    joblib.dump({'model': final_model, 'features': FEATURES_BUT, 'algo': 'xgboost'}, path)
    print(f"OK Modele XGBoost sauvegarde dans {path}")
    
def train_xgboost_passeurs(df):
    print(f"\n{'='*50}\nENTRAINEMENT : PASSEURS (XGBoost)\n{'='*50}")
    
    X = df[FEATURES_AST].values
    y = df['target_ast'].values
    
    final_scale = 4.0 # Bridé pour optimiser le Kelly
    final_model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.05, 
                              scale_pos_weight=final_scale, eval_metric='logloss', random_state=42)
    final_model.fit(X, y)
    
    path = os.path.join(MODELS_DIR, 'ml_model_ast.pkl')
    joblib.dump({'model': final_model, 'features': FEATURES_AST, 'algo': 'xgboost'}, path)
    print(f"OK Modele XGBoost sauvegarde dans {path}")

if __name__ == "__main__":
    print("Chargement des données...")
    df = load_clean_data()
    print(f"{len(df)} échantillons chargés avec chronologie respectée.")
    
    train_xgboost_buteurs(df)
    train_xgboost_passeurs(df)
    print("\nLes pointeurs sont volontairement ignores (ROI systematiquement negatif).")
