import pandas as pd
import numpy as np
import joblib
from xgboost import XGBClassifier

def main():
    print("Entraînement du modèle XGBoost Production (V5)...")
    
    # Charger les données massives V4
    df = pd.read_csv('backtests/backtest_v4_features.csv')
    
    # Features disponibles en PRODUCTION dans last 10.csv
    features = [
        'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 'season_g',
        'ga_g', 'hdca_g', 'pp1', 'is_home', 'is_b2b', 'opp_is_b2b',
        'consec_goals', 'qs_v10'
    ]
    
    # Features dérivées fabricables en production
    df['luck_factor'] = df['l10_goals'] / np.maximum(df['ixg_l10'], 0.01) # Approx
    df['ixg_x_hdcf'] = df['ixg_l10'] * df['hdcf_l10']
    df['sog_x_atoi'] = df['sog_l10'] * df['atoi_l10']
    df['ixg_x_ga'] = df['ixg_l10'] * df['ga_g']
    df['streak_x_ixg'] = df['consec_goals'] * df['ixg_l10']
    
    features_prod = features + ['luck_factor', 'ixg_x_hdcf', 'sog_x_atoi', 'ixg_x_ga', 'streak_x_ixg']
    
    X = df[features_prod].values
    y = df['scored'].astype(int).values
    
    # Temporal Split (80/20)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    
    scale = (len(y_train) - y_train.sum()) / max(1, y_train.sum())
    
    model = XGBClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.03,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        scale_pos_weight=scale, eval_metric='logloss', random_state=42
    )
    
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
    
    test_df = df.iloc[split_idx:].copy()
    test_df['proba'] = model.predict_proba(X_test)[:, 1]
    
    print("\n[RÉSULTATS DE L'ÉTAPE 1 : XGBOOST PROD]")
    
    # Benchmark V14.1 seul
    v10_safe = test_df[test_df['qs_v10'] >= 10.5]
    wr_base = v10_safe['scored'].mean() * 100
    n_base = len(v10_safe)
    print(f"Base SAFE (V10 >= 10.5) : {wr_base:.1f}% WR ({n_base} picks)")
    
    # Avec filtre XGBoost
    v10_xgb = v10_safe[v10_safe['proba'] >= 0.55]
    wr_xgb = v10_xgb['scored'].mean() * 100
    n_xgb = len(v10_xgb)
    
    print(f"SAFE + XGB Proba >= 0.55 : {wr_xgb:.1f}% WR ({n_xgb} picks)")
    diff = wr_xgb - wr_base
    print(f"Delta Étape 1 : {diff:+.1f}% WR")
    
    if diff > 0:
        print("\nVALIDE ✅ Le modèle augmente le WR en utilisant les features de production.")
        joblib.dump({
            'model': model,
            'features': features_prod,
            'version': 'v5_prod'
        }, './models/prod_model_v5.pkl')
    else:
        print("\nÉCHEC ❌ Le modèle ne performe pas en condition Prod.")

if __name__ == '__main__':
    main()
