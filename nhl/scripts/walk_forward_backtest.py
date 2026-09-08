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
    'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 'l10_g',
    'season_g', 'season_pts', 'ixg_x_hdcf', 'sog_x_atoi',
    'is_top6', 'prior_g60', 'prior_sog60', 'prior_sh_pct',
    'opp_xga_60', 'opp_hdca_60', 'opp_goalie_gsax_60', 'team_xg_60',
    'ixg_x_opp_xga', 'is_home', 'implied_prob', 'goalie_weakness'
]
FEATURES_AST = [
    'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 'l10_g', 'l10_a',
    'season_g', 'season_a', 'season_pts', 'ixg_x_hdcf', 'sog_x_atoi',
    'is_top6', 'prior_g60', 'prior_a60', 'prior_sog60',
    'opp_xga_60', 'opp_hdca_60', 'opp_goalie_gsax_60', 'team_xg_60',
    'ixg_x_opp_xga', 'is_home', 'implied_prob', 'goalie_weakness'
]

# Minimum de jours d'historique avant de commencer à prédire
MIN_TRAIN_SAMPLES = 200
# Fréquence de re-entraînement (jours)
RETRAIN_INTERVAL = 7


def load_all_data():
    """Charge le super-dataset historique (300K+ lignes) + les cotes réelles depuis sqlite."""
    # 1. Charger le super-dataset
    parquet_path = os.path.join(ROOT, "data", "historical_dataset.parquet")
    print(f"  [DATA] Chargement de {parquet_path}...")
    df = pd.read_parquet(parquet_path)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    # 2. Charger les cotes depuis la base de production
    conn = sqlite3.connect(DB_PATH)
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
            df_q = pd.read_sql(q, conn)
            df_q['date'] = pd.to_datetime(df_q['date']).dt.strftime('%Y-%m-%d')
            odds[cat] = df_q.drop_duplicates(subset=['date', 'joueur']).reset_index(drop=True)
        except Exception:
            odds[cat] = pd.DataFrame()

    try:
        df_players_cote = pd.read_sql(
            "SELECT date, joueur, cote FROM players WHERE cote IS NOT NULL AND cote > 1.05",
            conn
        )
        df_players_cote['date'] = pd.to_datetime(df_players_cote['date']).dt.strftime('%Y-%m-%d')
        df_players_cote = df_players_cote.drop_duplicates(subset=['date', 'joueur']).reset_index(drop=True)
    except Exception:
        df_players_cote = pd.DataFrame()
    conn.close()

    # 3. Unifier les cotes
    n_picks_but = len(odds.get('but', []))
    n_picks_ast = len(odds.get('ast', []))
    n_players_cote = len(df_players_cote)
    print(f"  [COTES] Source picks(but): {n_picks_but} | picks_assists: {n_picks_ast} | players.cote: {n_players_cote}")

    all_odds_parts = []
    for cat_key in ['but', 'ast']:
        if not odds.get(cat_key, pd.DataFrame()).empty:
            part = odds[cat_key][['date', 'joueur', 'cote']].copy()
            part['source'] = cat_key
            all_odds_parts.append(part)
    if not df_players_cote.empty:
        part = df_players_cote[['date', 'joueur', 'cote']].copy()
        part['source'] = 'players'
        all_odds_parts.append(part)

    if all_odds_parts:
        all_odds_unified = pd.concat(all_odds_parts, ignore_index=True)
        all_odds_unified = all_odds_unified.drop_duplicates(subset=['date', 'joueur'], keep='first')
    else:
        all_odds_unified = pd.DataFrame(columns=['date', 'joueur', 'cote', 'source'])

    print(f"  [COTES] Total cotes unifiées (dédupliquées): {len(all_odds_unified)}")

    # 4. Injecter implied_prob dans df (pour les features du modèle)
    df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')
    df = df.merge(
        all_odds_unified[['date', 'joueur', 'cote']].rename(columns={'date': 'date_str', 'cote': 'cote_merged'}),
        on=['date_str', 'joueur'], how='left'
    )
    
    if 'cote' in df.columns:
        df['cote_final'] = df['cote_merged'].combine_first(pd.to_numeric(df['cote'], errors='coerce'))
    else:
        df['cote_final'] = df['cote_merged']
        
    df['implied_prob'] = np.where(
        (df['cote_final'] > 1.05) & (df['cote_final'].notna()),
        1.0 / df['cote_final'], 0.0
    )
    if 'goalie_weakness' not in df.columns:
        df['goalie_weakness'] = 0.08

    # Nettoyage des positions
    if 'position' not in df.columns or df['position'].isnull().all():
        skaters_csv = os.path.join(ROOT, "data", "skaters.csv")
        if os.path.exists(skaters_csv):
            df_sk = pd.read_csv(skaters_csv, usecols=['name', 'position']).drop_duplicates(subset=['name'])
            df = df.merge(df_sk.rename(columns={'name': 'joueur'}), on='joueur', how='left')
        else:
            df['position'] = 'F'

    return df, odds, all_odds_unified


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


def walk_forward(df, all_odds_unified, features, target_col, cat_name,
                 ev_threshold=0.05, use_ensemble: bool = False, adaptive_ev: bool = False):
    """Exécute le walk-forward backtest pour un marché.

    Args:
        df: DataFrame complet trié par date.
        all_odds_unified: DataFrame unifié de toutes les cotes (date en string YYYY-MM-DD).
        features: Liste de features.
        target_col: Colonne cible (ex: 'target_but').
        cat_name: Nom du marché ('but' ou 'ast').
        ev_threshold: Seuil EV minimum de base (default 5%).
        use_ensemble: Si True, utilise NHLEnsembleClassifier avec Optuna.
        adaptive_ev: Si True, applique les seuils EV adaptatifs selon la cote.

    Returns:
        pd.DataFrame des résultats de chaque pari simulé.
    """
    dates_with_odds_str = all_odds_unified['date'].unique()
    dates_with_odds = sorted(pd.to_datetime(dates_with_odds_str).date)
    # Filtrer pour ne garder que les dates où on a la data ET les cotes
    all_dates = sorted(df['date'].dt.date.unique())
    dates = [d for d in all_dates if d in dates_with_odds]
    results = []

    model_type_str = "MULTI-BOOSTING ENSEMBLE" if use_ensemble else "XGBOOST CALIBRÉ"
    ev_mode_str = "ADAPTATIF" if adaptive_ev else f"FIXE {ev_threshold*100:.0f}%"
    print(f"\n{'=' * 60}")
    print(f" WALK-FORWARD : {cat_name.upper()} ({len(dates)} jours) — [{model_type_str} | EV {ev_mode_str}]")
    print(f"{'=' * 60}")

    current_model = None
    last_train_date = None
    n_retrains = 0
    n_with_odds = 0
    n_ev_passed = 0
    n_ev_rejected = 0

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
                        base, method='sigmoid', cv=tscv
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

        # Matching avec les cotes réelles (format YYYY-MM-DD string)
        day_str = str(day)  # datetime.date -> 'YYYY-MM-DD'
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

            # Chercher la cote dans le DataFrame unifié
            odds_match = all_odds_unified[
                (all_odds_unified['date'] == day_str)
                & (all_odds_unified['joueur'] == joueur)
            ]

            if odds_match.empty:
                continue

            n_with_odds += 1
            cote = float(odds_match.iloc[0]['cote'])
            ev = proba * cote - 1.0

            required_ev = get_adaptive_ev_threshold(cote, ev_threshold) if adaptive_ev else ev_threshold

            if ev >= required_ev:
                mise = kelly_eighth(proba, cote)
                won = result_int > 0
                gain = (cote * mise - mise) if won else -mise
                n_ev_passed += 1

                results.append({
                    'date': day, 'joueur': joueur, 'cat': cat_name,
                    'proba': proba, 'cote': cote, 'ev': ev,
                    'mise': mise, 'gain': gain, 'won': won,
                })
            else:
                n_ev_rejected += 1

    print(f"  Re-entraînements: {n_retrains}")
    print(f"  Joueurs avec cote trouvée: {n_with_odds}")
    print(f"  Passé filtre EV: {n_ev_passed} | Rejeté EV: {n_ev_rejected}")
    return pd.DataFrame(results)


def run_full_backtest(use_ensemble: bool = False, adaptive_ev: bool = False):
    """Lance le walk-forward complet sur tous les marchés actifs."""
    df, odds, all_odds_unified = load_all_data()
    print(f"Données chargées: {len(df)} joueurs-matchs")

    all_results = []

    configs = [
        ('but', FEATURES_BUT, 'target_but'),
        ('ast', FEATURES_AST, 'target_ast'),
    ]

    for cat, features, target_col in configs:
        # Règle de production : les défenseurs sont interdits sur les Buteurs (market_filter.py)
        df_cat = df[df['position'] != 'D'].copy() if cat == 'but' else df

        results = walk_forward(
            df_cat, all_odds_unified, features, target_col, cat,
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

    # --- RAPPORT PAR JOUR DE MATCH ---
    print(f"\n  {'-' * 50}")
    print(f"  DÉTAIL PAR JOUR DE MATCH")
    print(f"  {'-' * 50}")
    print(f"  {'Date':<12} {'Paris':>5} {'W':>3} {'L':>3} {'Mise':>6} {'P&L':>8} {'ROI':>7} {'Cumul':>8}")
    print(f"  {'-'*58}")
    
    cumul = 0.0
    for date_val in sorted(df_all['date'].unique()):
        day_df = df_all[df_all['date'] == date_val]
        n_day = len(day_df)
        w_day = int(day_df['won'].sum())
        l_day = n_day - w_day
        mise_day = day_df['mise'].sum()
        gain_day = day_df['gain'].sum()
        roi_day = (gain_day / mise_day * 100) if mise_day > 0 else 0
        cumul += gain_day
        date_str = str(date_val)
        print(f"  {date_str:<12} {n_day:>5} {w_day:>3} {l_day:>3} {mise_day:>6.1f} {gain_day:>+8.2f} {roi_day:>+6.1f}% {cumul:>+8.2f}")


if __name__ == "__main__":
    use_ens = "--ensemble" in sys.argv
    adaptive = "--adaptive-ev" in sys.argv
    run_full_backtest(use_ensemble=use_ens, adaptive_ev=adaptive)
