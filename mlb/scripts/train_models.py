"""
mlb/scripts/train_models.py — Entraînement et Backtest du modèle XGBoost (Strikeouts).

Ce script lit le dataset généré par build_dataset.py, entraîne un modèle XGBoost
avec validation croisée temporelle (TimeSeriesSplit), et évalue sa précision.
"""

import os
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
    """Création des features (moyennes glissantes) pour éviter le lookahead bias."""
    df = df.copy()
    df['game_date'] = pd.to_datetime(df['game_date'])
    df = df.sort_values(['player_name', 'game_date'])
    
    # K/9 historique du lanceur (sur les 5 derniers matchs)
    # Note: On calcule les manches lancées (IP) en estimant 3 batteurs = 1 manche
    df['IP_est'] = df['total_batters_faced'] / 3.0
    
    # On décale (shift) pour ne pas utiliser les stats du match qu'on veut prédire !
    df['L5_Strikeouts'] = df.groupby('player_name')['strikeouts'].transform(lambda x: x.shift(1).rolling(5, min_periods=1).mean())
    df['L5_IP'] = df.groupby('player_name')['IP_est'].transform(lambda x: x.shift(1).rolling(5, min_periods=1).mean())
    
    df['L5_K9'] = np.where(df['L5_IP'] > 0, (df['L5_Strikeouts'] * 9) / df['L5_IP'], 0)
    
    # Taux de Strikeout de l'équipe adverse (K%) sur les 10 derniers matchs
    df_team = df.sort_values(['opp_team', 'game_date'])
    df_team['Opp_L10_K'] = df_team.groupby('opp_team')['strikeouts'].transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean())
    df['Opp_L10_K'] = df_team['Opp_L10_K']
    
    # Remplir les NaN (premiers matchs de la saison)
    df = df.fillna(0)
    
    return df

def train_and_backtest():
    if not os.path.exists(DATASET_PATH):
        logger.error(f"Fichier {DATASET_PATH} introuvable. Lancez build_dataset.py d'abord.")
        return
        
    df = pd.read_csv(DATASET_PATH)
    logger.info(f"Dataset chargé : {len(df)} matchs.")
    
    # 1. Feature Engineering
    df = feature_engineering(df)
    
    # On retire les matchs où l'on n'a pas d'historique (les premiers matchs de chaque joueur)
    df_train = df[df['L5_K9'] > 0].copy()
    logger.info(f"Matchs exploitables (avec historique) : {len(df_train)}")
    
    if len(df_train) < 50:
        logger.error("Pas assez de données pour entraîner le modèle. Veuillez télécharger une plus grande période (ex: 3-6 mois) dans build_dataset.py.")
        return
        
    # 2. Préparation pour XGBoost
    features = ['is_home', 'L5_K9', 'Opp_L10_K']
    X = df_train[features]
    y = df_train['strikeouts']
    
    # 3. Validation Croisée Temporelle (TimeSeriesSplit)
    tscv = TimeSeriesSplit(n_splits=5)
    model = xgb.XGBRegressor(
        objective='reg:squarederror',
        n_estimators=100,
        learning_rate=0.05,
        max_depth=3,
        random_state=42
    )
    
    rmses = []
    maes = []
    
    profit_u = 0.0
    paris_joues = 0
    paris_gagnes = 0
    
    for train_index, test_index in tscv.split(X):
        X_train, X_test = X.iloc[train_index], X.iloc[test_index]
        y_train, y_test = y.iloc[train_index], y.iloc[test_index]
        
        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        
        rmses.append(np.sqrt(mean_squared_error(y_test, preds)))
        maes.append(mean_absolute_error(y_test, preds))
        
        # --- SIMULATION ROI (1 Unité) ---
        # On simule que le bookmaker place la ligne (Over/Under) à la moyenne historique du lanceur (L5_K9 arrondi)
        # La cote standard pour un Over/Under en MLB est souvent autour de 1.85
        lignes_bookmaker = np.round(X_test['L5_K9'])
        
        for i in range(len(preds)):
            pred_k = preds[i]
            ligne = lignes_bookmaker.iloc[i]
            vrai_k = y_test.iloc[i]
            
            # Si l'IA prédit que le lanceur fera au moins 0.8 K de plus que sa ligne, on parie "OVER"
            if pred_k >= ligne + 0.8:
                paris_joues += 1
                if vrai_k > ligne:
                    profit_u += 0.85  # Gain net (Cote 1.85 - 1U mise)
                    paris_gagnes += 1
                else:
                    profit_u -= 1.0   # Perte de la mise
                    
            # Optionnel: on pourrait aussi parier UNDER si l'IA prédit beaucoup moins
            
    logger.info("=== RÉSULTATS BACKTEST (Validation Croisée) ===")
    logger.info(f"Erreur Absolue Moyenne (MAE) : {np.mean(maes):.2f} Strikeouts (L'IA se trompe de {np.mean(maes):.2f} K en moyenne)")
    logger.info(f"RMSE : {np.mean(rmses):.2f}")
    
    logger.info("=== SIMULATION DE PORTEFEUILLE (Flat Betting 1U) ===")
    if paris_joues > 0:
        winrate = (paris_gagnes / paris_joues) * 100
        roi = (profit_u / paris_joues) * 100
        logger.info(f"Paris joués : {paris_joues}")
        logger.info(f"Winrate : {winrate:.1f}% ({paris_gagnes} Gagnés / {paris_joues - paris_gagnes} Perdus)")
        logger.info(f"Profit : {profit_u:+.2f} Unités (ROI: {roi:+.1f}%)")
    else:
        logger.info("Aucun pari n'a validé les critères du modèle.")
    
    # 4. Entraînement final sur tout le dataset
    model.fit(X, y)
    
    # Importance des features
    importance = model.feature_importances_
    logger.info("=== IMPORTANCE DES VARIABLES ===")
    for f, imp in zip(features, importance):
        logger.info(f" - {f}: {imp*100:.1f}%")
        
    # 5. Sauvegarde
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    logger.info(f"✅ Modèle sauvegardé dans {MODEL_PATH}")

if __name__ == "__main__":
    train_and_backtest()
