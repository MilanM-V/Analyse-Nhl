"""
mlb/scripts/ab_test_features.py — A/B Testing des nouvelles variables V2.

Protocole :
1. Baseline V1 : ['is_home', 'L5_K9', 'Opp_L10_K'] → notre référence (+27.85 U)
2. On ajoute UNE variable à la fois
3. Si Profit U augmente ET ROI augmente → ON GARDE
4. Sinon → ON JETTE

Résultat : un tableau comparatif clair pour décider.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(ROOT))

import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_absolute_error
import joblib
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("MLB-ABTest")

DATASET_PATH = "mlb/data/dataset_strikeouts.csv"
MODEL_PATH = "mlb/models/xg_model_strikeouts.pkl"


def feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    """Création de TOUTES les features possibles (on choisira lesquelles utiliser après)."""
    df = df.copy()
    df['game_date'] = pd.to_datetime(df['game_date'])
    df = df.sort_values(['player_name', 'game_date'])
    
    # V1 Features
    df['IP_est'] = df['total_batters_faced'] / 3.0
    df['L5_Strikeouts'] = df.groupby('player_name')['strikeouts'].transform(
        lambda x: x.shift(1).rolling(5, min_periods=1).mean()
    )
    df['L5_IP'] = df.groupby('player_name')['IP_est'].transform(
        lambda x: x.shift(1).rolling(5, min_periods=1).mean()
    )
    df['L5_K9'] = np.where(df['L5_IP'] > 0, (df['L5_Strikeouts'] * 9) / df['L5_IP'], 0)
    
    df_team = df.sort_values(['opp_team', 'game_date'])
    df_team['Opp_L10_K'] = df_team.groupby('opp_team')['strikeouts'].transform(
        lambda x: x.shift(1).rolling(10, min_periods=1).mean()
    )
    df['Opp_L10_K'] = df_team['Opp_L10_K']
    
    # V2 Features
    if 'avg_release_speed' in df.columns:
        df['L5_Velo'] = df.groupby('player_name')['avg_release_speed'].transform(
            lambda x: x.shift(1).rolling(5, min_periods=1).mean()
        )
    else:
        df['L5_Velo'] = 0
        
    if 'swinging_strike_pct' in df.columns:
        df['L5_SwStr'] = df.groupby('player_name')['swinging_strike_pct'].transform(
            lambda x: x.shift(1).rolling(5, min_periods=1).mean()
        )
    else:
        df['L5_SwStr'] = 0
    
    if 'avg_spin_rate' in df.columns:
        df['L5_Spin'] = df.groupby('player_name')['avg_spin_rate'].transform(
            lambda x: x.shift(1).rolling(5, min_periods=1).mean()
        )
    else:
        df['L5_Spin'] = 0
        
    if 'umpire' in df.columns and df['umpire'].notna().any():
        global_avg_k = df['strikeouts'].mean()
        umpire_avg = df.groupby('umpire')['strikeouts'].mean()
        df['Umpire_K_Factor'] = df['umpire'].map(umpire_avg) / global_avg_k
        df['Umpire_K_Factor'] = df['Umpire_K_Factor'].fillna(1.0)
    else:
        df['Umpire_K_Factor'] = 1.0
    
    df = df.fillna(0)
    return df


def run_backtest(X: pd.DataFrame, y: pd.Series, label: str) -> dict:
    """Entraîne et backteste un modèle avec les features données."""
    tscv = TimeSeriesSplit(n_splits=5)
    model = xgb.XGBRegressor(
        objective='reg:squarederror',
        n_estimators=100,
        learning_rate=0.05,
        max_depth=3,
        random_state=42
    )
    
    maes = []
    profit_u = 0.0
    paris_joues = 0
    paris_gagnes = 0
    
    for train_idx, test_idx in tscv.split(X):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
        
        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        maes.append(mean_absolute_error(y_test, preds))
        
        # Simulation identique à V1 (seuil +0.8, cote 1.85)
        lignes = np.round(X_test['L5_K9'])
        for i in range(len(preds)):
            if preds[i] >= lignes.iloc[i] + 0.8:
                paris_joues += 1
                if y_test.iloc[i] > lignes.iloc[i]:
                    profit_u += 0.85
                    paris_gagnes += 1
                else:
                    profit_u -= 1.0
    
    winrate = (paris_gagnes / paris_joues * 100) if paris_joues > 0 else 0
    roi = (profit_u / paris_joues * 100) if paris_joues > 0 else 0
    
    return {
        "label": label,
        "features": list(X.columns),
        "n_features": len(X.columns),
        "mae": round(np.mean(maes), 3),
        "paris": paris_joues,
        "wins": paris_gagnes,
        "winrate": round(winrate, 1),
        "profit_u": round(profit_u, 2),
        "roi": round(roi, 1),
    }


def main():
    from mlb.core.database import load_all_pitcher_stats
    df = load_all_pitcher_stats()
    
    if df.empty:
        logger.error("La base de données SQLite est vide. Lancez mlb/scripts/build_dataset.py d'abord.")
        return
    df = feature_engineering(df)
    df_train = df[df['L5_K9'] > 0].copy()
    
    y = df_train['strikeouts']
    
    # ===== CONFIGURATIONS À TESTER =====
    baseline_features = ['is_home', 'L5_K9', 'Opp_L10_K']
    
    tests = [
        ("🏠 BASELINE V1", baseline_features),
        ("⚡ + Vélocité", baseline_features + ['L5_Velo']),
        ("🌀 + SwStr%", baseline_features + ['L5_SwStr']),
        ("🔄 + Spin Rate", baseline_features + ['L5_Spin']),
        ("⚡🔄 + Velo + Spin Rate", baseline_features + ['L5_Velo', 'L5_Spin']),
        ("👨‍⚖️ + Umpire", baseline_features + ['Umpire_K_Factor']),
        ("⚡🌀 + Velo + SwStr", baseline_features + ['L5_Velo', 'L5_SwStr']),
        ("⚡🌀🔄 + Velo+SwStr+Spin", baseline_features + ['L5_Velo', 'L5_SwStr', 'L5_Spin']),
        ("🔥 TOUT V2", baseline_features + ['L5_Velo', 'L5_SwStr', 'L5_Spin', 'Umpire_K_Factor']),
    ]
    
    results = []
    
    logger.info("=" * 70)
    logger.info("       A/B TESTING — MLB FEATURES V2")
    logger.info("       Baseline : V1 (+27.85 U, ROI +17.5%)")
    logger.info("=" * 70)
    
    for label, features in tests:
        logger.info(f"\n--- Test: {label} ---")
        X = df_train[features]
        result = run_backtest(X, y, label)
        results.append(result)
        
        emoji = "✅" if result['profit_u'] > results[0]['profit_u'] else "❌"
        logger.info(f"  {emoji} Profit: {result['profit_u']:+.2f} U | ROI: {result['roi']:+.1f}% | Winrate: {result['winrate']}% | Paris: {result['paris']}")
    
    # ===== TABLEAU COMPARATIF =====
    logger.info("\n" + "=" * 70)
    logger.info("       TABLEAU COMPARATIF FINAL")
    logger.info("=" * 70)
    logger.info(f"{'Config':<30s} {'Profit':>8s} {'ROI':>7s} {'Win%':>6s} {'Paris':>6s} {'MAE':>6s}  Verdict")
    logger.info("-" * 85)
    
    baseline_profit = results[0]['profit_u']
    best_result = max(results, key=lambda r: r['profit_u'])
    
    for r in results:
        is_best = "⭐ BEST" if r == best_result else ""
        is_better = "✅ KEEP" if r['profit_u'] > baseline_profit and r != results[0] else ""
        is_worse = "❌ DROP" if r['profit_u'] <= baseline_profit and r != results[0] else ""
        verdict = is_best or is_better or is_worse or "BASE"
        
        logger.info(f"  {r['label']:<28s} {r['profit_u']:>+7.2f}U {r['roi']:>+6.1f}% {r['winrate']:>5.1f}% {r['paris']:>5d}  {r['mae']:>5.3f}  {verdict}")
    
    # ===== SAUVEGARDE DU MEILLEUR MODÈLE =====
    logger.info(f"\n🏆 MEILLEUR MODÈLE : {best_result['label']}")
    logger.info(f"   Features : {best_result['features']}")
    logger.info(f"   Profit : {best_result['profit_u']:+.2f} U | ROI : {best_result['roi']:+.1f}%")
    
    # Ré-entraîner le meilleur sur tout le dataset et sauvegarder
    best_features = best_result['features']
    X_best = df_train[best_features]
    
    final_model = xgb.XGBRegressor(
        objective='reg:squarederror',
        n_estimators=100,
        learning_rate=0.05,
        max_depth=3,
        random_state=42
    )
    final_model.fit(X_best, y)
    
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(final_model, MODEL_PATH)
    logger.info(f"✅ Modèle CHAMPION sauvegardé dans {MODEL_PATH}")
    
    # Afficher l'importance des features du champion
    logger.info("\n=== IMPORTANCE DES VARIABLES (CHAMPION) ===")
    for f, imp in sorted(zip(best_features, final_model.feature_importances_), key=lambda x: -x[1]):
        bar = "█" * int(imp * 50)
        logger.info(f"  {f:20s} : {imp*100:5.1f}%  {bar}")


if __name__ == "__main__":
    main()
