"""
scripts/walk_forward_backtest.py — Walk-Forward Backtest rigoureux.

Simule jour par jour exactement ce que le bot aurait fait :
1. Pour chaque jour J, entraîner le modèle sur les données [0, J-1]
2. Prédire les probabilités pour le jour J
3. Appliquer les filtres EV et le Kelly 1/8
4. Logger le P&L quotidien
5. Avancer au jour J+1

C'est la SEULE méthode valide pour estimer le ROI futur.

Usage:
    python nhl/scripts/walk_forward_backtest.py
"""
import sqlite3
import pandas as pd
import numpy as np
import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from datetime import timedelta
from xgboost import XGBClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, os.path.dirname(ROOT_DIR))
from nhl.core.ensemble_model import NHLEnsembleClassifier
from nhl.core.market_filter import get_adaptive_ev_threshold

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "bot_database.db")

FEATURES_BUT = [
    'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10',
    'season_g', 'season_pts',
    'ga_g', 'hdca_g', 'pp1', 'is_home',
    'is_b2b', 'opp_is_b2b', 'consec_goals',
    'ixg_x_hdcf', 'sog_x_atoi', 'ixg_x_ga',
    'is_top6', 'linemate_synergy', 'team_scoring_env'
]
FEATURES_AST = FEATURES_BUT + ['season_a']

# Minimum de jours d'historique avant de commencer à prédire
MIN_TRAIN_SAMPLES = 200
# Fréquence de re-entraînement (jours)
RETRAIN_INTERVAL = 7


def load_all_data():
    """Charge les données joueurs + cotes réelles pour le walk-forward.

    Returns:
        Tuple (df_players, dict_odds) avec les données préparées.
    """
    conn = sqlite3.connect(DB_PATH)

    # Joueurs évalués avec résultats
    df = pd.read_sql(
        "SELECT * FROM players WHERE but IS NOT NULL AND but != ''", conn
    )

    # Cotes réelles des picks
    odds = {}
    queries = [
        ("picks", "but", "but"),
        ("picks_assists", "ast", "assist"),
    ]
    for table, cat, target in queries:
        try:
            q = (
                f"SELECT date, joueur, cote, {target} as result "
                f"FROM {table} WHERE cote IS NOT NULL AND cote > 1.05"
            )
            odds[cat] = pd.read_sql(q, conn)
        except Exception:
            odds[cat] = pd.DataFrame()

    conn.close()

    # Préparation features
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    for col in ['ixg', 'hdcf', 'sog', 'atoi']:
        df[f'{col}_l10'] = pd.to_numeric(
            df[col], errors='coerce'
        ).fillna(0)
    for col in ['season_g', 'season_a', 'season_pts', 'ga_g', 'hdca_g']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

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

    df['ixg_x_hdcf'] = df['ixg_l10'] * df['hdcf_l10']
    df['sog_x_atoi'] = df['sog_l10'] * df['atoi_l10']
    df['ixg_x_ga'] = df['ixg_l10'] * df['ga_g']

    df['is_top6'] = ((df['atoi_l10'] >= 17.0) | (df['pp1'] == 1)).astype(int)
    df['linemate_synergy'] = (df['season_g'] + df['season_a']) * df['pp1']
    df['team_scoring_env'] = df['ga_g'] * df['hdca_g']

    df['target_but'] = (
        pd.to_numeric(df['but'], errors='coerce').fillna(0) > 0
    ).astype(int)
    df['target_ast'] = (
        pd.to_numeric(df['assist'], errors='coerce').fillna(0) > 0
    ).astype(int)

    return df, odds


def kelly_eighth(proba: float, cote: float, cap: float = 2.0) -> float:
    """Calcule le Kelly 1/8ème (identique au bot de production).

    Args:
        proba: Probabilité calibrée de l'événement.
        cote: Cote décimale du bookmaker.
        cap: Mise maximale en unités.

    Returns:
        Mise recommandée en unités (arrondie à 0.5).
    """
    if not cote or cote <= 1.05:
        return 0.0
    b = cote - 1.0
    f = (proba * b - (1 - proba)) / b
    if f <= 0:
        return 0.0
    units = round(f / 8.0 * 100 * 2) / 2
    return max(0.5, min(units, cap))


def walk_forward(df, odds_df, features, target_col, cat_name,
                 ev_threshold=0.05, use_ensemble: bool = False, adaptive_ev: bool = False):
    """Exécute le walk-forward backtest pour un marché.

    Args:
        df: DataFrame complet trié par date.
        odds_df: DataFrame des cotes réelles.
        features: Liste de features.
        target_col: Colonne cible (ex: 'target_but').
        cat_name: Nom du marché ('but' ou 'ast').
        ev_threshold: Seuil EV minimum de base (default 5%).
        use_ensemble: Si True, utilise NHLEnsembleClassifier avec Optuna.
        adaptive_ev: Si True, applique les seuils EV adaptatifs selon la cote.

    Returns:
        pd.DataFrame des résultats de chaque pari simulé.
    """
    dates = sorted(df['date'].dt.date.unique())
    results = []

    model_type_str = "MULTI-BOOSTING ENSEMBLE" if use_ensemble else "XGBOOST CALIBRÉ"
    ev_mode_str = "ADAPTATIF" if adaptive_ev else f"FIXE {ev_threshold*100:.0f}%"
    print(f"\n{'=' * 60}")
    print(f" WALK-FORWARD : {cat_name.upper()} ({len(dates)} jours) — [{model_type_str} | EV {ev_mode_str}]")
    print(f"{'=' * 60}")

    current_model = None
    last_train_date = None
    n_retrains = 0

    for day in dates:
        df_past = df[df['date'].dt.date < day]
        df_today = df[df['date'].dt.date == day]

        if df_today.empty or len(df_past) < MIN_TRAIN_SAMPLES:
            continue

        # Re-entraînement périodique
        days_since_train = (
            (day - last_train_date).days if last_train_date else 999
        )
        if current_model is None or days_since_train >= RETRAIN_INTERVAL:
            X_past = df_past[features].values
            y_past = df_past[target_col].values

            if sum(y_past) < 10:
                continue

            try:
                if use_ensemble:
                    current_model = NHLEnsembleClassifier(market=cat_name, mode='ensemble', n_splits=3)
                    current_model.fit(X_past, y_past)
                else:
                    scale_pos = (len(y_past) - sum(y_past)) / max(1, sum(y_past))
                    base = XGBClassifier(
                        n_estimators=100, max_depth=3, learning_rate=0.05,
                        scale_pos_weight=scale_pos, eval_metric='logloss',
                        random_state=42, subsample=0.8, colsample_bytree=0.8,
                    )
                    n_splits = min(3, max(2, len(y_past) // 200))
                    tscv = TimeSeriesSplit(n_splits=n_splits)
                    current_model = CalibratedClassifierCV(
                        base, method='isotonic', cv=tscv
                    )
                    current_model.fit(X_past, y_past)

                last_train_date = day
                n_retrains += 1
            except Exception:
                continue

        # Prédiction sur le jour J
        X_today = df_today[features].values
        try:
            probas = current_model.predict_proba(X_today)[:, 1]
        except Exception:
            continue

        # Matching avec les cotes réelles
        if odds_df.empty:
            continue

        day_str = str(day)
        result_col = 'assist' if 'ast' in target_col else 'but'

        for idx_in_today, (_, row) in enumerate(df_today.iterrows()):
            proba = float(probas[idx_in_today])
            joueur = row['joueur']

            result_val = pd.to_numeric(
                row.get(result_col, 0), errors='coerce'
            )
            if pd.isna(result_val):
                continue
            result_int = int(result_val > 0)

            # Chercher la cote réelle
            odds_match = odds_df[
                (odds_df['date'] == day_str)
                & (odds_df['joueur'] == joueur)
            ]

            if odds_match.empty:
                continue

            cote = float(odds_match.iloc[0]['cote'])
            ev = proba * cote - 1.0

            required_ev = get_adaptive_ev_threshold(cote, ev_threshold) if adaptive_ev else ev_threshold

            if ev >= required_ev:
                mise = kelly_eighth(proba, cote)
                won = result_int > 0
                gain = (cote * mise - mise) if won else -mise

                results.append({
                    'date': day, 'joueur': joueur, 'cat': cat_name,
                    'proba': proba, 'cote': cote, 'ev': ev,
                    'mise': mise, 'gain': gain, 'won': won,
                })

    print(f"  Re-entraînements: {n_retrains}")
    return pd.DataFrame(results)


def run_full_backtest(use_ensemble: bool = False, adaptive_ev: bool = False):
    """Lance le walk-forward complet sur tous les marchés actifs."""
    df, odds = load_all_data()
    print(f"Données chargées: {len(df)} joueurs-matchs")

    all_results = []

    configs = [
        ('but', FEATURES_BUT, 'target_but'),
        ('ast', FEATURES_AST, 'target_ast'),
    ]

    for cat, features, target_col in configs:
        odds_df = odds.get(cat, pd.DataFrame())
        if odds_df.empty:
            print(f"\n[{cat.upper()}] Pas de cotes historiques. Skipping.")
            continue

        results = walk_forward(
            df, odds_df, features, target_col, cat,
            use_ensemble=use_ensemble, adaptive_ev=adaptive_ev
        )
        if not results.empty:
            all_results.append(results)

    if not all_results:
        print("\nAucun résultat. Vérifiez vos données (cotes dans la DB).")
        return

    df_all = pd.concat(all_results, ignore_index=True)

    # --- RAPPORT FINAL ---
    print(f"\n{'=' * 70}")
    print(" RÉSULTATS WALK-FORWARD (100% Out-of-Sample)")
    print(f"{'=' * 70}")

    for cat in df_all['cat'].unique():
        cat_df = df_all[df_all['cat'] == cat]
        n = len(cat_df)
        wins = int(cat_df['won'].sum())
        total_mise = cat_df['mise'].sum()
        total_gain = cat_df['gain'].sum()
        roi = (total_gain / total_mise * 100) if total_mise > 0 else 0
        wr = (wins / n * 100) if n > 0 else 0
        ev_mean = cat_df['ev'].mean() * 100
        cote_mean = cat_df['cote'].mean()

        print(f"\n  [{cat.upper()}]")
        print(f"    Paris:        {n}")
        print(f"    Win Rate:     {wr:.1f}%")
        print(f"    Cote Moy:     {cote_mean:.2f}")
        print(f"    EV Moyenne:   {ev_mean:+.1f}%")
        print(f"    Mise Totale:  {total_mise:.1f} U")
        print(f"    Profit:       {total_gain:+.2f} U")
        print(f"    ROI:          {roi:+.1f}%")

    # --- MÉTRIQUES DE RISQUE ---
    df_all = df_all.sort_values('date')
    df_all['cumul_pnl'] = df_all['gain'].cumsum()
    df_all['max_pnl'] = df_all['cumul_pnl'].cummax()
    df_all['drawdown'] = df_all['cumul_pnl'] - df_all['max_pnl']

    total_mise = df_all['mise'].sum()
    total_gain = df_all['gain'].sum()
    global_roi = (total_gain / total_mise * 100) if total_mise > 0 else 0

    gain_std = df_all['gain'].std()
    sharpe = (
        df_all['gain'].mean() / gain_std if gain_std > 0.01 else 0
    )

    print(f"\n  {'-' * 50}")
    print(f"  GLOBAL (tous marchés confondus)")
    print(f"  {'-' * 50}")
    print(f"    Paris Total:    {len(df_all)}")
    print(f"    P&L Final:      {df_all['cumul_pnl'].iloc[-1]:+.2f} U")
    print(f"    ROI Global:     {global_roi:+.1f}%")
    print(f"    Drawdown Max:   {df_all['drawdown'].min():.2f} U")
    print(f"    Sharpe Ratio:   {sharpe:.3f}")

    # P&L cumulé par semaine (pour visualiser la tendance)
    df_all['week'] = pd.to_datetime(
        df_all['date']
    ).dt.isocalendar().week.astype(int)
    weekly = df_all.groupby('week')['gain'].sum()
    winning_weeks = (weekly > 0).sum()
    total_weeks = len(weekly)
    print(f"    Semaines +:     {winning_weeks}/{total_weeks} "
          f"({winning_weeks / max(1, total_weeks) * 100:.0f}%)")


if __name__ == "__main__":
    use_ens = "--ensemble" in sys.argv
    adaptive = "--adaptive-ev" in sys.argv
    run_full_backtest(use_ensemble=use_ens, adaptive_ev=adaptive)
