import sqlite3
import pandas as pd
import numpy as np
import os
import joblib
from xgboost import XGBClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import log_loss, roc_auc_score, brier_score_loss

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "bot_database.db")
MODELS_DIR = os.path.join(ROOT, "models")

os.makedirs(MODELS_DIR, exist_ok=True)

# Features propres sans fuite de données
FEATURES = [
    'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 
    'season_g', 'season_a', 'season_pts',
    'ga_g', 'hdca_g', 'pp1', 'is_home', 
    'is_b2b', 'opp_is_b2b', 'consec_goals',
    'ixg_x_hdcf', 'sog_x_atoi', 'ixg_x_ga'
]

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
    df['target_pts'] = (pd.to_numeric(df['point'], errors='coerce').fillna(0) > 0).astype(int)
    
    return df

def train_and_evaluate(df, target_col, model_name):
    print(f"\n{'='*50}\nENTRAINEMENT : {model_name.upper()}\n{'='*50}")
    
    X = df[FEATURES].values
    y = df[target_col].values
    
    # TimeSeriesSplit (Empêche de lire le futur)
    tscv = TimeSeriesSplit(n_splits=5)
    
    auc_scores = []
    brier_scores = []
    
    best_model = None
    best_brier = float('inf')
    
    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        X_train, y_train = X[train_idx], y[train_idx]
        X_test, y_test = X[test_idx], y[test_idx]
        
        # Poids pour gérer le déséquilibre des classes
        scale_pos = (len(y_train) - sum(y_train)) / max(1, sum(y_train))
        
        # Hyperparamètres conservateurs pour éviter l'overfitting
        model = XGBClassifier(
            n_estimators=100, 
            max_depth=3,          # Faible profondeur pour généraliser
            learning_rate=0.05, 
            scale_pos_weight=scale_pos,
            eval_metric='logloss',
            random_state=42,
            subsample=0.8,        # Bagging
            colsample_bytree=0.8
        )
        
        model.fit(X_train, y_train)
        preds = model.predict_proba(X_test)[:, 1]
        
        # Métriques
        if sum(y_test) > 0 and len(np.unique(y_test)) > 1:
            auc = roc_auc_score(y_test, preds)
            brier = brier_score_loss(y_test, preds)
            
            auc_scores.append(auc)
            brier_scores.append(brier)
            
            if brier < best_brier:
                best_brier = brier
                best_model = model
                
        print(f"Fold {fold+1}: Marge OOS -> Test sur {len(y_test)} rows | Base Winrate: {sum(y_test)/len(y_test)*100:.1f}%")

    if auc_scores:
        print(f"\n=> RESULTATS HORS-ECHANTILLON (Out-Of-Sample):")
        print(f"   AUC moyen: {np.mean(auc_scores):.3f} (Si proche de 0.5 = Hasard)")
        print(f"   Brier Score moyen: {np.mean(brier_scores):.3f} (Plus c'est bas, mieux c'est)")
    
    # Entraînement final sur TOUTES les données avec les paramètres robustes
    print("\n=> Entraînement du modèle de production sur 100% des données...")
    final_scale = (len(y) - sum(y)) / max(1, sum(y))
    final_model = XGBClassifier(
        n_estimators=100, max_depth=3, learning_rate=0.05,
        scale_pos_weight=final_scale, eval_metric='logloss',
        random_state=42, subsample=0.8, colsample_bytree=0.8
    )
    final_model.fit(X, y)
    
    # Sauvegarde
    path = os.path.join(MODELS_DIR, f'xg_model_{model_name}.pkl')
    joblib.dump({'model': final_model, 'features': FEATURES}, path)
    print(f"OK Modele sauvegarde dans {path}")
    
    # Importance des features
    importances = final_model.feature_importances_
    indices = np.argsort(importances)[::-1][:5]
    print("   Top 5 Features:")
    for i in indices:
        print(f"     - {FEATURES[i]}: {importances[i]:.3f}")

if __name__ == "__main__":
    print("Chargement des données...")
    df = load_clean_data()
    print(f"{len(df)} échantillons chargés avec chronologie respectée.")
    
    train_and_evaluate(df, 'target_but', 'but')
    train_and_evaluate(df, 'target_ast', 'ast')
    train_and_evaluate(df, 'target_pts', 'pts')
