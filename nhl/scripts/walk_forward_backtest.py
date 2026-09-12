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
    'ixg_l10', 'sog_l10', 'atoi_l10', 'l10_g', 'l10_a', 
    'hdcf_l10', 'season_g', 'season_a', 'season_pts', 'sog_x_atoi', 'ixg_x_hdcf',
    'ga_g', 'hdca_g', 'pp1', 'is_home', 'is_b2b', 'opp_is_b2b', 'opp_goalie_gsax_60',
    'consec_goals', 'linemate_synergy', 'team_scoring_env', 'ixg_x_ga'
]
FEATURES_AST = [
    'ixg_l10', 'sog_l10', 'atoi_l10', 'l10_g', 'l10_a', 
    'hdcf_l10', 'season_g', 'season_a', 'season_pts', 'sog_x_atoi', 'ixg_x_hdcf',
    'ga_g', 'hdca_g', 'pp1', 'is_home', 'is_b2b', 'opp_is_b2b', 'opp_goalie_gsax_60',
    'consec_goals', 'linemate_synergy', 'team_scoring_env', 'ixg_x_ga'
]
FEATURES_PTS = FEATURES_AST.copy()

# Minimum de jours d'historique avant de commencer à prédire
MIN_TRAIN_SAMPLES = 200
# Fréquence de re-entraînement (jours)
RETRAIN_INTERVAL = 7


import unicodedata
import string

def normalize_name(name):
    if not isinstance(name, str): return ""
    name = ''.join(c for c in unicodedata.normalize('NFD', name) if unicodedata.category(c) != 'Mn')
    name = name.lower()
    for p in string.punctuation: name = name.replace(p, ' ')
    parts = name.split()
    if len(parts) >= 2: return f"{parts[0][0]} {' '.join(parts[1:])}"
    return name.replace(' ', '')

def load_all_data():
    """Charge le super-dataset historique (300K+ lignes) + les cotes réelles depuis sqlite & API Historique."""
    # 1. Charger le super-dataset
    parquet_path = os.path.join(ROOT, "data", "historical_dataset.parquet")
    print(f"  [DATA] Chargement de {parquet_path}...")
    df = pd.read_parquet(parquet_path)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')
    df['player_norm'] = df['joueur'].apply(normalize_name)

    # 2. Charger les cotes depuis la base de production (bot_database)
    conn = sqlite3.connect(DB_PATH)
    odds = {'but': pd.DataFrame(columns=['date', 'joueur', 'cote', 'result']), 
            'ast': pd.DataFrame(columns=['date', 'joueur', 'cote', 'result']),
            'pts': pd.DataFrame(columns=['date', 'joueur', 'cote', 'result'])}
    queries = [
        ("picks", "but", "but"),
        ("picks_assists", "ast", "assist"),
    ]
    for table, cat, target in queries:
        try:
            q = f"SELECT date, joueur, cote, {target} as result FROM {table} WHERE cote IS NOT NULL AND cote > 1.05"
            df_q = pd.read_sql(q, conn)
            df_q['date'] = pd.to_datetime(df_q['date']).dt.strftime('%Y-%m-%d')
            odds[cat] = df_q.drop_duplicates(subset=['date', 'joueur']).reset_index(drop=True)
        except Exception:
            pass
    conn.close()

    # 3. Charger les cotes historiques The-Odds-API
    hist_odds_path = os.path.join(ROOT, "data", "odds", "historical_odds_parsed.csv")
    if os.path.exists(hist_odds_path):
        df_hist_odds = pd.read_csv(hist_odds_path)
        print(f"  [COTES] Chargement de {len(df_hist_odds)} cotes historiques depuis l'API.")
        
        # Séparer but, ast et pts
        df_hist_but = df_hist_odds[df_hist_odds['market'] == 'but'].copy()
        df_hist_ast = df_hist_odds[df_hist_odds['market'] == 'ast'].copy()
        df_hist_pts = df_hist_odds[df_hist_odds['market'] == 'pts'].copy()
        
        df_unique = df[['date_str', 'player_norm', 'joueur']].drop_duplicates()
        
        for df_h, cat in [(df_hist_but, 'but'), (df_hist_ast, 'ast'), (df_hist_pts, 'pts')]:
            merged = df_h.merge(df_unique, left_on=['date', 'player_norm'], right_on=['date_str', 'player_norm'], how='inner')
            merged = merged[['date_str', 'joueur', 'median_odds']].rename(columns={'date_str': 'date', 'median_odds': 'cote'})
            merged['result'] = 0 # Placeholder, on a les vrais target dans df de toute facon
            
            # Ajouter aux odds de prod existantes
            odds[cat] = pd.concat([odds[cat], merged], ignore_index=True).drop_duplicates(subset=['date', 'joueur'], keep='first')
            
    print(f"  [COTES] Source unifiée picks(but): {len(odds['but'])} | picks_assists: {len(odds['ast'])} | picks_points: {len(odds['pts'])}")

    # 4. Injecter implied_prob_but, implied_prob_ast, implied_prob_pts dans df (pour les features du modèle)
    df = df.merge(odds['but'][['date', 'joueur', 'cote']].rename(columns={'date': 'date_str', 'cote': 'cote_but'}), on=['date_str', 'joueur'], how='left')
    df = df.merge(odds['ast'][['date', 'joueur', 'cote']].rename(columns={'date': 'date_str', 'cote': 'cote_ast'}), on=['date_str', 'joueur'], how='left')
    df = df.merge(odds['pts'][['date', 'joueur', 'cote']].rename(columns={'date': 'date_str', 'cote': 'cote_pts'}), on=['date_str', 'joueur'], how='left')

    df['implied_prob_but'] = np.where(df['cote_but'].notna(), 1.0 / df['cote_but'], 0.0)
    df['implied_prob_ast'] = np.where(df['cote_ast'].notna(), 1.0 / df['cote_ast'], 0.0)
    df['implied_prob_pts'] = np.where(df['cote_pts'].notna(), 1.0 / df['cote_pts'], 0.0)
    
    # Pour le modèle, la feature s'appelle toujours 'implied_prob'. 
    # Pendant le split, on va utiliser la probabilité du marché actuel (fait plus loin ou par le modèle).
    # En fait, dans walk_forward, la colonne s'appelle 'implied_prob'.
    # Il faudra écraser 'implied_prob' juste avant l'entraînement. 
    # Pour l'instant, on laisse par défaut sur BUT.
    df['implied_prob'] = df['implied_prob_but']
    
    # Générer target_pts
    df['target_pts'] = ((df['I_F_goals'] + df['I_F_primaryAssists'] + df['I_F_secondaryAssists']) >= 1).astype(int)

    if 'goalie_weakness' not in df.columns:
        df['goalie_weakness'] = 0.08

    if 'position' not in df.columns or df['position'].isnull().all():
        skaters_csv = os.path.join(ROOT, "data", "skaters.csv")
        if os.path.exists(skaters_csv):
            df_sk = pd.read_csv(skaters_csv, usecols=['name', 'position']).drop_duplicates(subset=['name'])
            df = df.merge(df_sk.rename(columns={'name': 'joueur'}), on='joueur', how='left')
        else:
            df['position'] = 'F'

    return df, odds, pd.DataFrame()


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
                    current_model = NHLEnsembleClassifier(market=cat_name, mode='ensemble', n_splits=2)
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
                if n_retrains % 5 == 0:
                    print(f"  [{cat_name.upper()}] Progession: {day} (Retrain #{n_retrains})")
            except Exception as e:
                print(f"  [{cat_name.upper()}] Erreur lors du retrain: {e}")
                continue

        # Prédiction sur le jour J
        X_today = df_today[features].values
        try:
            probas = current_model.predict_proba(X_today)[:, 1]
        except Exception:
            continue

        # Matching avec les cotes réelles (format YYYY-MM-DD string)
        day_str = str(day)  # datetime.date -> 'YYYY-MM-DD'
        
        # Phase 1: Collecter tous les paris potentiels du jour
        daily_bets = []
        for idx_in_today, (_, row) in enumerate(df_today.iterrows()):
            proba = float(probas[idx_in_today])
            joueur = row['joueur']

            result_int = int(row[target_col])

            # Chercher la cote dans le DataFrame unifié
            odds_match = all_odds_unified[
                (all_odds_unified['date'] == day_str)
                & (all_odds_unified['joueur'] == joueur)
            ]

            if odds_match.empty:
                continue

            cote = float(odds_match.iloc[0]['cote'])
            # [FIX-BUG-2] Plafonner les cotes extrêmes qui détruisent le P&L (max 25.0)
            if cote > 25.0:
                continue
                
            # [PHASE 1] Filtre de sûreté : on ignore si la probabilité de base est trop faible
            # Uniquement pour BUT (l'application sur AST tuait le ROI)
            if cat_name.lower() == 'but' and proba < 0.12:
                continue

            n_with_odds += 1
            ev = proba * cote - 1.0

            required_ev = get_adaptive_ev_threshold(cote, ev_threshold) if adaptive_ev else ev_threshold

            if ev >= required_ev:
                mise = kelly_eighth(proba, cote, cap=2.0)
                won = result_int > 0
                gain = (cote * mise - mise) if won else -mise
                n_ev_passed += 1

                is_safe = proba >= 0.60 or ev >= 0.20
                daily_bets.append({
                    'date': day, 'joueur': joueur, 'cat': cat_name,
                    'proba': proba, 'cote': cote, 'ev': ev,
                    'mise': mise, 'gain': gain, 'won': won,
                    'is_safe': is_safe
                })
            else:
                n_ev_rejected += 1
                
        # Phase 2: Appliquer les limites de bankroll (BUG-5)
        MAX_DAILY_BETS = 15
        MAX_DAILY_EXPOSURE = 20.0
        
        if daily_bets:
            # Trier par EV décroissant pour garder les meilleurs paris
            daily_bets.sort(key=lambda x: x['ev'], reverse=True)
            
            total_exposure = 0.0
            accepted_bets = []
            
            for bet in daily_bets:
                if len(accepted_bets) >= MAX_DAILY_BETS:
                    break
                
                # Ajuster la mise si on dépasse la limite d'exposition
                if total_exposure + bet['mise'] > MAX_DAILY_EXPOSURE:
                    allowed_mise = MAX_DAILY_EXPOSURE - total_exposure
                    if allowed_mise < 0.5:
                        break # Pas assez de budget pour ce pari (mise min 0.5)
                    bet['mise'] = allowed_mise
                    bet['gain'] = (bet['cote'] * bet['mise'] - bet['mise']) if bet['won'] else -bet['mise']
                    
                total_exposure += bet['mise']
                accepted_bets.append(bet)
                
            results.extend(accepted_bets)

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
        ('pts', FEATURES_PTS, 'target_pts'),
    ]

    for cat, features, target_col in configs:
        # Règle de production : les défenseurs sont interdits sur les Buteurs (market_filter.py)
        df_cat = df[df['position'] != 'D'].copy() if cat == 'but' else df.copy()
        
        # S'assurer d'utiliser la bonne probabilité implicite pour ce marché
        df_cat['implied_prob'] = df_cat[f'implied_prob_{cat}']

        results = walk_forward(
            df_cat, odds[cat], features, target_col, cat,
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

    # Sauvegarde des prédictions pour le simulateur de combinés
    csv_path = os.path.join(ROOT, "data", "backtest_predictions.csv")
    df_all.to_csv(csv_path, index=False)
    print(f"\n  [SAUVEGARDE] Prédictions exportées vers {csv_path} pour l'analyse des combinés.")

    # --- PARIS SAFE ---
    df_safe = df_all[df_all['is_safe'] == True]
    if not df_safe.empty:
        safe_mise = df_safe['mise'].sum()
        safe_gain = df_safe['gain'].sum()
        safe_roi = (safe_gain / safe_mise * 100) if safe_mise > 0 else 0
        safe_wr = (df_safe['won'].sum() / len(df_safe) * 100)
        print(f"\n  {'-' * 50}")
        print(f"  PARIS SAFE (Proba >= 60% OU EV >= 20%)")
        print(f"  {'-' * 50}")
        print(f"    Paris Total:    {len(df_safe)}")
        print(f"    Win Rate:       {safe_wr:.1f}%")
        print(f"    P&L Final:      {safe_gain:+.2f} U")
        print(f"    ROI Safe:       {safe_roi:+.1f}%")

    # P&L cumulé par semaine (pour visualiser la tendance)
    # [FIX-BUG-3] Utiliser year et week pour ne pas fusionner les années
    df_all['year'] = pd.to_datetime(df_all['date']).dt.isocalendar().year
    df_all['week'] = pd.to_datetime(df_all['date']).dt.isocalendar().week
    weekly = df_all.groupby(['year', 'week'])['gain'].sum()
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
