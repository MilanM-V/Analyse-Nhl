"""
scripts/tune_hyperparams.py — Optimisation Bayésienne des Hyperparamètres via Optuna.

Recherche les meilleurs hyperparamètres pour XGBoost, LightGBM et CatBoost
sous validation croisée temporelle stricte (TimeSeriesSplit), en minimisant
le Brier Score moyen (précision probabiliste et calibration).

Sauvegarde les hyperparamètres optimaux dans nhl/config/optimal_hyperparams.json.

Usage:
    python nhl/scripts/tune_hyperparams.py [--trials 20]
"""
import sqlite3
import pandas as pd
import numpy as np
import sys
import os
import json
import argparse
from datetime import timedelta

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.calibration import CalibratedClassifierCV

from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from catboost import CatBoostClassifier

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "bot_database.db")
CONFIG_DIR = os.path.join(ROOT, "config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "optimal_hyperparams.json")

os.makedirs(CONFIG_DIR, exist_ok=True)

FEATURES_BUT = [
    'ixg_l10', 'sog_l10', 'atoi_l10', 'l10_g', 'l10_a', 
    'hdcf_l10', 'season_g', 'season_a', 'season_pts', 'sog_x_atoi', 'ixg_x_hdcf',
    'ga_g', 'hdca_g', 'pp1', 'is_home', 'is_b2b', 'opp_is_b2b', 'opp_goalie_gsax_60',
    'consec_goals', 'linemate_synergy', 'team_scoring_env', 'ixg_x_ga'
]
FEATURES_AST = FEATURES_BUT.copy()
FEATURES_PTS = FEATURES_BUT.copy()


def load_clean_data():
    parquet_path = os.path.join(ROOT, "data", "historical_dataset.parquet")
    df = pd.read_parquet(parquet_path)

    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    # Conversion des colonnes en numérique
    for col in FEATURES_BUT:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    df['target_but'] = (pd.to_numeric(df['I_F_goals'], errors='coerce').fillna(0) > 0).astype(int)
    df['target_ast'] = ((pd.to_numeric(df['I_F_primaryAssists'], errors='coerce').fillna(0) + pd.to_numeric(df['I_F_secondaryAssists'], errors='coerce').fillna(0)) > 0).astype(int)
    df['target_pts'] = ((df['I_F_goals'].fillna(0) + df['I_F_primaryAssists'].fillna(0) + df['I_F_secondaryAssists'].fillna(0)) >= 1).astype(int)
    return df


def optimize_model_for_market(X, y, scale_pos, algo_name, n_trials=20):
    """Optimise un algorithme spécifique via TimeSeriesSplit CV sur Brier Score."""
    n_splits = min(3, max(2, len(y) // 400))
    tscv = TimeSeriesSplit(n_splits=n_splits)

    def objective(trial):
        if algo_name == 'CatBoost':
            params = {
                'iterations': trial.suggest_int('iterations', 60, 150, step=30),
                'depth': trial.suggest_int('depth', 2, 5),
                'learning_rate': trial.suggest_float('learning_rate', 0.02, 0.12, log=True),
                'l2_leaf_reg': trial.suggest_float('l2_leaf_reg', 1.0, 10.0),
                'scale_pos_weight': scale_pos,
                'random_seed': 42,
                'verbose': False
            }
            model = CatBoostClassifier(**params)

        elif algo_name == 'LightGBM':
            params = {
                'n_estimators': trial.suggest_int('n_estimators', 60, 150, step=30),
                'max_depth': trial.suggest_int('max_depth', 2, 5),
                'num_leaves': trial.suggest_int('num_leaves', 4, 15),
                'learning_rate': trial.suggest_float('learning_rate', 0.02, 0.12, log=True),
                'reg_lambda': trial.suggest_float('reg_lambda', 0.5, 8.0),
                'subsample': trial.suggest_float('subsample', 0.7, 1.0),
                'colsample_bytree': trial.suggest_float('colsample_bytree', 0.7, 1.0),
                'scale_pos_weight': scale_pos,
                'random_state': 42,
                'verbose': -1
            }
            model = LGBMClassifier(**params)

        elif algo_name == 'XGBoost':
            params = {
                'n_estimators': trial.suggest_int('n_estimators', 60, 150, step=30),
                'max_depth': trial.suggest_int('max_depth', 2, 4),
                'learning_rate': trial.suggest_float('learning_rate', 0.02, 0.12, log=True),
                'reg_lambda': trial.suggest_float('reg_lambda', 1.0, 10.0),
                'subsample': trial.suggest_float('subsample', 0.7, 1.0),
                'colsample_bytree': trial.suggest_float('colsample_bytree', 0.7, 1.0),
                'scale_pos_weight': scale_pos,
                'eval_metric': 'logloss',
                'random_state': 42,
                'verbosity': 0
            }
            model = XGBClassifier(**params)
        else:
            raise ValueError(f"Algo inconnu: {algo_name}")

        scores = []
        for tr_idx, val_idx in tscv.split(X):
            X_tr, y_tr = X[tr_idx], y[tr_idx]
            X_val, y_val = X[val_idx], y[val_idx]
            try:
                # Calibration interne
                cal = CalibratedClassifierCV(model, method='isotonic', cv=2)
                cal.fit(X_tr, y_tr)
                p = cal.predict_proba(X_val)[:, 1]
                scores.append(brier_score_loss(y_val, p))
            except Exception:
                return 1.0  # Pénalité forte si échec
        return float(np.mean(scores))

    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    print(f"    [{algo_name}] Meilleur Brier Score CV: {study.best_value:.4f}")
    return study.best_params


def run_tuning(n_trials=20):
    print("=" * 70)
    print(" OPTUNA TUNING BAYÉSIEN — OPTIMISATION MULTI-BOOSTING NHL")
    print(f" Objectif : Minimiser le Brier Score moyen (TimeSeriesSplit, {n_trials} trials)")
    print("=" * 70)

    df = load_clean_data()
    best_config = {}

    markets = [
        ('but', FEATURES_BUT, 'target_but', 'BUTEURS'),
        ('ast', FEATURES_AST, 'target_ast', 'PASSEURS'),
        ('pts', FEATURES_PTS, 'target_pts', 'POINTS')
    ]

    for market_key, features, target_col, label in markets:
        print(f"\n--- OPTIMISATION MARCHÉ {label} ---")
        X = df[features].values
        y = df[target_col].values
        scale_pos = float((len(y) - sum(y)) / max(1, sum(y)))

        best_config[market_key] = {}
        for algo in ['CatBoost', 'LightGBM', 'XGBoost']:
            params = optimize_model_for_market(X, y, scale_pos, algo, n_trials=n_trials)
            best_config[market_key][algo] = params

    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(best_config, f, indent=4)

    print(f"\n✅ Configuration sauvegardée dans : {CONFIG_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=20, help="Nombre de trials Optuna par modèle")
    args = parser.parse_args()
    run_tuning(n_trials=args.trials)
