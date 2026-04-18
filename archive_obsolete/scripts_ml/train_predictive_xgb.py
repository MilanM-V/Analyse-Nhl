"""
train_predictive_xgb.py — Entraîne un XGBoost PRÉDICTIF sur les features L10 
calculées AVANT chaque match (issues du backtest massif).

Contrairement au modèle précédent (entraîné sur les stats du match en cours),
ce modèle utilise uniquement des données disponibles AVANT le match.
"""
import pandas as pd
import numpy as np
import joblib
import os
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

INPUT_CSV = "./backtest_results_v2.csv"
MODEL_PATH = "./models/pregame_model_v2.pkl"

def main():
    print("=" * 60)
    print("  ENTRAÎNEMENT XGBOOST PRÉDICTIF (Features L10 pré-match)")
    print("=" * 60)

    df = pd.read_csv(INPUT_CSV)
    print(f"\n  Dataset : {len(df):,} entrées joueur-match")
    print(f"  Taux de base (% joueurs ayant marqué) : {df['scored'].mean()*100:.1f}%")

    # Features disponibles AVANT le match
    features = ['ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 'ga_g', 'score']
    # 'score' = le score V10 lui-même (contient l'info PP1, contexte, etc.)
    
    # Vérifier les colonnes
    for f in features:
        if f not in df.columns:
            print(f"  ERREUR: colonne '{f}' manquante !")
            return

    # Ajouter des features dérivées
    df['ixg_x_hdcf'] = df['ixg_l10'] * df['hdcf_l10']
    df['sog_x_atoi'] = df['sog_l10'] * df['atoi_l10']
    df['ixg_x_ga'] = df['ixg_l10'] * df['ga_g']
    
    features_extended = features + ['ixg_x_hdcf', 'sog_x_atoi', 'ixg_x_ga']
    
    # Nettoyage
    df = df.dropna(subset=features_extended + ['scored'])
    
    X = df[features_extended].values
    y = df['scored'].astype(int).values

    print(f"  Features : {features_extended}")
    print(f"  Positifs (buts) : {y.sum():,} ({y.mean()*100:.1f}%)")
    print(f"  Négatifs (0 but) : {(len(y)-y.sum()):,}")

    # Split temporel : on utilise 80% premiers matchs pour train, 20% derniers pour test
    # (plus réaliste qu'un split aléatoire pour du time-series)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    
    print(f"\n  Train : {len(X_train):,} | Test : {len(X_test):,}")

    # Balance des classes
    scale = (len(y_train) - y_train.sum()) / max(1, y_train.sum())
    
    model = XGBClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale,
        eval_metric='logloss',
        random_state=42
    )
    
    print("\n  Entraînement XGBoost (200 arbres, depth=5)...")
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
    
    # Évaluation
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]
    
    print("\n  --- Rapport de classification (test set) ---")
    print(classification_report(y_test, y_pred, target_names=['Pas de but', 'But']))
    
    # Importance des features
    importance = model.feature_importances_
    feat_imp = sorted(zip(features_extended, importance), key=lambda x: x[1], reverse=True)
    print("\n  --- Importance des features ---")
    for fname, imp in feat_imp:
        bar = "█" * int(imp * 50)
        print(f"  {fname:18s} : {imp:.3f} {bar}")

    # ── Scanner de seuils sur les PROBAS du modèle ──
    print("\n" + "=" * 60)
    print("  SCANNER DE SEUILS SUR PROBABILITÉS XGBoost")
    print("=" * 60)

    test_df = df.iloc[split_idx:].copy()
    test_df['proba'] = y_proba
    n_test_matches = test_df['game_id'].nunique()

    # Distribution WR par palier de proba
    print(f"\n  {'Proba ≥':>10s} | {'WR':>7s} | {'N Paris':>8s} | {'Picks/Match':>12s} | {'ROI (2.6)':>10s}")
    print("  " + "-" * 60)
    
    for thresh in [0.50, 0.45, 0.42, 0.40, 0.38, 0.36, 0.34, 0.32, 0.30, 0.28, 0.26, 0.24, 0.22, 0.20, 0.18, 0.15]:
        sub = test_df[test_df['proba'] >= thresh]
        if len(sub) < 10:
            continue
        wr = sub['scored'].mean() * 100
        ppm = len(sub) / max(n_test_matches, 1)
        wins = sub['scored'].sum()
        profit = (wins * 2.60) - len(sub)
        roi = (profit / len(sub)) * 100
        marker = " ◄" if ppm >= 2.0 and wr >= 40.0 else ""
        print(f"  {thresh:>10.2f} | {wr:>6.1f}% | {len(sub):>8,} | {ppm:>11.2f} | {roi:>+9.1f}%{marker}")

    # Sauvegarder le modèle + metadata
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump({
        'model': model,
        'features': features_extended,
        'version': 'v2_predictive_l10',
    }, MODEL_PATH)
    print(f"\n  Modèle sauvegardé : {MODEL_PATH}")
    print("=" * 60)


if __name__ == '__main__':
    main()
