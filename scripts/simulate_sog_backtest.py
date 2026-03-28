"""
simulate_sog_backtest.py — Backtest SOG (Shots on Goal >= 3)
Objectif : Trouver un score SOG fiable pour prédire si un joueur va tirer 3+ tirs cadrés.
"""
import sys, os, math, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from collections import defaultdict, deque
from datetime import datetime, timedelta

CSV_PATH = "./stats/skaters_all.csv"
SOG_TARGET = 3  # Over 2.5 tirs cadrés
ODDS_AVG_SOG = 1.85  # Cote moyenne du marché SOG over 2.5
STAKE = 1.0
MIN_ATOI = 16.0

USECOLS = [
    'playerId', 'name', 'gameId', 'season', 'playerTeam', 'opposingTeam',
    'home_or_away', 'gameDate', 'position', 'situation', 'icetime',
    'I_F_xGoals', 'I_F_shotsOnGoal', 'I_F_goals', 'I_F_highDangerShots',
    'I_F_rebounds', 'onIce_corsiPercentage',
    'OnIce_F_goals', 'OnIce_F_shotsOnGoal',
    'OnIce_F_highDangerShots', 'OnIce_A_highDangerShots',
]


def calculate_sog_score(sog, atoi, ixg, hdcf, season_g, is_pp1, is_home, sa_g):
    """Score heuristique pour prédire les SOG >= 3."""
    score = 0.0

    # Feature #1 : SOG moyen sur L10 (poids dominant)
    if sog >= 4.0:   score += 4.0
    elif sog >= 3.5: score += 3.0
    elif sog >= 3.0: score += 2.0
    elif sog >= 2.5: score += 1.0
    elif sog >= 2.0: score += 0.5
    else:            score -= 1.0

    # Feature #2 : ATOI (plus de temps = plus de tirs)
    if atoi >= 20.0:   score += 2.0
    elif atoi >= 18.0: score += 1.0
    elif atoi >= 16.0: score += 0.5

    # Feature #3 : ixG (qualité des chances)
    if ixg >= 0.50:   score += 1.5
    elif ixg >= 0.35: score += 1.0
    elif ixg >= 0.25: score += 0.5

    # Feature #4 : HDCF (volume de tirs dangereux)
    if hdcf >= 2.5:   score += 1.0
    elif hdcf >= 2.0: score += 0.5

    # Feature #5 : PP1
    if is_pp1: score += 1.5

    # Feature #6 : Home advantage (léger)
    if is_home: score += 0.25

    # Feature #7 : SA/G adverse (gardien sollicité = plus de SOG concédés)
    if sa_g >= 32.0:   score += 1.0
    elif sa_g >= 30.0: score += 0.5

    return score


def main():
    t0 = time.time()
    print("=" * 60)
    print("  BACKTEST SOG — Shots on Goal >= 3")
    print("=" * 60)

    # ── 1. Chargement ─────────────────────────────────────────────
    print("\n[1/5] Chargement...", flush=True)
    chunks_all = []
    total = 0

    for chunk in pd.read_csv(CSV_PATH, chunksize=100_000, usecols=USECOLS, low_memory=False):
        chunk = chunk[~chunk['position'].isin(['G'])]
        chunk['gameDate'] = chunk['gameDate'].astype(str)
        c_all = chunk[chunk['situation'] == 'all'].copy()
        chunks_all.append(c_all)
        total += len(c_all)
        print(f"  ... {total:,}", end='\r', flush=True)

    df = pd.concat(chunks_all, ignore_index=True)
    del chunks_all
    df = df.sort_values(['gameDate', 'gameId']).reset_index(drop=True)
    n_games = df['gameId'].nunique()
    print(f"\n  {len(df):,} lignes | {n_games:,} matchs")

    # ── 2. Rolling stats ──────────────────────────────────────────
    print("\n[2/5] Calcul des rolling stats...", flush=True)

    player_history = defaultdict(lambda: deque(maxlen=10))
    player_season = defaultdict(lambda: {'goals': 0, 'gp': 0, 'season': None})
    team_sa_history = defaultdict(lambda: deque(maxlen=10))  # Shots Against par match

    all_entries = []
    game_dates = df.groupby('gameId').first()['gameDate'].to_dict()
    games_processed = 0

    for game_id, game_df in df.groupby('gameId', sort=False):
        games_processed += 1
        if games_processed % 1000 == 0:
            print(f"  {games_processed:,} matchs...", end='\r', flush=True)

        game_date = game_dates.get(game_id, '')
        season = game_df.iloc[0]['season'] if 'season' in game_df.columns else 2024
        teams_in_game = game_df['playerTeam'].unique()

        # PP1 detection
        team_ixg_candidates = defaultdict(list)
        player_data = []

        for _, row in game_df.iterrows():
            pid = row['playerId']
            pos = row['position']
            team = row['playerTeam']

            if pos in ('D', 'LD', 'RD'):
                continue

            ps = player_season[pid]
            if ps['season'] != season:
                ps['goals'] = 0
                ps['gp'] = 0
                ps['season'] = season

            history = player_history[pid]

            if len(history) < 5:
                icetime_min = row['icetime'] / 60.0 if row['icetime'] > 0 else 0
                history.append({
                    'ixg': row['I_F_xGoals'] or 0,
                    'sog': row['I_F_shotsOnGoal'] or 0,
                    'hdcf': row['I_F_highDangerShots'] or 0,
                    'goals': row['I_F_goals'] or 0,
                    'icetime': icetime_min,
                })
                ps['goals'] += (row['I_F_goals'] or 0)
                ps['gp'] += 1
                continue

            n_hist = len(history)
            l10_ixg = sum(h['ixg'] for h in history) / n_hist
            l10_sog = sum(h['sog'] for h in history) / n_hist
            l10_hdcf = sum(h['hdcf'] for h in history) / n_hist
            l10_atoi = sum(h['icetime'] for h in history) / n_hist
            season_g = ps['goals'] / max(ps['gp'], 1)

            team_ixg_candidates[team].append((pid, l10_ixg))

            player_data.append({
                'pid': pid, 'name': row['name'], 'team': team,
                'opp': row['opposingTeam'],
                'is_home': row['home_or_away'] == 'HOME',
                'row': row,
                'l10_ixg': l10_ixg, 'l10_sog': l10_sog, 'l10_hdcf': l10_hdcf,
                'l10_atoi': l10_atoi, 'season_g': season_g,
            })

        # PP1
        pp1_pids = set()
        for team, cands in team_ixg_candidates.items():
            for pid_pp, _ in sorted(cands, key=lambda x: x[1], reverse=True)[:3]:
                pp1_pids.add(pid_pp)

        # Scoring
        for pd_e in player_data:
            pid = pd_e['pid']
            row = pd_e['row']
            l10_atoi = pd_e['l10_atoi']
            season_g = pd_e['season_g']

            if season_g < 0.10 or l10_atoi < MIN_ATOI:
                icetime_min = row['icetime'] / 60.0 if row['icetime'] > 0 else 0
                player_history[pid].append({
                    'ixg': row['I_F_xGoals'] or 0,
                    'sog': row['I_F_shotsOnGoal'] or 0,
                    'hdcf': row['I_F_highDangerShots'] or 0,
                    'goals': row['I_F_goals'] or 0,
                    'icetime': icetime_min,
                })
                ps = player_season[pid]
                ps['goals'] += (row['I_F_goals'] or 0)
                ps['gp'] += 1
                continue

            opp = pd_e['opp']
            is_pp1 = pid in pp1_pids

            # SA/G adverse (combien l'adversaire subit de tirs)
            opp_sa = team_sa_history[opp]
            sa_g = sum(opp_sa) / max(len(opp_sa), 1) if len(opp_sa) > 0 else 30.0

            sog_score = calculate_sog_score(
                sog=pd_e['l10_sog'], atoi=l10_atoi,
                ixg=pd_e['l10_ixg'], hdcf=pd_e['l10_hdcf'],
                season_g=season_g, is_pp1=is_pp1,
                is_home=pd_e['is_home'], sa_g=sa_g,
            )

            actual_sog = int(row['I_F_shotsOnGoal'] or 0)
            hit_target = int(actual_sog >= SOG_TARGET)

            all_entries.append({
                'game_id': game_id, 'date': game_date,
                'name': pd_e['name'], 'team': pd_e['team'], 'opp': opp,
                'sog_score': round(sog_score, 2),
                'hit_sog': hit_target,
                'actual_sog': actual_sog,
                'pp1': int(is_pp1),
                'is_home': int(pd_e['is_home']),
                'sog_l10': round(pd_e['l10_sog'], 2),
                'atoi_l10': round(l10_atoi, 1),
                'ixg_l10': round(pd_e['l10_ixg'], 4),
                'hdcf_l10': round(pd_e['l10_hdcf'], 2),
                'season_g': round(season_g, 3),
                'sa_g': round(sa_g, 1),
                'sog_x_atoi': round(pd_e['l10_sog'] * l10_atoi, 2),
            })

            # Update history 
            icetime_min = row['icetime'] / 60.0 if row['icetime'] > 0 else 0
            player_history[pid].append({
                'ixg': row['I_F_xGoals'] or 0,
                'sog': row['I_F_shotsOnGoal'] or 0,
                'hdcf': row['I_F_highDangerShots'] or 0,
                'goals': row['I_F_goals'] or 0,
                'icetime': icetime_min,
            })
            ps = player_season[pid]
            ps['goals'] += (row['I_F_goals'] or 0)
            ps['gp'] += 1

        # Update team SOG against
        for t in teams_in_game:
            t_sog = game_df[game_df['playerTeam'] == t]['I_F_shotsOnGoal'].sum()
            for ot in game_df[game_df['playerTeam'] != t]['playerTeam'].unique():
                team_sa_history[ot].append(t_sog if not pd.isna(t_sog) else 0)

    elapsed = time.time() - t0
    print(f"\n  Terminé : {games_processed:,} matchs en {elapsed:.0f}s")

    # ── 3. Dataset ────────────────────────────────────────────────
    print("\n[3/5] Dataset SOG...", flush=True)
    bets_df = pd.DataFrame(all_entries)
    n_matches = bets_df['game_id'].nunique()
    base_rate = bets_df['hit_sog'].mean() * 100
    print(f"  {len(bets_df):,} entrées | {n_matches:,} matchs | Base SOG hit: {base_rate:.1f}%")
    bets_df.to_csv('./backtests/backtest_sog.csv', index=False)

    # ── 4. Analyse des seuils SOG Score ──────────────────────────
    print(f"\n[4/5] Scanner de seuils SOG Score...")
    print(f"  {'Score ≥':>10s} | {'WR':>7s} | {'N':>7s} | {'P/M':>6s} | {'ROI':>8s}")
    print("  " + "-" * 50)
    for t in np.arange(10.0, 3.0, -0.5):
        sub = bets_df[bets_df['sog_score'] >= t]
        if len(sub) < 50: continue
        wr = sub['hit_sog'].mean() * 100
        ppm = len(sub) / max(n_matches, 1)
        roi = ((sub['hit_sog'].sum() * ODDS_AVG_SOG - len(sub)) / len(sub)) * 100
        marker = " ◄" if wr >= 55 else ""
        print(f"  {t:>10.1f} | {wr:>6.1f}% | {len(sub):>7,} | {ppm:>5.2f} | {roi:>+7.1f}%{marker}")

    # ── 5. XGBoost SOG ───────────────────────────────────────────
    print(f"\n[5/5] XGBoost SOG...", flush=True)

    features = [
        'sog_l10', 'atoi_l10', 'ixg_l10', 'hdcf_l10', 'season_g',
        'sa_g', 'pp1', 'is_home', 'sog_x_atoi', 'sog_score',
    ]

    X = bets_df[features].values
    y = bets_df['hit_sog'].astype(int).values

    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    scale = (len(y_train) - y_train.sum()) / max(1, y_train.sum())

    from xgboost import XGBClassifier
    model = XGBClassifier(
        n_estimators=200, max_depth=5, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        scale_pos_weight=scale, eval_metric='logloss', random_state=42
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    y_proba = model.predict_proba(X_test)[:, 1]

    # Feature importance
    importance = model.feature_importances_
    feat_imp = sorted(zip(features, importance), key=lambda x: x[1], reverse=True)
    print("\n  Feature Importance SOG:")
    for fname, imp in feat_imp:
        bar = "█" * int(imp * 60)
        print(f"  {fname:18s} : {imp:.3f} {bar}")

    # Scanner Proba SOG
    test_df = bets_df.iloc[split_idx:].copy()
    test_df['proba_sog'] = y_proba
    n_test = test_df['game_id'].nunique()

    print(f"\n  --- Scanner Proba SOG ---")
    print(f"  {'Proba ≥':>10s} | {'WR':>7s} | {'N':>7s} | {'P/M':>6s} | {'ROI':>8s}")
    print("  " + "-" * 50)
    for t in np.arange(0.70, 0.30, -0.05):
        sub = test_df[test_df['proba_sog'] >= t]
        if len(sub) < 20: continue
        wr = sub['hit_sog'].mean() * 100
        ppm = len(sub) / max(n_test, 1)
        roi = ((sub['hit_sog'].sum() * ODDS_AVG_SOG - len(sub)) / len(sub)) * 100
        marker = " ◄" if wr >= 55 else ""
        print(f"  {t:>10.2f} | {wr:>6.1f}% | {len(sub):>7,} | {ppm:>5.2f} | {roi:>+7.1f}%{marker}")

    # Combinaison Score + Proba
    print(f"\n  --- Combinaison SOG Score ≥ 7.0 + Proba ---")
    score_filtered = test_df[test_df['sog_score'] >= 7.0]
    for t in np.arange(0.65, 0.30, -0.05):
        sub = score_filtered[score_filtered['proba_sog'] >= t]
        if len(sub) < 20: continue
        wr = sub['hit_sog'].mean() * 100
        ppm = len(sub) / max(n_test, 1)
        roi = ((sub['hit_sog'].sum() * ODDS_AVG_SOG - len(sub)) / len(sub)) * 100
        marker = " ◄" if wr >= 55 else ""
        print(f"  Score≥7+P≥{t:.2f} | {wr:>6.1f}% | {len(sub):>7,} | {ppm:>5.2f} | {roi:>+7.1f}%{marker}")

    # Save model
    import joblib
    os.makedirs('./models', exist_ok=True)
    joblib.dump({'model': model, 'features': features, 'version': 'sog_v1'},
                './models/sog_model_v1.pkl')
    print("\n  Modèle SOG sauvegardé → models/sog_model_v1.pkl")

    print(f"\n  Temps total : {time.time()-t0:.0f}s")
    print("=" * 60)


if __name__ == '__main__':
    main()
