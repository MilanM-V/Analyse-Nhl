"""
scripts/train_models.py — Entraînement des modèles ML NHL (V2 — Calibré).

Corrections critiques par rapport à V1:
- Split temporel strict (holdout de 30 jours jamais vu)
- scale_pos_weight = ratio réel des classes (pas hardcodé à 4.0)
- CalibratedClassifierCV (isotonique) pour des probabilités calibrées
- Métriques affichées UNIQUEMENT sur le holdout (jamais sur le train)
- Métadonnées de train sauvegardées dans le .pkl pour traçabilité
"""
import sqlite3
import pandas as pd
import numpy as np
import sys
import os
import joblib

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from datetime import timedelta
from sklearn.metrics import roc_auc_score, brier_score_loss

# Import de notre architecture d'ensemble multi-boosting
import sys
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, os.path.dirname(ROOT_DIR))
from nhl.core.ensemble_model import NHLEnsembleClassifier

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "bot_database.db")
MODELS_DIR = os.path.join(ROOT, "models")

os.makedirs(MODELS_DIR, exist_ok=True)

# Features de production standard (DB courante)
FEATURES_BASE = [
    'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10',
    'season_g', 'season_a', 'season_pts',
    'ga_g', 'hdca_g', 'pp1', 'is_home',
    'is_b2b', 'opp_is_b2b', 'consec_goals',
    'ixg_x_hdcf', 'sog_x_atoi', 'ixg_x_ga',
    'is_top6', 'linemate_synergy', 'team_scoring_env',
    'implied_prob', 'goalie_weakness'
]
FEATURES_BUT = [f for f in FEATURES_BASE if f != 'season_a']
FEATURES_AST = FEATURES_BASE

# Features pour le super-dataset historique multi-saisons (avec priors vétérans et contexte équipe/gardien)
FEATURES_HIST_BASE = [
    'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 'l10_g', 'l10_a',
    'season_g', 'season_a', 'season_pts', 'ixg_x_hdcf', 'sog_x_atoi',
    'is_top6', 'prior_g60', 'prior_a60', 'prior_sog60', 'prior_sh_pct',
    'opp_xga_60', 'opp_hdca_60', 'opp_goalie_gsax_60', 'team_xg_60',
    'ixg_x_opp_xga', 'is_home', 'implied_prob', 'goalie_weakness'
]
FEATURES_HIST_BUT = [f for f in FEATURES_HIST_BASE if f not in ['season_a', 'l10_a', 'prior_a60']]
FEATURES_HIST_AST = [f for f in FEATURES_HIST_BASE if f not in ['prior_sh_pct']]

# Holdout : les 30 derniers jours ne sont JAMAIS utilisés pour l'entraînement
HOLDOUT_DAYS = 30


def load_clean_data(use_historical: bool = False):
    """Charge les données depuis SQLite ou le super-dataset Parquet multi-saisons."""
    if use_historical:
        parquet_path = os.path.join(ROOT, "data", "historical_dataset.parquet")
        if os.path.exists(parquet_path):
            print(f"Chargement du super-dataset Parquet ({parquet_path})...")
            df = pd.read_parquet(parquet_path)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            return df, FEATURES_HIST_BUT, FEATURES_HIST_AST

    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        "SELECT * FROM players WHERE but IS NOT NULL AND but != ''", conn
    )
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
    df['season_pts'] = pd.to_numeric(
        df['season_pts'], errors='coerce'
    ).fillna(0)

    df['ga_g'] = pd.to_numeric(df['ga_g'], errors='coerce').fillna(0)
    df['hdca_g'] = pd.to_numeric(df['hdca_g'], errors='coerce').fillna(0)

    df['pp1'] = pd.to_numeric(
        df['pp1'], errors='coerce'
    ).fillna(0).astype(int)
    df['is_home'] = pd.to_numeric(
        df['is_home'], errors='coerce'
    ).fillna(0).astype(int)
    df['is_b2b'] = pd.to_numeric(
        df['b2b'], errors='coerce'
    ).fillna(0).astype(int)
    df['opp_is_b2b'] = pd.to_numeric(
        df.get('opp_b2b', 0), errors='coerce'
    ).fillna(0).astype(int)
    df['consec_goals'] = pd.to_numeric(
        df.get('consec_goals', 0), errors='coerce'
    ).fillna(0)

    # Feature Engineering (Interactions & Synergies P10)
    df['ixg_x_hdcf'] = df['ixg_l10'] * df['hdcf_l10']
    df['sog_x_atoi'] = df['sog_l10'] * df['atoi_l10']
    df['ixg_x_ga'] = df['ixg_l10'] * df['ga_g']

    df['is_top6'] = ((df['atoi_l10'] >= 17.0) | (df['pp1'] == 1)).astype(int)
    df['linemate_synergy'] = (df['season_g'] + df['season_a']) * df['pp1']
    df['team_scoring_env'] = df['ga_g'] * df['hdca_g']

    # Nouvelles features quantitatives (P5)
    df['cote'] = pd.to_numeric(df.get('cote', np.nan), errors='coerce')
    df['implied_prob'] = np.where((df['cote'] > 1.05) & (df['cote'].notna()), 1.0 / df['cote'], 0.0)
    
    df['goalie_sv_pct'] = pd.to_numeric(df.get('goalie_sv_pct', np.nan), errors='coerce')
    df['goalie_weakness'] = np.where(df['goalie_sv_pct'] > 0, 1.0 - df['goalie_sv_pct'], 0.08)

    # Targets binaires
    df['target_but'] = (
        pd.to_numeric(df['but'], errors='coerce').fillna(0) > 0
    ).astype(int)
    df['target_ast'] = (
        pd.to_numeric(df['assist'], errors='coerce').fillna(0) > 0
    ).astype(int)

    return df, FEATURES_BUT, FEATURES_AST


def train_with_holdout(df, features, target_col, model_name):
    """Entraîne un modèle avec holdout temporel strict + calibration isotonique.

    Args:
        df: DataFrame trié chronologiquement.
        features: Liste des features à utiliser.
        target_col: Colonne cible ('target_but' ou 'target_ast').
        model_name: Nom pour la sauvegarde ('but' ou 'ast').
    """
    print(f"\n{'=' * 60}")
    print(f"ENTRAINEMENT : {model_name.upper()} "
          f"(Holdout {HOLDOUT_DAYS}j + Calibration Isotonique)")
    print(f"{'=' * 60}")

    # --- SPLIT TEMPOREL STRICT (Adaptatif si historique court) ---
    total_days = max(1, (df['date'].max() - df['date'].min()).days)
    effective_holdout = min(HOLDOUT_DAYS, max(5, int(total_days * 0.20)))
    cutoff_date = df['date'].max() - timedelta(days=effective_holdout)
    df_train = df[df['date'] <= cutoff_date].copy()
    df_holdout = df[df['date'] > cutoff_date].copy()

    print(f"  Période totale : {total_days} jours | Holdout effectif : {effective_holdout} jours")
    print(f"  Train :   {len(df_train)} samples "
          f"({df_train['date'].min().date()} -> "
          f"{df_train['date'].max().date()})")
    print(f"  Holdout:  {len(df_holdout)} samples "
          f"({df_holdout['date'].min().date()} -> "
          f"{df_holdout['date'].max().date()})")

    X_train = df_train[features].values
    y_train = df_train[target_col].values
    X_holdout = df_holdout[features].values
    y_holdout = df_holdout[target_col].values

    # --- MODÈLE DE BASE (scale_pos_weight = ratio réel) ---
    n_neg = int(len(y_train) - sum(y_train))
    n_pos = int(max(1, sum(y_train)))
    scale_pos = n_neg / n_pos
    print(f"  Classe positive: {n_pos}/{len(y_train)} "
          f"({n_pos / len(y_train) * 100:.1f}%) — "
          f"scale_pos_weight={scale_pos:.2f}")

    # --- MODÈLE MULTI-BOOSTING ENSEMBLE (XGB + LGBM + CatBoost avec Optuna) ---
    ensemble = NHLEnsembleClassifier(market=model_name, mode="ensemble", n_splits=3, random_state=42)
    ensemble.fit(X_train, y_train)

    print(f"  Modèle Champion identifié : {ensemble.best_model_name_}")
    if ensemble.weights_ is not None:
        poids_str = ", ".join([f"{k}: {ensemble.weights_[i]:.2f}" for i, k in enumerate(ensemble.models_.keys())])
        print(f"  Poids Blending optimaux : {poids_str}")

    # --- MÉTRIQUES SUR LE HOLDOUT (JAMAIS VU) ---
    holdout_auc = None
    holdout_brier = None

    probas_holdout = ensemble.predict_proba(X_holdout)[:, 1]

    if len(np.unique(y_holdout)) > 1 and len(y_holdout) >= 10:
        holdout_auc = float(roc_auc_score(y_holdout, probas_holdout))
        holdout_brier = float(brier_score_loss(y_holdout, probas_holdout))

        mean_proba = float(probas_holdout.mean())
        real_rate = float(y_holdout.mean())

        print(f"\n  --- HOLDOUT (données JAMAIS vues) ---")
        print(f"  AUC:                  {holdout_auc:.4f}")
        print(f"  Brier Score:          {holdout_brier:.4f}")
        print(f"  Proba moy. prédite:   {mean_proba:.4f}")
        print(f"  Taux réel:            {real_rate:.4f}")
        print(f"  Écart calibration:    {abs(mean_proba - real_rate):.4f}")

        if holdout_auc < 0.52:
            print(f"  ⚠️ ATTENTION : AUC < 0.52 — "
                  f"le modèle n'a presque pas de pouvoir prédictif OOS.")
    else:
        print(f"\n  ⚠️ Holdout trop petit ({len(y_holdout)} samples) "
              f"pour des métriques fiables.")

    # --- SAUVEGARDE ---
    path = os.path.join(MODELS_DIR, f'ml_model_{model_name}.pkl')
    joblib.dump({
        'model': ensemble,
        'features': features,
        'algo': 'multi_boosting_ensemble',
        'best_single_model': ensemble.best_model_name_,
        'weights': ensemble.weights_,
        'train_cutoff': str(cutoff_date.date()),
        'train_samples': len(df_train),
        'holdout_samples': len(df_holdout),
        'holdout_auc': holdout_auc,
        'holdout_brier': holdout_brier,
        'scale_pos_weight': scale_pos,
    }, path)
    print(f"\n  ✅ Modèle d'Ensemble calibré sauvegardé : {path}")


if __name__ == "__main__":
    use_hist = "--historical" in sys.argv
    print(f"Chargement des données ({'HISTORIQUE MULTI-SAISONS' if use_hist else 'DB COURANTE'})...")
    df, feat_but, feat_ast = load_clean_data(use_historical=use_hist)
    print(f"{len(df):,} échantillons chargés avec chronologie respectée.")

    train_with_holdout(df, feat_but, 'target_but', 'but')
    train_with_holdout(df, feat_ast, 'target_ast', 'ast')
    print("\nLes pointeurs sont volontairement ignorés "
          "(ROI systématiquement négatif).")
