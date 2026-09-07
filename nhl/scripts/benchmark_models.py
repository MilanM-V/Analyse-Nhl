"""
scripts/benchmark_models.py — Benchmark rigoureux XGBoost vs LightGBM vs CatBoost vs Ensemble.

Compare les 3 algorithmes majeurs de gradient boosting et leurs combinaisons
(Blending pondéré & Stacking) sous validation croisée temporelle stricte
(TimeSeriesSplit) et évaluation sur holdout jamais vu.

Usage:
    python nhl/scripts/benchmark_models.py
"""
import sqlite3
import pandas as pd
import numpy as np
import sys
import os
from datetime import timedelta

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from scipy.optimize import minimize

from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from catboost import CatBoostClassifier

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "bot_database.db")

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
    """Charge et prépare les features chronologiquement."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM players WHERE but IS NOT NULL AND but != ''", conn)
    conn.close()

    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    for col in ['ixg', 'hdcf', 'sog', 'atoi']:
        df[f'{col}_l10'] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    for col in ['season_g', 'season_a', 'season_pts', 'ga_g', 'hdca_g']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    df['pp1'] = pd.to_numeric(df['pp1'], errors='coerce').fillna(0).astype(int)
    df['is_home'] = pd.to_numeric(df['is_home'], errors='coerce').fillna(0).astype(int)
    df['is_b2b'] = pd.to_numeric(df['b2b'], errors='coerce').fillna(0).astype(int)
    df['opp_is_b2b'] = pd.to_numeric(df.get('opp_b2b', 0), errors='coerce').fillna(0).astype(int)
    df['consec_goals'] = pd.to_numeric(df.get('consec_goals', 0), errors='coerce').fillna(0)

    df['ixg_x_hdcf'] = df['ixg_l10'] * df['hdcf_l10']
    df['sog_x_atoi'] = df['sog_l10'] * df['atoi_l10']
    df['ixg_x_ga'] = df['ixg_l10'] * df['ga_g']

    df['target_but'] = (pd.to_numeric(df['but'], errors='coerce').fillna(0) > 0).astype(int)
    df['target_ast'] = (pd.to_numeric(df['assist'], errors='coerce').fillna(0) > 0).astype(int)
    return df


def get_base_models(scale_pos: float):
    """Initialise les 3 modèles avec des hyperparamètres régularisés."""
    xgb = XGBClassifier(
        n_estimators=100, max_depth=3, learning_rate=0.05,
        scale_pos_weight=scale_pos, eval_metric='logloss',
        random_state=42, subsample=0.8, colsample_bytree=0.8,
        verbosity=0
    )
    lgb = LGBMClassifier(
        n_estimators=100, max_depth=3, num_leaves=7, learning_rate=0.05,
        scale_pos_weight=scale_pos, random_state=42,
        subsample=0.8, colsample_bytree=0.8,
        verbose=-1
    )
    cat = CatBoostClassifier(
        iterations=100, depth=3, learning_rate=0.05,
        scale_pos_weight=scale_pos, random_seed=42,
        verbose=False
    )
    return {'XGBoost': xgb, 'LightGBM': lgb, 'CatBoost': cat}


def benchmark_market(df: pd.DataFrame, features: list, target_col: str, market_name: str):
    """Benchmark complet XGBoost vs LightGBM vs CatBoost vs Ensemble."""
    print(f"\n{'=' * 75}")
    print(f" BENCHMARK COMPARATIF : MARCHÉ {market_name.upper()}")
    print(f"{'=' * 75}")

    total_days = max(1, (df['date'].max() - df['date'].min()).days)
    holdout_days = min(30, max(5, int(total_days * 0.20)))
    cutoff_date = df['date'].max() - timedelta(days=holdout_days)

    df_train = df[df['date'] <= cutoff_date].copy()
    df_holdout = df[df['date'] > cutoff_date].copy()

    X_train = df_train[features].values
    y_train = df_train[target_col].values
    X_holdout = df_holdout[features].values
    y_holdout = df_holdout[target_col].values

    n_pos = sum(y_train)
    n_neg = len(y_train) - n_pos
    scale_pos = n_neg / max(1, n_pos)

    print(f"  Train: {len(df_train)} samples ({df_train['date'].min().date()} -> {df_train['date'].max().date()})")
    print(f"  Holdout: {len(df_holdout)} samples ({df_holdout['date'].min().date()} -> {df_holdout['date'].max().date()})")
    print(f"  Positifs train: {n_pos}/{len(y_train)} ({n_pos/len(y_train)*100:.1f}%) | scale_pos={scale_pos:.2f}\n")

    base_models = get_base_models(scale_pos)
    calibrated_models = {}
    preds_holdout = {}
    oof_train_preds = {name: np.zeros(len(y_train)) for name in base_models}

    # TimeSeriesSplit pour générer les méta-features Out-of-Fold (OOF) SANS leakage
    n_splits = min(4, max(2, len(y_train) // 400))
    tscv = TimeSeriesSplit(n_splits=n_splits)

    # 1. Évaluation et calibration des modèles individuels
    for name, model in base_models.items():
        # Génération OOF pour le stacking
        for train_idx, val_idx in tscv.split(X_train):
            X_tr, y_tr = X_train[train_idx], y_train[train_idx]
            X_val = X_train[val_idx]
            m_clone = get_base_models(scale_pos)[name]
            m_clone.fit(X_tr, y_tr)
            oof_train_preds[name][val_idx] = m_clone.predict_proba(X_val)[:, 1]

        # Entraînement complet calibré (isotonique via TimeSeriesSplit)
        calibrated = CalibratedClassifierCV(model, method='isotonic', cv=tscv)
        calibrated.fit(X_train, y_train)
        calibrated_models[name] = calibrated
        preds_holdout[name] = calibrated.predict_proba(X_holdout)[:, 1]

    # Découper les OOF sur la partie où tous les folds ont prédit
    # Dans TimeSeriesSplit, les premiers indices (fold 0 train) n'ont pas d'OOF.
    first_val_idx = list(tscv.split(X_train))[0][1][0]
    X_meta_train = np.column_stack([oof_train_preds[name][first_val_idx:] for name in base_models])
    y_meta_train = y_train[first_val_idx:]

    # 2. Construction de l'Ensemble Blending (Poids convexes optimisés sur Brier score)
    def brier_obj(weights):
        w = np.array(weights)
        w = w / np.sum(w)
        blend = sum(w[i] * X_meta_train[:, i] for i in range(len(w)))
        return brier_score_loss(y_meta_train, blend)

    init_weights = [1.0 / len(base_models)] * len(base_models)
    bounds = [(0, 1) for _ in base_models]
    cons = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0})
    res_opt = minimize(brier_obj, init_weights, bounds=bounds, constraints=cons)
    blend_weights = res_opt.x / np.sum(res_opt.x)

    # Prédictions Holdout Blending
    preds_holdout['Blending (Convexe)'] = sum(
        blend_weights[i] * preds_holdout[name] for i, name in enumerate(base_models)
    )

    # 3. Construction du Stacking avec Méta-modèle Régression Logistique (L2)
    meta_model = LogisticRegression(C=0.1, solver='lbfgs')
    meta_model.fit(X_meta_train, y_meta_train)

    X_meta_holdout = np.column_stack([preds_holdout[name] for name in base_models])
    stack_raw_holdout = meta_model.predict_proba(X_meta_holdout)[:, 1]
    preds_holdout['Stacking (LogReg L2)'] = stack_raw_holdout

    # Calibration isotonique finale du stacking
    from sklearn.isotonic import IsotonicRegression
    meta_train_probas = meta_model.predict_proba(X_meta_train)[:, 1]
    iso_reg = IsotonicRegression(out_of_bounds='clip')
    iso_reg.fit(meta_train_probas, y_meta_train)
    preds_holdout['Stacking Calibré'] = iso_reg.predict(stack_raw_holdout)

    # --- TABLEAU DE RÉSULTATS COMPARATIFS ---
    results = []
    real_rate = float(y_holdout.mean())

    for model_name, probas in preds_holdout.items():
        auc = roc_auc_score(y_holdout, probas)
        brier = brier_score_loss(y_holdout, probas)
        loss = log_loss(y_holdout, probas)
        mean_prob = float(probas.mean())
        cal_err = abs(mean_prob - real_rate)

        results.append({
            'Modèle': model_name,
            'AUC-ROC': auc,
            'Brier Score': brier,
            'Log-Loss': loss,
            'Proba Moy': mean_prob,
            'Écart Calib': cal_err
        })

    df_res = pd.DataFrame(results).sort_values('Brier Score', ascending=True)

    print(f"{'Modèle':<24} | {'AUC-ROC':<8} | {'Brier':<8} | {'Log-Loss':<8} | {'Proba Moy':<9} | {'Écart Calib':<11}")
    print("-" * 80)
    for _, r in df_res.iterrows():
        print(f"{r['Modèle']:<24} | {r['AUC-ROC']:<8.4f} | {r['Brier Score']:<8.4f} | {r['Log-Loss']:<8.4f} | {r['Proba Moy']:<9.4f} | {r['Écart Calib']:<11.4f}")

    print(f"\n  Taux réel Holdout: {real_rate:.4f} ({int(sum(y_holdout))}/{len(y_holdout)} positifs)")
    print(f"  Poids Blending optimaux : " + ", ".join([f"{name}: {blend_weights[i]:.2f}" for i, name in enumerate(base_models)]))
    best_model = df_res.iloc[0]['Modèle']
    print(f"  🏆 Modèle Champion (plus faible Brier Score) : {best_model}\n")

    return df_res, blend_weights, meta_model


if __name__ == "__main__":
    print("Chargement des données pour le Benchmark...")
    df = load_clean_data()
    print(f"{len(df)} échantillons chargés.")

    res_but, weights_but, meta_but = benchmark_market(df, FEATURES_BUT, 'target_but', 'Buteurs')
    res_ast, weights_ast, meta_ast = benchmark_market(df, FEATURES_AST, 'target_ast', 'Passeurs')
