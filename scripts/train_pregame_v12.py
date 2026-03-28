import pandas as pd
import sqlite3
import os
import joblib
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report, f1_score
try:
    from imblearn.over_sampling import SMOTE
    HAS_SMOTE = True
except ImportError:
    HAS_SMOTE = False

DB_PATH = "./bot_database.db"
MODEL_PATH = "./pregame_model.pkl"

def main():
    """Entraîne un modèle XGBoost V12 sur l'historique des picks."""
    print("=== Démarrage de l'entraînement ML V12 (XGBoost) ===")

    if os.path.exists(DB_PATH):
        print("Lecture depuis la base de données SQLite...")
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query("SELECT * FROM picks WHERE but IS NOT NULL AND but != ''", conn)
        conn.close()
    elif os.path.exists('./stats/picks_log.csv'):
        print("Lecture depuis le fichier CSV...")
        df = pd.read_csv('./stats/picks_log.csv', sep=',')
        if len(df.columns) == 1:
            df = pd.read_csv('./stats/picks_log.csv', sep=';')

        df = df[df['but'].notna()]
        df = df[df['but'] != '']
    else:
        print("Erreur: Aucune donnée trouvée ou colonne 'but' vide pour entraîner le modèle.")
        return

    if len(df) < 50:
        print(f"Pas assez de données pour entraîner un modèle de qualité (seulement {len(df)}). Il en faut au moins 50.")
        return

    df['but'] = pd.to_numeric(df['but'], errors='coerce')
    df = df.dropna(subset=['but'])

    features = [
        'ixg', 'hdcf', 'sog', 'atoi', 'l10_g', 'season_g', 
        'pdo', 'ga_g', 'cf_pct', 'hdca_g', 'pk_pct', 'rebounds', 'rush'
    ]

    for f in features:
        if df[f].dtype == 'object':
            df[f] = df[f].astype(str).str.replace(',', '.').astype(float)
        df[f] = pd.to_numeric(df[f], errors='coerce').fillna(0)

    X = df[features]
    y = df['but'].astype(int)

    y.loc[y > 0] = 1

    print(f"Dataset : {len(df)} echantillons ({sum(y)} Buts positifs, {len(df)-sum(y)} Nul)")

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    if HAS_SMOTE and sum(y_train) < len(y_train)/3:
        sm = SMOTE(random_state=42)
        X_train_res, y_train_res = sm.fit_resample(X_train, y_train)
    else:
        X_train_res, y_train_res = X_train, y_train

    # Calcul du ratio pour équilibrer les poids automatiquement
    balance_ratio = (len(y_train_res) - sum(y_train_res)) / max(1, sum(y_train_res))

    model = XGBClassifier(
        n_estimators=100,
        learning_rate=0.05,
        max_depth=4,
        eval_metric='logloss',
        scale_pos_weight=balance_ratio,
        random_state=42
    )
    model.fit(X_train_res, y_train_res)

    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)

    print("\n--- Évaluation du Modèle XGBoost V12 ---")
    print(f"Précision globale: {acc*100:.1f}%")
    print(f"F1-Score: {f1:.3f}")
    print(classification_report(y_test, y_pred))

    importance = model.feature_importances_
    feat_imp = pd.Series(importance, index=features).sort_values(ascending=False)
    print("\n--- Importance des variables ---")
    print(feat_imp.head(5))

    joblib.dump(model, MODEL_PATH)
    print(f"\nModèle XGBoost sauvegardé avec succès sous '{MODEL_PATH}'")
    print(f"predictor_v11.py l'utilisera désormais automatiquement.")

if __name__ == '__main__':
    main()
