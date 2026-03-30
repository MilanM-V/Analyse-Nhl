"""
simulate_v4_features.py — Backtest V4 avec features avancées

Nouvelles features vs V3 :
1. Backup Goalie detection (via icetime gardien)
2. Back-to-Back detection (dates consécutives)
3. Hot streak avancé (matchs consécutifs avec but)
4. Défense adverse fine (HDCA/G rolling, PK% rolling)
5. Scoring rate vs xG (luck factor)
"""
import sys, os, math, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from collections import defaultdict, deque
from datetime import datetime, timedelta

CSV_PATH = "./stats/skaters_all.csv"
ODDS_AVG = 2.60
STAKE = 1.0
MIN_ATOI = 16.0

USECOLS = [
    'playerId', 'name', 'gameId', 'season', 'playerTeam', 'opposingTeam',
    'home_or_away', 'gameDate', 'position', 'situation', 'icetime',
    'I_F_xGoals', 'I_F_shotsOnGoal', 'I_F_goals', 'I_F_highDangerShots',
    'I_F_rebounds', 'onIce_corsiPercentage',
    'OnIce_F_goals', 'OnIce_A_goals', 'OnIce_F_shotsOnGoal',
    'OnIce_F_highDangerShots', 'OnIce_A_highDangerShots',
]


def calculate_base_qs_v4(ixg, hdcf, sog, atoi, season_g, oish, pdo,
                          ga_g, pk_pct, hdca_g, is_pp1, is_home, is_b2b,
                          is_backup):
    """V10 + bonus backup goalie."""
    qs = 3.5

    if oish > 16.0:   qs -= 2.0
    elif oish > 14.0: qs -= 1.0
    if is_b2b: qs -= 1.5

    g1 = 0.0
    ixg_score = (4.0 if ixg >= 0.55 else
                 3.0 if ixg >= 0.45 else
                 2.5 if ixg >= 0.38 else
                 1.5 if ixg >= 0.30 else
                 0.5 if ixg >= 0.22 else
                -1.0)
    g1 += ixg_score

    if hdcf >= 3.0:   g1 += 2.5
    elif hdcf >= 2.5: g1 += 1.5
    elif hdcf >= 2.0: g1 += 0.75
    elif hdcf >= 1.5: g1 += 0.5
    else:             g1 -= 0.5

    if sog >= 3.5:   g1 += 1.0
    elif sog >= 2.5: g1 += 0.5

    qs += min(g1, 5.0)

    g2 = 0.0
    if ga_g >= 3.00:   g2 += 2.5
    elif ga_g >= 2.80: g2 += 1.5
    elif ga_g >= 2.50: g2 += 0.5
    elif ga_g < 2.30:  g2 -= 0.5

    if pk_pct < 77.0:   g2 += 1.0
    elif pk_pct < 80.0: g2 += 0.5
    elif pk_pct > 85.0: g2 -= 0.5

    if hdca_g >= 12.0:   g2 += 0.75
    elif hdca_g >= 10.0: g2 += 0.375
    elif hdca_g <= 5.0:  g2 -= 0.5

    qs += min(g2, 3.5)

    g3 = 0.0
    if atoi >= 20.0:   g3 += 1.5
    elif atoi >= 18.0: g3 += 0.75

    if pdo < 96.0:    g3 += 2.0
    elif pdo < 98.0:  g3 += 1.0
    elif pdo > 103.0: g3 -= 1.0
    elif pdo > 100.0: g3 -= 0.5

    if season_g >= 0.35:   g3 += 0.5
    elif season_g >= 0.25: g3 += 0.25

    qs += min(g3, 3.0)

    if is_pp1:
        if pk_pct < 77.0:   qs += 2.5
        elif pk_pct > 83.0: qs += 0.5
        else:               qs += 1.75

    if is_backup and ga_g >= 2.8:
        qs += 2.0
    elif is_backup:
        qs += 0.75

    qs_normalized = 2 + 10 * (1 / (1 + math.exp(-0.45 * (qs - 6.5))))
    return qs_normalized


def main():
    t0 = time.time()
    print("=" * 60)
    print("  SIMULATION V4 — Features Avancées (B2B, Backup, Streaks)")
    print("=" * 60)

    # ── 1. Chargement ─────────────────────────────────────────────
    print("\n[1/6] Chargement...", flush=True)
    chunks_all = []
    chunks_5v5 = []
    total = 0
    
    for chunk in pd.read_csv(CSV_PATH, chunksize=100_000, usecols=USECOLS, low_memory=False):
        chunk = chunk[~chunk['position'].isin(['G'])]
        chunk['gameDate'] = chunk['gameDate'].astype(str)
        
        c_all = chunk[chunk['situation'] == 'all'].copy()
        chunks_all.append(c_all)
        
        c5 = chunk[chunk['situation'] == '5on5'][
            ['playerId', 'gameId', 'OnIce_F_goals', 'OnIce_F_shotsOnGoal',
             'OnIce_F_highDangerShots', 'OnIce_A_highDangerShots']
        ].copy()
        chunks_5v5.append(c5)
        
        total += len(c_all)
        print(f"  ... {total:,}", end='\r', flush=True)

    df = pd.concat(chunks_all, ignore_index=True)
    df_5v5 = pd.concat(chunks_5v5, ignore_index=True)
    del chunks_all, chunks_5v5
    df = df.sort_values(['gameDate', 'gameId']).reset_index(drop=True)
    n_games = df['gameId'].nunique()
    print(f"\n  {len(df):,} lignes | {n_games:,} matchs")

    # ── 2. Index 5v5 ──────────────────────────────────────────────
    print("\n[2/6] Index 5v5...", flush=True)
    oish_5v5 = {}
    hdca_5v5 = {}  # HDCA par équipe-match
    for _, r5 in df_5v5.iterrows():
        sog5 = r5.get('OnIce_F_shotsOnGoal', 0) or 0
        g5 = r5.get('OnIce_F_goals', 0) or 0
        oish_5v5[(r5['playerId'], r5['gameId'])] = (g5 / sog5) * 100 if sog5 > 0 else 10.0
    del df_5v5

    # ── 3. Simulation ─────────────────────────────────────────────
    print("\n[3/6] Simulation V4...", flush=True)

    player_history = defaultdict(lambda: deque(maxlen=10))
    player_goals_history = defaultdict(lambda: deque(maxlen=10))
    player_season = defaultdict(lambda: {'goals': 0, 'gp': 0, 'season': None})
    
    # Team trackers
    team_ga_history = defaultdict(lambda: deque(maxlen=10))
    team_hdca_history = defaultdict(lambda: deque(maxlen=10))
    team_last_game_date = {}  # Pour détecter B2B
    team_goals_allowed_history = defaultdict(lambda: deque(maxlen=20))  # Pour PK% approx
    
    # Goalie tracker (pour backup detection)
    team_goalie_icetime = defaultdict(lambda: defaultdict(float))  # {team: {season: {goalie_id: total_icetime}}}

    all_entries = []
    games_processed = 0
    game_ids_seen = set()

    for game_id, game_df in df.groupby('gameId', sort=False):
        if game_id in game_ids_seen:
            continue
        game_ids_seen.add(game_id)
        games_processed += 1

        if games_processed % 5000 == 0:
            print(f"  ... {games_processed:,}/{n_games:,} ({time.time()-t0:.0f}s)", end='\r', flush=True)

        game_date = game_df['gameDate'].iloc[0]
        season = game_df['season'].iloc[0] if 'season' in game_df.columns else 0

        # ── B2B detection ──
        teams_in_game = game_df['playerTeam'].unique()
        b2b_teams = set()
        try:
            gd = datetime.strptime(str(game_date)[:8], '%Y%m%d')
            for t in teams_in_game:
                if t in team_last_game_date:
                    last_gd = team_last_game_date[t]
                    if (gd - last_gd).days <= 1:
                        b2b_teams.add(t)
        except:
            pass

        # ── PP1 detection ──
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
            goals_hist = player_goals_history[pid]

            if len(history) < 5:
                icetime_min = row['icetime'] / 60.0 if row['icetime'] > 0 else 0
                history.append({
                    'ixg': row['I_F_xGoals'] or 0,
                    'sog': row['I_F_shotsOnGoal'] or 0,
                    'hdcf': row['I_F_highDangerShots'] or 0,
                    'goals': row['I_F_goals'] or 0,
                    'icetime': icetime_min,
                    'oiSH': oish_5v5.get((pid, game_id), 10.0),
                })
                goals_hist.append(row['I_F_goals'] or 0)
                ps['goals'] += (row['I_F_goals'] or 0)
                ps['gp'] += 1
                continue

            n_hist = len(history)
            l10_ixg = sum(h['ixg'] for h in history) / n_hist
            l10_sog = sum(h['sog'] for h in history) / n_hist
            l10_hdcf = sum(h['hdcf'] for h in history) / n_hist
            l10_atoi = sum(h['icetime'] for h in history) / n_hist
            avg_oish = sum(h['oiSH'] for h in history) / n_hist
            season_g = ps['goals'] / max(ps['gp'], 1)

            # Streaks
            goals_list = list(goals_hist)
            l3_goals = sum(goals_list[-3:]) if len(goals_list) >= 3 else 0
            l5_goals = sum(goals_list[-5:]) if len(goals_list) >= 5 else 0
            l3_scored = sum(1 for g in goals_list[-3:] if g > 0) if len(goals_list) >= 3 else 0
            l5_scored = sum(1 for g in goals_list[-5:] if g > 0) if len(goals_list) >= 5 else 0
            l10_goals = sum(goals_list)
            l10_scored = sum(1 for g in goals_list if g > 0)

            # Consecutive games with goal (hot streak)
            consec_goals = 0
            for g in reversed(goals_list):
                if g > 0:
                    consec_goals += 1
                else:
                    break

            # Scoring rate vs xG (luck factor)
            l10_total_xg = sum(h['ixg'] for h in history)
            luck_factor = l10_goals / max(l10_total_xg, 0.01) if l10_total_xg > 0 else 1.0

            team_ixg_candidates[team].append((pid, l10_ixg))

            player_data.append({
                'pid': pid, 'name': row['name'], 'team': team,
                'opp': row['opposingTeam'],
                'is_home': row['home_or_away'] == 'HOME',
                'row': row,
                'l10_ixg': l10_ixg, 'l10_sog': l10_sog, 'l10_hdcf': l10_hdcf,
                'l10_atoi': l10_atoi, 'avg_oish': avg_oish, 'season_g': season_g,
                'l3_goals': l3_goals, 'l5_goals': l5_goals,
                'l3_scored': l3_scored, 'l5_scored': l5_scored,
                'l10_goals': l10_goals, 'l10_scored': l10_scored,
                'consec_goals': consec_goals, 'luck_factor': luck_factor,
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

            if season_g < 0.18 or l10_atoi < MIN_ATOI:
                icetime_min = row['icetime'] / 60.0 if row['icetime'] > 0 else 0
                player_history[pid].append({
                    'ixg': row['I_F_xGoals'] or 0,
                    'sog': row['I_F_shotsOnGoal'] or 0,
                    'hdcf': row['I_F_highDangerShots'] or 0,
                    'goals': row['I_F_goals'] or 0,
                    'icetime': icetime_min,
                    'oiSH': oish_5v5.get((pid, game_id), 10.0),
                })
                player_goals_history[pid].append(row['I_F_goals'] or 0)
                ps = player_season[pid]
                ps['goals'] += (row['I_F_goals'] or 0)
                ps['gp'] += 1
                continue

            opp = pd_e['opp']
            is_pp1 = pid in pp1_pids
            team = pd_e['team']
            is_b2b = team in b2b_teams
            opp_is_b2b = opp in b2b_teams

            # Defensive stats
            opp_ga = team_ga_history[opp]
            ga_g = sum(opp_ga) / max(len(opp_ga), 1) if len(opp_ga) > 0 else 2.7
            
            opp_hdca = team_hdca_history[opp]
            hdca_g = sum(opp_hdca) / max(len(opp_hdca), 1) if len(opp_hdca) > 0 else 8.0

            # Backup goalie detection (simplifiée : pas de données gardien dans skaters_all)
            is_backup = False

            qs = calculate_base_qs_v4(
                ixg=pd_e['l10_ixg'], hdcf=pd_e['l10_hdcf'],
                sog=pd_e['l10_sog'], atoi=l10_atoi,
                season_g=season_g, oish=pd_e['avg_oish'], pdo=100.0,
                ga_g=ga_g, pk_pct=80.0, hdca_g=hdca_g,
                is_pp1=is_pp1, is_home=pd_e['is_home'],
                is_b2b=is_b2b, is_backup=is_backup
            )

            scored = int((row['I_F_goals'] or 0) > 0)

            all_entries.append({
                'game_id': game_id, 'date': game_date, 'season': season,
                'name': pd_e['name'], 'team': team, 'opp': opp,
                'qs_v10': round(qs, 3),
                'scored': scored,
                'pp1': int(is_pp1),
                'is_home': int(pd_e['is_home']),
                'is_b2b': int(is_b2b),
                'opp_is_b2b': int(opp_is_b2b),
                'ixg_l10': round(pd_e['l10_ixg'], 4),
                'hdcf_l10': round(pd_e['l10_hdcf'], 2),
                'sog_l10': round(pd_e['l10_sog'], 2),
                'atoi_l10': round(l10_atoi, 1),
                'season_g': round(season_g, 3),
                'ga_g': round(ga_g, 2),
                'hdca_g': round(hdca_g, 2),
                'l3_goals': pd_e['l3_goals'],
                'l5_goals': pd_e['l5_goals'],
                'l3_scored': pd_e['l3_scored'],
                'l5_scored': pd_e['l5_scored'],
                'l10_goals': pd_e['l10_goals'],
                'l10_scored': pd_e['l10_scored'],
                'consec_goals': pd_e['consec_goals'],
                'luck_factor': round(pd_e['luck_factor'], 3),
            })

            # Update history
            icetime_min = row['icetime'] / 60.0 if row['icetime'] > 0 else 0
            player_history[pid].append({
                'ixg': row['I_F_xGoals'] or 0,
                'sog': row['I_F_shotsOnGoal'] or 0,
                'hdcf': row['I_F_highDangerShots'] or 0,
                'goals': row['I_F_goals'] or 0,
                'icetime': icetime_min,
                'oiSH': oish_5v5.get((pid, game_id), 10.0),
            })
            player_goals_history[pid].append(row['I_F_goals'] or 0)
            ps = player_season[pid]
            ps['goals'] += (row['I_F_goals'] or 0)
            ps['gp'] += 1

        # Update team stats
        for t in teams_in_game:
            t_goals = game_df[game_df['playerTeam'] == t]['I_F_goals'].sum()
            t_hdcf = game_df[game_df['playerTeam'] == t]['I_F_highDangerShots'].sum()
            for ot in game_df[game_df['playerTeam'] != t]['playerTeam'].unique():
                team_ga_history[ot].append(t_goals if not pd.isna(t_goals) else 0)
                team_hdca_history[ot].append(t_hdcf if not pd.isna(t_hdcf) else 0)
            # B2B tracking
            try:
                team_last_game_date[t] = datetime.strptime(str(game_date)[:8], '%Y%m%d')
            except:
                pass

    elapsed = time.time() - t0
    print(f"\n  Terminé : {games_processed:,} matchs en {elapsed:.0f}s")

    # ── 4. Dataset ────────────────────────────────────────────────
    print("\n[4/6] Dataset...", flush=True)
    bets_df = pd.DataFrame(all_entries)
    n_matches = bets_df['game_id'].nunique()
    print(f"  {len(bets_df):,} entrées | {n_matches:,} matchs | Base: {bets_df['scored'].mean()*100:.1f}%")
    bets_df.to_csv('backtest_v4_features.csv', index=False)

    # ── 5. Analyse feature par feature ────────────────────────────
    print("\n[5/6] Impact de chaque feature sur le WR...")
    print("=" * 60)

    # B2B impact
    b2b_opp = bets_df[bets_df['opp_is_b2b'] == 1]
    no_b2b_opp = bets_df[bets_df['opp_is_b2b'] == 0]
    print(f"\n  ADVERSAIRE EN B2B :")
    print(f"    Oui : {b2b_opp['scored'].mean()*100:.1f}% WR ({len(b2b_opp):,} paris)")
    print(f"    Non : {no_b2b_opp['scored'].mean()*100:.1f}% WR ({len(no_b2b_opp):,} paris)")
    print(f"    Δ   : {(b2b_opp['scored'].mean() - no_b2b_opp['scored'].mean())*100:+.1f}%")

    # Hot streak
    for streak_len in [1, 2, 3]:
        streak = bets_df[bets_df['consec_goals'] >= streak_len]
        no_streak = bets_df[bets_df['consec_goals'] < streak_len]
        print(f"\n  HOT STREAK ≥ {streak_len} matchs consécutifs avec but :")
        print(f"    Oui : {streak['scored'].mean()*100:.1f}% WR ({len(streak):,} paris)")
        print(f"    Non : {no_streak['scored'].mean()*100:.1f}% WR ({len(no_streak):,} paris)")
        print(f"    Δ   : {(streak['scored'].mean() - no_streak['scored'].mean())*100:+.1f}%")

    # HDCA impact
    high_hdca = bets_df[bets_df['hdca_g'] >= 10.0]
    low_hdca = bets_df[bets_df['hdca_g'] < 10.0]
    print(f"\n  HDCA/G ADVERSE ≥ 10 (défense poreuse) :")
    print(f"    Oui : {high_hdca['scored'].mean()*100:.1f}% WR ({len(high_hdca):,} paris)")
    print(f"    Non : {low_hdca['scored'].mean()*100:.1f}% WR ({len(low_hdca):,} paris)")
    print(f"    Δ   : {(high_hdca['scored'].mean() - low_hdca['scored'].mean())*100:+.1f}%")

    # Luck factor (regression)
    lucky = bets_df[bets_df['luck_factor'] > 1.5]
    unlucky = bets_df[bets_df['luck_factor'] < 0.5]
    normal = bets_df[(bets_df['luck_factor'] >= 0.5) & (bets_df['luck_factor'] <= 1.5)]
    print(f"\n  LUCK FACTOR (buts/xG ratio L10) :")
    print(f"    Lucky (>1.5)  : {lucky['scored'].mean()*100:.1f}% WR ({len(lucky):,})")
    print(f"    Normal        : {normal['scored'].mean()*100:.1f}% WR ({len(normal):,})")
    print(f"    Unlucky (<0.5): {unlucky['scored'].mean()*100:.1f}% WR ({len(unlucky):,})")

    # PP1 impact
    pp1_on = bets_df[bets_df['pp1'] == 1]
    pp1_off = bets_df[bets_df['pp1'] == 0]
    print(f"\n  PP1 (Power Play 1) :")
    print(f"    Oui : {pp1_on['scored'].mean()*100:.1f}% WR ({len(pp1_on):,})")
    print(f"    Non : {pp1_off['scored'].mean()*100:.1f}% WR ({len(pp1_off):,})")
    print(f"    Δ   : {(pp1_on['scored'].mean() - pp1_off['scored'].mean())*100:+.1f}%")

    # Home
    home = bets_df[bets_df['is_home'] == 1]
    away = bets_df[bets_df['is_home'] == 0]
    print(f"\n  HOME / AWAY :")
    print(f"    Home : {home['scored'].mean()*100:.1f}% WR ({len(home):,})")
    print(f"    Away : {away['scored'].mean()*100:.1f}% WR ({len(away):,})")
    print(f"    Δ    : {(home['scored'].mean() - away['scored'].mean())*100:+.1f}%")

    # ── 6. XGBoost V4 + Threshold scan ────────────────────────────
    print(f"\n[6/6] XGBoost V4...", flush=True)
    
    features = [
        'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 'season_g',
        'ga_g', 'hdca_g', 'pp1', 'is_home', 'is_b2b', 'opp_is_b2b',
        'l3_goals', 'l5_goals', 'l3_scored', 'l5_scored',
        'l10_goals', 'l10_scored', 'consec_goals', 'luck_factor',
        'qs_v10',
    ]
    
    bets_df['ixg_x_hdcf'] = bets_df['ixg_l10'] * bets_df['hdcf_l10']
    bets_df['sog_x_atoi'] = bets_df['sog_l10'] * bets_df['atoi_l10']
    bets_df['ixg_x_ga'] = bets_df['ixg_l10'] * bets_df['ga_g']
    bets_df['streak_x_ixg'] = bets_df['consec_goals'] * bets_df['ixg_l10']
    bets_df['scoring_rate'] = bets_df['l10_scored'] / 10.0
    
    features_ext = features + ['ixg_x_hdcf', 'sog_x_atoi', 'ixg_x_ga', 'streak_x_ixg', 'scoring_rate']

    X = bets_df[features_ext].values
    y = bets_df['scored'].astype(int).values

    split_idx = int(len(X) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    scale = (len(y_train) - y_train.sum()) / max(1, y_train.sum())

    from xgboost import XGBClassifier
    model = XGBClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.03,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=5,
        scale_pos_weight=scale, eval_metric='logloss', random_state=42
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    y_proba = model.predict_proba(X_test)[:, 1]

    # Feature importance
    importance = model.feature_importances_
    feat_imp = sorted(zip(features_ext, importance), key=lambda x: x[1], reverse=True)
    print("\n  Feature Importance (top 12):")
    for fname, imp in feat_imp[:12]:
        bar = "█" * int(imp * 60)
        print(f"  {fname:22s} : {imp:.3f} {bar}")

    # Scanner
    test_df = bets_df.iloc[split_idx:].copy()
    test_df['proba'] = y_proba
    n_test = test_df['game_id'].nunique()

    print(f"\n  --- Scanner de seuils V4 ---")
    print(f"  {'Proba ≥':>10s} | {'WR':>7s} | {'N':>7s} | {'P/M':>6s} | {'ROI':>8s}")
    print("  " + "-" * 50)
    for t in np.arange(0.60, 0.24, -0.02):
        sub = test_df[test_df['proba'] >= t]
        if len(sub) < 20: continue
        wr = sub['scored'].mean() * 100
        ppm = len(sub) / max(n_test, 1)
        roi = ((sub['scored'].sum() * ODDS_AVG - len(sub)) / len(sub)) * 100
        marker = " ◄" if wr >= 40 else ""
        print(f"  {t:>10.2f} | {wr:>6.1f}% | {len(sub):>7,} | {ppm:>5.2f} | {roi:>+7.1f}%{marker}")

    # V10 distribution
    print(f"\n  --- Score V10 ---")
    for t in [12.0, 11.5, 11.0, 10.5, 10.0, 9.5, 9.0]:
        sub = test_df[test_df['qs_v10'] >= t]
        if sub.empty: continue
        wr = sub['scored'].mean() * 100
        ppm = len(sub) / max(n_test, 1)
        roi = ((sub['scored'].sum() * ODDS_AVG - len(sub)) / len(sub)) * 100
        print(f"  V10 ≥ {t:>5.1f} | {wr:>6.1f}% | {len(sub):>7,} | {ppm:>5.2f} | {roi:>+7.1f}%")

    # Combined: V10 score + high proba
    print(f"\n  --- Combinaison V10 ≥ 10.5 + Proba ---")
    v10_filtered = test_df[test_df['qs_v10'] >= 10.5]
    for t in np.arange(0.55, 0.25, -0.02):
        sub = v10_filtered[v10_filtered['proba'] >= t]
        if len(sub) < 20: continue
        wr = sub['scored'].mean() * 100
        ppm = len(sub) / max(n_test, 1)
        roi = ((sub['scored'].sum() * ODDS_AVG - len(sub)) / len(sub)) * 100
        marker = " ◄" if wr >= 40 else ""
        print(f"  V10≥10.5 + P≥{t:.2f} | {wr:>6.1f}% | {len(sub):>7,} | {ppm:>5.2f} | {roi:>+7.1f}%{marker}")

    import joblib
    joblib.dump({'model': model, 'features': features_ext, 'version': 'v4_enhanced'}, 
                './models/pregame_model_v4.pkl')

    print(f"\n  Temps total : {time.time()-t0:.0f}s")
    print("=" * 60)


if __name__ == '__main__':
    main()
