"""
mlb/scripts/train_models.py — Entraînement et Backtest du modèle XGBoost V2 (Strikeouts).

Ce script lit le dataset généré par build_dataset.py (V2 avec Umpire + Statcast),
entraîne un modèle XGBoost avec validation croisée temporelle (TimeSeriesSplit),
et évalue sa précision + ROI simulé.

V2 Features : is_home, L5_K9, Opp_L10_K, L5_Velo, L5_SwStr%, Umpire_K_Factor
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(ROOT))

import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import joblib
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("MLB-Train")

DATASET_PATH = "mlb/data/dataset_strikeouts.csv"
MODEL_PATH = "mlb/models/xg_model_strikeouts.pkl"

def feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    """Création des features (moyennes glissantes) pour éviter le lookahead bias.
    
    V2 : Ajout de L5_Velo, L5_SwStr, et Umpire_K_Factor.
    """
    df = df.copy()
    df['game_date'] = pd.to_datetime(df['game_date'])
    df = df.sort_values(['player_name', 'game_date'])
    
    # --- FEATURES V1 (inchangées) ---
    # K/9 historique du lanceur (sur les 5 derniers matchs)
    df['IP_est'] = df['total_batters_faced'] / 3.0
    
    # On décale (shift) pour ne pas utiliser les stats du match qu'on veut prédire !
    df['L5_Strikeouts'] = df.groupby('player_name')['strikeouts'].transform(lambda x: x.shift(1).rolling(5, min_periods=1).mean())
    df['L5_IP'] = df.groupby('player_name')['IP_est'].transform(lambda x: x.shift(1).rolling(5, min_periods=1).mean())
    
    df['L5_K9'] = np.where(df['L5_IP'] > 0, (df['L5_Strikeouts'] * 9) / df['L5_IP'], 0)
    
    # Taux de Strikeout de l'équipe adverse (K%) sur les 10 derniers matchs
    df_team = df.sort_values(['opp_team', 'game_date'])
    df_team['Opp_L10_K'] = df_team.groupby('opp_team')['strikeouts'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean())
    df['Opp_L10_K'] = df_team['Opp_L10_K']
    
    # --- FEATURES V2 (nouvelles) ---
    
    # 1. Vélocité moyenne glissante sur les 5 derniers matchs (shifted)
    has_velo = 'avg_release_speed' in df.columns
    if has_velo:
        df['L5_Velo'] = df.groupby('player_name')['avg_release_speed'].transform(
            lambda x: x.shift(1).rolling(5, min_periods=1).mean()
        )
    else:
        df['L5_Velo'] = 0
        logger.warning("Colonne 'avg_release_speed' absente — L5_Velo mis à 0.")
        
    # 2. Swinging Strike % glissant sur les 5 derniers matchs (shifted)
    has_swstr = 'swinging_strike_pct' in df.columns
    if has_swstr:
        df['L5_SwStr'] = df.groupby('player_name')['swinging_strike_pct'].transform(
            lambda x: x.shift(1).rolling(5, min_periods=1).mean()
        )
    else:
        df['L5_SwStr'] = 0
        logger.warning("Colonne 'swinging_strike_pct' absente — L5_SwStr mis à 0.")
        
    # 2.5 Spin Rate
    has_spin = 'avg_spin_rate' in df.columns
    if has_spin:
        df['L5_Spin'] = df.groupby('player_name')['avg_spin_rate'].transform(
            lambda x: x.shift(1).rolling(5, min_periods=1).mean()
        )
    else:
        df['L5_Spin'] = 0
    
    # 3. Umpire K-Factor : Moyenne historique de K par match quand cet arbitre officie
    has_umpire = 'umpire' in df.columns
    if has_umpire:
        # On calcule la moyenne de K globale par arbitre SUR TOUT le dataset
        # puis on la normalise par rapport à la moyenne générale
        global_avg_k = df['strikeouts'].mean()
        umpire_avg = df.groupby('umpire')['strikeouts'].mean()
        df['Umpire_K_Factor'] = df['umpire'].map(umpire_avg) / global_avg_k
        df['Umpire_K_Factor'] = df['Umpire_K_Factor'].fillna(1.0)  # Arbitre inconnu = facteur neutre
        
        # Log des arbitres extrêmes
        top_ump = umpire_avg.nlargest(3)
        bot_ump = umpire_avg.nsmallest(3)
        logger.info(f"👨‍⚖️ Top 3 Umpires Pro-K : {dict(top_ump.round(1))}")
        logger.info(f"👨‍⚖️ Bot 3 Umpires Anti-K : {dict(bot_ump.round(1))}")
    else:
        df['Umpire_K_Factor'] = 1.0
        logger.warning("Colonne 'umpire' absente — Umpire_K_Factor mis à 1.0.")
    
    # Remplir les NaN (premiers matchs de la saison)
    df = df.fillna(0)
    
    return df

def train_and_backtest():
    """Entraîne le modèle XGBoost V2 et effectue un backtest complet."""
    from mlb.core.database import load_all_pitcher_stats
    df = load_all_pitcher_stats()
    
    if df.empty:
        logger.error("La base de données SQLite est vide. Lancez mlb/scripts/build_dataset.py d'abord.")
        return
        
    logger.info(f"Dataset chargé : {len(df)} matchs.")
    
    # 1. Feature Engineering V2
    df = feature_engineering(df)
    
    # On retire les matchs où l'on n'a pas d'historique (les premiers matchs de chaque joueur)
    df_train = df[df['L5_K9'] > 0].copy()
    logger.info(f"Matchs exploitables (avec historique) : {len(df_train)}")
    
    if len(df_train) < 50:
        logger.error("Pas assez de données pour entraîner le modèle.")
        return
        
    # 2. Préparation pour XGBoost — Features Championnes (A/B Test)
    features = ['is_home', 'L5_K9', 'Opp_L10_K', 'L5_Spin']
    X = df_train[features]
    y = df_train['strikeouts']
    
    # 3. Validation Croisée Temporelle (TimeSeriesSplit)
    tscv = TimeSeriesSplit(n_splits=5)
    model = xgb.XGBRegressor(
        objective='reg:squarederror',
        n_estimators=150,  # Augmenté de 100 à 150 pour les nouvelles features
        learning_rate=0.05,
        max_depth=4,       # Augmenté de 3 à 4 pour capturer les interactions
        min_child_weight=5,  # Régularisation contre l'overfitting
        subsample=0.8,       # Bagging pour la robustesse
        colsample_bytree=0.8,
        random_state=42
    )
    
    rmses = []
    maes = []
    
    # --- GRID SEARCH POUR LE SEUIL (THRESHOLD) OPTIMAL ---
    logger.info("=== RECHERCHE DU SEUIL OPTIMAL (GRID SEARCH) ===")
    thresholds = [0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5]
    best_roi = -999.0
    best_th = 0.0
    
    for th in thresholds:
        profit_u = 0.0
        paris_joues = 0
        paris_gagnes = 0
        
        for train_index, test_index in tscv.split(X):
            X_train, X_test = X.iloc[train_index], X.iloc[test_index]
            y_train, y_test = y.iloc[train_index], y.iloc[test_index]
            
            model.fit(X_train, y_train)
            preds = model.predict(X_test)
            
            lignes_bookmaker = np.round(X_test['L5_K9'])
            
            for i in range(len(preds)):
                pred_k = preds[i]
                ligne = lignes_bookmaker.iloc[i]
                vrai_k = y_test.iloc[i]
                
                if pred_k >= ligne + th:
                    paris_joues += 1
                    if vrai_k > ligne:
                        profit_u += 0.85
                        paris_gagnes += 1
                    else:
                        profit_u -= 1.0
                        
        if paris_joues > 0:
            roi = (profit_u / paris_joues) * 100
            winrate = (paris_gagnes / paris_joues) * 100
            logger.info(f"Seuil +{th:.1f} -> Paris: {paris_joues:3d} | Winrate: {winrate:4.1f}% | Profit: {profit_u:+5.2f} U | ROI: {roi:+5.1f}%")
            if roi > best_roi and paris_joues >= 20: # Min 20 paris pour être significatif
                best_roi = roi
                best_th = th
                
    logger.info(f"🏆 SEUIL OPTIMAL TROUVÉ : +{best_th:.1f} K (ROI: {best_roi:+.1f}%)")
    
    # On sauvegarde le threshold optimal dans le fichier pour l'inférence
    global OPTIMAL_THRESHOLD
    OPTIMAL_THRESHOLD = best_th
    
    # 4. Entraînement final sur tout le dataset
    model.fit(X, y)
    
    # Importance des features V2
    importance = model.feature_importances_
    logger.info("=== IMPORTANCE DES VARIABLES (V2) ===")
    feat_imp = sorted(zip(features, importance), key=lambda x: -x[1])
    for f, imp in feat_imp:
        bar = "█" * int(imp * 50)
        logger.info(f"  {f:20s} : {imp*100:5.1f}%  {bar}")
        
    # 5. Sauvegarde
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump({'model': model, 'threshold': OPTIMAL_THRESHOLD}, MODEL_PATH)
    logger.info(f"✅ Modèle V2 et Seuil ({OPTIMAL_THRESHOLD}) sauvegardés dans {MODEL_PATH}")

if __name__ == "__main__":
    train_and_backtest()
