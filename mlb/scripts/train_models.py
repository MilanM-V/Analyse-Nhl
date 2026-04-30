"""
mlb/scripts/train_models.py — Entraînement et Backtest du modèle XGBoost V2 (Strikeouts).

Ce script lit le dataset généré par build_dataset.py (V2 avec Umpire + Statcast),
entraîne un modèle XGBoost avec validation croisée temporelle (TimeSeriesSplit),
et évalue sa précision + ROI simulé.

V2 Features : is_home, L5_K9, Opp_L10_K, L5_Velo, L5_SwStr%, Umpire_K_Factor
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
    if not os.path.exists(DATASET_PATH):
        logger.error(f"Fichier {DATASET_PATH} introuvable. Lancez build_dataset.py d'abord.")
        return
        
    df = pd.read_csv(DATASET_PATH)
    logger.info(f"Dataset chargé : {len(df)} matchs.")
    
    # 1. Feature Engineering V2
    df = feature_engineering(df)
    
    # On retire les matchs où l'on n'a pas d'historique (les premiers matchs de chaque joueur)
    df_train = df[df['L5_K9'] > 0].copy()
    logger.info(f"Matchs exploitables (avec historique) : {len(df_train)}")
    
    if len(df_train) < 50:
        logger.error("Pas assez de données pour entraîner le modèle.")
        return
        
    # 2. Préparation pour XGBoost — V2 Features
    features = ['is_home', 'L5_K9', 'Opp_L10_K', 'L5_Velo', 'L5_SwStr', 'Umpire_K_Factor']
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
                    
    logger.info("=== RÉSULTATS BACKTEST V2 (Validation Croisée) ===")
    logger.info(f"Erreur Absolue Moyenne (MAE) : {np.mean(maes):.2f} Strikeouts")
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
    
    # Importance des features V2
    importance = model.feature_importances_
    logger.info("=== IMPORTANCE DES VARIABLES (V2) ===")
    feat_imp = sorted(zip(features, importance), key=lambda x: -x[1])
    for f, imp in feat_imp:
        bar = "█" * int(imp * 50)
        logger.info(f"  {f:20s} : {imp*100:5.1f}%  {bar}")
        
    # 5. Sauvegarde
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    logger.info(f"✅ Modèle V2 sauvegardé dans {MODEL_PATH}")

if __name__ == "__main__":
    train_and_backtest()
