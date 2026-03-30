import pandas as pd
import numpy as np
from collections import defaultdict, deque
import math
import os
import sys
import joblib

# Ajouter le root au path pour les imports core
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CSV_PATH = "./stats/skaters_all.csv"
USECOLS = [
    'playerId', 'name', 'gameId', 'season', 'playerTeam', 'opposingTeam',
    'home_or_away', 'gameDate', 'position', 'situation', 'icetime',
    'I_F_xGoals', 'I_F_shotsOnGoal', 'I_F_goals', 'I_F_points',
    'I_F_primaryAssists', 'I_F_secondaryAssists', 'I_F_highDangerShots'
]

def calculate_qs_goal(v):
    qs = 3.5
    ixg = v['ixg']
    hdcf = v['l10_hdcf']
    sog = v['l10_sog']
    atoi = v['atoi']
    
    ixg_score = (4.0 if ixg >= 0.55 else 3.0 if ixg >= 0.45 else 2.5 if ixg >= 0.38 else 1.5 if ixg >= 0.30 else 0.5 if ixg >= 0.22 else -1.0)
    g1 = ixg_score
    if hdcf >= 3.0:   g1 += 2.5
    elif hdcf >= 2.5: g1 += 1.5
    elif hdcf >= 2.0: g1 += 0.75
    elif hdcf >= 1.5: g1 += 0.5
    else:             g1 -= 0.5
    if sog >= 3.5:   g1 += 1.0
    elif sog >= 2.5: g1 += 0.5
    qs += min(g1, 5.0)

    # Mock GA_G / Opponent (moyenne 2.8)
    qs += 1.5 
    
    g3 = 0.0
    if atoi >= 20.0:   g3 += 1.5
    elif atoi >= 18.0: g3 += 0.75
    qs += min(g3, 3.0)
    
    return 2 + 10 * (1 / (1 + math.exp(-0.45 * (qs - 6.5))))

def calculate_qs_assist(v):
    qs = 4.0
    l10_a = v['l10_a']
    if l10_a >= 0.8: qs += 3.0
    elif l10_a >= 0.6: qs += 2.0
    elif l10_a >= 0.4: qs += 1.0
    if v['atoi'] >= 20.0: qs += 2.0
    elif v['atoi'] >= 18.0: qs += 1.0
    return 2 + 10 * (1 / (1 + math.exp(-0.4 * (qs - 7.0))))

def calculate_qs_point(v):
    q_g = calculate_qs_goal(v)
    q_a = calculate_qs_assist(v)
    return (q_g * 0.4) + (q_a * 0.6)

def calculate_sog_score(v):
    score = 0.0
    sog = v['l10_sog']
    if sog >= 4.0: score += 4.0
    elif sog >= 3.5: score += 3.0
    elif sog >= 3.0: score += 2.0
    elif sog >= 2.5: score += 1.0
    elif sog >= 2.0: score += 0.5
    else:            score -= 1.0
    if v['atoi'] >= 20.0: score += 2.0
    elif v['atoi'] >= 18.0: score += 1.0
    elif v['atoi'] >= 16.0: score += 0.5
    if v['ixg'] >= 0.50: score += 1.5
    elif v['ixg'] >= 0.35: score += 1.0
    elif v['ixg'] >= 0.25: score += 0.5
    return score

def evaluate_xgb_mock(v):
    # Mock simple de la proba XGBoost basée sur ixg et atoi
    base_proba = (v['ixg'] * 0.6) + (v['atoi'] / 60.0 * 0.2)
    return min(0.65, max(0.05, base_proba + 0.15))

def compute_buteurs_thresholds_from_backtest(target_seasons: list[int]) -> dict[str, float]:
    backtest_path = "./backtests/backtest_v4_features.csv"
    model_path = "./models/pregame_model_v4.pkl"
    df = pd.read_csv(backtest_path)
    df = df[df["season"].isin(target_seasons)].copy()
    pack = joblib.load(model_path)
    model = pack["model"]
    features = pack["features"]

    if "ixg_x_hdcf" not in df.columns:
        df["ixg_x_hdcf"] = df["ixg_l10"] * df["hdcf_l10"]
        df["sog_x_atoi"] = df["sog_l10"] * df["atoi_l10"]
        df["ixg_x_ga"] = df["ixg_l10"] * df["ga_g"]
        df["streak_x_ixg"] = df["consec_goals"] * df["ixg_l10"]
        df["scoring_rate"] = df["l10_scored"] / 10.0

    proba = model.predict_proba(df[features].values)[:, 1]
    df["proba"] = proba

    n_matches = int(df["game_id"].nunique())

    qs_vals = np.unique(np.round(np.quantile(df["qs_v10"], np.linspace(0.30, 0.999, 350)), 2))
    p_vals = np.round(np.arange(0.35, 0.71, 0.01), 2)

    target_elite_wr = 0.45
    target_elite_ppm = 0.25

    best_elite = None
    best_elite_ppm_over = float("inf")
    best_elite_wr = -1.0

    for qs in qs_vals[::-1]:
        for p in p_vals[::-1]:
            m = (df["qs_v10"] >= qs) & (df["proba"] >= p)
            c = int(m.sum())
            if c == 0:
                continue
            ppm = c / n_matches
            if ppm < target_elite_ppm:
                continue
            wr = float(df.loc[m, "scored"].mean())
            if wr < target_elite_wr:
                continue
            ppm_over = ppm - target_elite_ppm
            if (ppm_over < best_elite_ppm_over) or (ppm_over == best_elite_ppm_over and wr > best_elite_wr):
                best_elite = (float(qs), float(p), wr, ppm, c)
                best_elite_ppm_over = ppm_over
                best_elite_wr = wr

    if best_elite is None:
        best_elite = (float("nan"), float("nan"), float("nan"), 0.0, 0)

    elite_qs, elite_p, elite_wr, elite_ppm, elite_c = best_elite
    elite_mask = (df["qs_v10"] >= elite_qs) & (df["proba"] >= elite_p)

    target_safe_wr = 0.40
    target_safe_ppm = 1.0

    best_safe = None
    best_safe_ppm_abs = float("inf")
    best_safe_wr = -1.0

    for qs in qs_vals:
        for p in p_vals:
            m = (df["qs_v10"] >= qs) & (df["proba"] >= p) & (~elite_mask)
            c = int(m.sum())
            if c == 0:
                continue
            ppm = c / n_matches
            wr = float(df.loc[m, "scored"].mean())
            if wr < target_safe_wr:
                continue
            ppm_abs = abs(ppm - target_safe_ppm)
            if (ppm_abs < best_safe_ppm_abs) or (ppm_abs == best_safe_ppm_abs and wr > best_safe_wr):
                best_safe = (float(qs), float(p), wr, ppm, c)
                best_safe_ppm_abs = ppm_abs
                best_safe_wr = wr

    if best_safe is None:
        best_safe = (float("nan"), float("nan"), float("nan"), 0.0, 0)

    safe_qs, safe_p, safe_wr, safe_ppm, safe_c = best_safe

    best_near_1ppm = None
    best_near_1ppm_wr = -1.0
    for qs in qs_vals:
        for p in np.round(np.arange(0.30, 0.71, 0.005), 3):
            m = (df["qs_v10"] >= qs) & (df["proba"] >= p) & (~elite_mask)
            c = int(m.sum())
            if c < 200:
                continue
            ppm = c / n_matches
            if ppm < 0.98 or ppm > 1.02:
                continue
            wr = float(df.loc[m, "scored"].mean())
            if wr > best_near_1ppm_wr:
                best_near_1ppm = (float(qs), float(p), wr, ppm, c)
                best_near_1ppm_wr = wr

    if best_near_1ppm is None:
        best_near_1ppm = (float("nan"), float("nan"), float("nan"), float("nan"), 0)

    near_qs, near_p, near_wr, near_ppm, near_c = best_near_1ppm

    return {
        "n_matches": float(n_matches),
        "elite_qs": elite_qs,
        "elite_xgb": elite_p,
        "elite_wr": float(elite_wr),
        "elite_ppm": float(elite_ppm),
        "elite_n": float(elite_c),
        "safe_qs": safe_qs,
        "safe_xgb": safe_p,
        "safe_wr": float(safe_wr),
        "safe_ppm": float(safe_ppm),
        "safe_n": float(safe_c),
        "near1_qs": near_qs,
        "near1_xgb": near_p,
        "near1_wr": float(near_wr),
        "near1_ppm": float(near_ppm),
        "near1_n": float(near_c),
    }

def find_thresholds_goal(res_df: pd.DataFrame, n_total_matches: int) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    qs_candidates = np.unique(np.round(np.quantile(res_df['qs_g'], np.linspace(0.35, 0.999, 250)), 2))
    xgb_candidates = np.unique(np.round(np.quantile(res_df['xgb_p'], np.linspace(0.35, 0.999, 250)), 2))

    target_elite_ppm = 0.25
    target_elite_wr = 0.45

    elite_best: tuple[float, float, float, float] | None = None
    elite_best_ppm_over = float("inf")
    elite_best_wr = -1.0

    for qs_t in qs_candidates[::-1]:
        for xgb_t in xgb_candidates[::-1]:
            mask = (res_df['qs_g'] >= qs_t) & (res_df['xgb_p'] >= xgb_t)
            count = int(mask.sum())
            if count == 0:
                continue
            ppm = count / n_total_matches
            if ppm < target_elite_ppm:
                continue
            wr = float(res_df.loc[mask, 'goal'].mean())
            if wr < target_elite_wr:
                continue
            ppm_over = ppm - target_elite_ppm
            if (ppm_over < elite_best_ppm_over) or (ppm_over == elite_best_ppm_over and wr > elite_best_wr):
                elite_best = (float(qs_t), float(xgb_t), wr, ppm)
                elite_best_ppm_over = ppm_over
                elite_best_wr = wr

    if elite_best is None:
        elite_best = (float(qs_candidates.max()), float(xgb_candidates.max()), float("nan"), 0.0)

    elite_qs, elite_xgb, _, _ = elite_best
    elite_mask = (res_df['qs_g'] >= elite_qs) & (res_df['xgb_p'] >= elite_xgb)

    target_safe_ppm = 1.0
    target_safe_wr = 0.40

    safe_best: tuple[float, float, float, float] | None = None
    safe_best_ppm_abs = float("inf")
    safe_best_wr = -1.0

    for qs_t in qs_candidates:
        for xgb_t in xgb_candidates:
            mask = (res_df['qs_g'] >= qs_t) & (res_df['xgb_p'] >= xgb_t) & (~elite_mask)
            count = int(mask.sum())
            if count == 0:
                continue
            ppm = count / n_total_matches
            wr = float(res_df.loc[mask, 'goal'].mean())
            if wr < target_safe_wr:
                continue
            ppm_abs = abs(ppm - target_safe_ppm)
            if (ppm_abs < safe_best_ppm_abs) or (ppm_abs == safe_best_ppm_abs and wr > safe_best_wr):
                safe_best = (float(qs_t), float(xgb_t), wr, ppm)
                safe_best_ppm_abs = ppm_abs
                safe_best_wr = wr

    if safe_best is None:
        safe_best = (float(qs_candidates.min()), float(xgb_candidates.min()), float("nan"), 0.0)

    return elite_best, safe_best

def main():
    if not os.path.exists(CSV_PATH):
        print(f"Erreur : {CSV_PATH} non trouvé.")
        return

    print("Chargement des données (skaters_all.csv)...")
    df_all = pd.read_csv(CSV_PATH, usecols=USECOLS)
    df_all = df_all[df_all["situation"] == "all"].sort_values(["season", "gameDate", "gameId"])

    seasons = sorted(df_all["season"].dropna().unique())
    if len(seasons) < 2:
        print("Erreur : pas assez de saisons dans skaters_all.csv")
        return

    requested_seasons = [2025, 2024, 2023]
    season_list = [s for s in requested_seasons if s in set(map(int, seasons))]
    if not season_list:
        print("Erreur : aucune des saisons demandées (2023-2024-2025) n'est présente dans skaters_all.csv")
        return

    backtest_path = "./backtests/backtest_v4_features.csv"
    model_path = "./models/pregame_model_v4.pkl"
    goal_df = pd.read_csv(backtest_path)
    goal_df = goal_df[goal_df["season"].isin(season_list)].copy()
    goal_pack = joblib.load(model_path)
    goal_model = goal_pack["model"]
    goal_features = goal_pack["features"]

    if "ixg_x_hdcf" not in goal_df.columns:
        goal_df["ixg_x_hdcf"] = goal_df["ixg_l10"] * goal_df["hdcf_l10"]
        goal_df["sog_x_atoi"] = goal_df["sog_l10"] * goal_df["atoi_l10"]
        goal_df["ixg_x_ga"] = goal_df["ixg_l10"] * goal_df["ga_g"]
        goal_df["streak_x_ixg"] = goal_df["consec_goals"] * goal_df["ixg_l10"]
        goal_df["scoring_rate"] = goal_df["l10_scored"] / 10.0

    goal_df["proba"] = goal_model.predict_proba(goal_df[goal_features].values)[:, 1]

    elite_goal_qs = 9.75
    elite_goal_xgb = 0.65
    safe_goal_qs = 6.72
    safe_goal_xgb = 0.585

    def simulate_season(df_season: pd.DataFrame) -> tuple[pd.DataFrame, int]:
        player_hist = defaultdict(lambda: deque(maxlen=10))
        results = []
        for _, row in df_season.iterrows():
            pid = row["playerId"]
            hist = player_hist[pid]
            if len(hist) >= 5:
                stats = {
                    "ixg": sum(h["ixg"] for h in hist) / len(hist),
                    "l10_a": sum(h["a"] for h in hist) / len(hist),
                    "l10_sog": sum(h["sog"] for h in hist) / len(hist),
                    "l10_hdcf": sum(h["hdcf"] for h in hist) / len(hist),
                    "atoi": sum(h["atoi"] for h in hist) / len(hist),
                }
                qs_g = calculate_qs_goal(stats)
                xgb_p = evaluate_xgb_mock(stats)
                results.append(
                    {
                        "qs_g": qs_g,
                        "xgb_p": xgb_p,
                        "qs_a": calculate_qs_assist(stats),
                        "qs_p": calculate_qs_point(stats),
                        "sog_score": calculate_sog_score(stats),
                        "goal": int((row["I_F_goals"] or 0) > 0),
                        "assist": int(((row["I_F_primaryAssists"] or 0) + (row["I_F_secondaryAssists"] or 0)) > 0),
                        "point": int((row["I_F_points"] or 0) > 0),
                        "hit_sog": int((row["I_F_shotsOnGoal"] or 0) >= 3),
                    }
                )
            player_hist[pid].append(
                {
                    "ixg": row["I_F_xGoals"] or 0,
                    "a": (row["I_F_primaryAssists"] or 0) + (row["I_F_secondaryAssists"] or 0),
                    "sog": row["I_F_shotsOnGoal"] or 0,
                    "hdcf": row["I_F_highDangerShots"] or 0,
                    "atoi": (row["icetime"] or 0) / 60.0,
                }
            )
        res_df = pd.DataFrame(results)
        n_matches = int(df_season["gameId"].nunique())
        return res_df, n_matches

    with open("simulation_report.md", "w", encoding="utf-8") as f:
        f.write("# 🏒 Simulation (Dernière saison + Cette saison)\n\n")
        f.write(f"Saisons disponibles dans les datasets: {', '.join(map(str, seasons[-6:]))}.\n\n")
        f.write("Saisons demandées : **2023, 2024, 2025**\n\n")
        f.write(f"Saisons réellement simulées : **{', '.join(map(str, season_list))}**\n\n")

        for s in season_list:
            f.write(f"## Saison {s}\n\n")
            df_s = df_all[df_all["season"] == s].copy()
            res_df, n_matches = simulate_season(df_s)
            f.write(f"Matches (skaters_all) : **{n_matches:,}** | Opportunités : **{len(res_df):,}**\n\n")

            goal_s = goal_df[goal_df["season"] == s].copy()
            n_goal_matches = int(goal_s["game_id"].nunique()) if not goal_s.empty else 0

            if n_goal_matches > 0:
                elite_mask = (goal_s["qs_v10"] >= elite_goal_qs) & (goal_s["proba"] >= elite_goal_xgb)
                safe_mask = (goal_s["qs_v10"] >= safe_goal_qs) & (goal_s["proba"] >= safe_goal_xgb) & (~elite_mask)

                elite_n = int(elite_mask.sum())
                safe_n = int(safe_mask.sum())

                elite_wr = float(goal_s.loc[elite_mask, "scored"].mean()) * 100 if elite_n > 0 else float("nan")
                safe_wr = float(goal_s.loc[safe_mask, "scored"].mean()) * 100 if safe_n > 0 else float("nan")

                elite_ppm = elite_n / n_goal_matches
                safe_ppm = safe_n / n_goal_matches

                elite_pr = (elite_n / len(goal_s)) * 100 if len(goal_s) > 0 else 0.0
                safe_pr = (safe_n / len(goal_s)) * 100 if len(goal_s) > 0 else 0.0

                f.write("### 🎯 BUTEURS\n")
                f.write(f"Matches (backtest_v4) : **{n_goal_matches:,}** | Entrées : **{len(goal_s):,}**\n\n")
                f.write("| Catégorie | Seuil QS | Seuil XGB | Winrate | Pickrate | PPM |\n")
                f.write("|-----------|----------|-----------|---------|----------|-----|\n")
                f.write(f"| ELITE | {elite_goal_qs:.2f} | {elite_goal_xgb:.2f} | {elite_wr:.1f}% | {elite_pr:.2f}% | {elite_ppm:.2f} |\n")
                f.write(f"| SAFE | {safe_goal_qs:.2f} | {safe_goal_xgb:.2f} | {safe_wr:.1f}% | {safe_pr:.2f}% | {safe_ppm:.2f} |\n\n")
            else:
                f.write("### 🎯 BUTEURS\n")
                f.write("Aucune donnée buteurs disponible pour cette saison dans backtest_v4_features.csv.\n\n")

            if len(res_df) == 0 or n_matches == 0:
                f.write("Aucune donnée exploitable sur cette saison.\n\n")
                continue

            ast_el = float(res_df["qs_a"].quantile(0.99))
            ast_safe = float(res_df["qs_a"].quantile(0.95))
            pts_el = float(res_df["qs_p"].quantile(0.99))
            pts_safe = float(res_df["qs_p"].quantile(0.95))
            sog_el = float(res_df["sog_score"].quantile(0.99))
            sog_safe = float(res_df["sog_score"].quantile(0.95))

            def write_two_tiers(title: str, metric: str, score_col: str, t_el: float, t_safe: float) -> None:
                f.write(f"### {title}\n")
                f.write("| Catégorie | Seuil | Winrate | Pickrate | PPM |\n")
                f.write("|-----------|-------|---------|----------|-----|\n")
                for label, t in [("ELITE", t_el), ("SAFE", t_safe)]:
                    sub = res_df[res_df[score_col] >= t]
                    n = len(sub)
                    wr = float(sub[metric].mean()) * 100 if n > 0 else float("nan")
                    pr = (n / len(res_df)) * 100 if len(res_df) > 0 else 0.0
                    ppm = n / n_matches
                    f.write(f"| {label} | {t:.2f} | {wr:.1f}% | {pr:.2f}% | {ppm:.2f} |\n")
                f.write("\n")

            write_two_tiers("🅰️ PASSEURS", "assist", "qs_a", ast_el, ast_safe)
            write_two_tiers("🏆 POINTEURS", "point", "qs_p", pts_el, pts_safe)

            f.write("### 🔫 TIREURS (SOG ≥ 3)\n")
            f.write("| Catégorie | Seuil score | Winrate | Pickrate | PPM |\n")
            f.write("|-----------|-------------|---------|----------|-----|\n")
            for label, t in [("ELITE", sog_el), ("SAFE", sog_safe)]:
                sub = res_df[res_df["sog_score"] >= t]
                n = len(sub)
                wr = float(sub["hit_sog"].mean()) * 100 if n > 0 else float("nan")
                pr = (n / len(res_df)) * 100 if len(res_df) > 0 else 0.0
                ppm = n / n_matches
                f.write(f"| {label} | {t:.2f} | {wr:.1f}% | {pr:.2f}% | {ppm:.2f} |\n")
            f.write("\n")

        f.write("--- \n*Rapport généré automatiquement par l'Agent IA le " + pd.Timestamp.now().strftime("%Y-%m-%d") + "*\n")
            
    print("\n✅ Simulation terminée !")
    print("Rapport généré : simulation_report.md")

if __name__ == "__main__":
    main()
