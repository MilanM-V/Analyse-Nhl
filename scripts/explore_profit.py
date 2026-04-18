"""
EXPLORATION PROFIT + COMBINÉS — Optimiser le GAIN (pas juste le WR).

Analyse :
  1. ROI par config (WR × cotes) au lieu de WR seul
  2. Simulation de combinés intra-vague (parlays 2-3 legs)
  3. Impact de la sélectivité sur la rentabilité
"""
import sqlite3
import os
import sys
from itertools import combinations
from collections import defaultdict

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)
os.chdir(root)

DB_PATH = "bot_database.db"


def section(title):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # ═══════════════════════════════════════════════════
    # 1. RÉCUPÉRER LES COTES RÉELLES DEPUIS LES TABLES PICKS
    # ═══════════════════════════════════════════════════
    section("DONNEES DISPONIBLES")

    # On a les cotes dans picks/picks_assists/picks_points mais PAS dans players
    # On va donc travailler avec les tables picks pour le ROI
    markets = {}
    for tbl, col, label in [
        ("picks", "but", "BUTS"),
        ("picks_assists", "assist", "ASSISTS"),
        ("picks_points", "point", "POINTS"),
    ]:
        c.execute(f"""
            SELECT joueur, equipe, adversaire, date, vague, score, verdict,
                   {col} as result, cote, is_home, pp1, backup, b2b
            FROM {tbl}
            WHERE {col} IS NOT NULL
        """)
        rows = [dict(r) for r in c.fetchall()]
        markets[label] = rows
        with_cote = sum(1 for r in rows if r["cote"])
        print(f"  {label}: {len(rows)} picks resolus, {with_cote} avec cote")

    # Pour le backtest profit avec les données players (plus riches)
    c.execute("""SELECT * FROM players WHERE but IS NOT NULL AND assist IS NOT NULL AND point IS NOT NULL AND atoi >= 13.0""")
    all_players = [dict(r) for r in c.fetchall()]
    print(f"\n  Table players: {len(all_players)} joueurs resolus")

    # ═══════════════════════════════════════════════════
    # 2. ROI PAR CONFIG — en utilisant les cotes réelles
    # ═══════════════════════════════════════════════════
    section("ROI RÉEL (avec cotes) — PICKS EXISTANTS")

    for label, rows in markets.items():
        if not rows:
            continue

        cotes_valides = [r["cote"] for r in rows if r["cote"] and r["cote"] > 1.0]
        mean_cote = sum(cotes_valides) / len(cotes_valides) if cotes_valides else 1.85

        total = len(rows)
        won = sum(1 for r in rows if r["result"] and int(r["result"]) > 0)
        units = 0
        for r in rows:
            cote = r["cote"] if r["cote"] and r["cote"] > 1.0 else mean_cote
            if r["result"] and int(r["result"]) > 0:
                units += (cote - 1)
            else:
                units -= 1

        wr = won / total * 100 if total > 0 else 0
        roi = units / total * 100 if total > 0 else 0
        print(f"\n  {label}: {won}/{total} ({wr:.1f}%) | {units:+.1f} U | ROI: {roi:+.1f}% | Cote moy: {mean_cote:.2f}")

        # Par tranche de cote
        print(f"    Par tranche de cote:")
        for cote_min, cote_max in [(1.0, 1.50), (1.50, 1.80), (1.80, 2.20), (2.20, 3.00), (3.00, 5.00), (5.00, 99)]:
            subset = [r for r in rows if r["cote"] and cote_min <= r["cote"] < cote_max]
            if len(subset) >= 5:
                sub_won = sum(1 for r in subset if r["result"] and int(r["result"]) > 0)
                sub_units = sum((r["cote"] - 1) if (r["result"] and int(r["result"]) > 0) else -1 for r in subset)
                sub_wr = sub_won / len(subset) * 100
                sub_roi = sub_units / len(subset) * 100
                avg_c = sum(r["cote"] for r in subset) / len(subset)
                print(f"      Cote {cote_min:.1f}-{cote_max:.1f}: {sub_won}/{len(subset)} ({sub_wr:.1f}%) | {sub_units:+.1f} U ({sub_roi:+.1f}%) | Avg: {avg_c:.2f}")

    # ═══════════════════════════════════════════════════
    # 3. BACKTEST PROFIT — Filtres optimisés sur table players
    # ═══════════════════════════════════════════════════
    section("BACKTEST PROFIT — Filtres optimises (sans cotes, estimation)")

    # On n'a pas les cotes dans la table players, mais on peut estimer
    # le ROI en utilisant les cotes moyennes des tables picks
    avg_cotes = {"BUTS": 3.20, "ASSISTS": 1.94, "POINTS": 1.50}

    configs = {
        "BUTS": [
            ("V17 actuel (SG>=0.4+SOG>=3+HDCF>=2+QS)", 
             lambda r, qs=None: r["is_home"] and float(r["season_g"] or 0) >= 0.4 and float(r["sog"] or 0) >= 3.0 and float(r["hdcf"] or 0) >= 2.0),
            ("OPTIMAL (SG>=0.4+SOG>=3+HDCF>=2.5+GA>=2.8)",
             lambda r, qs=None: r["is_home"] and float(r["season_g"] or 0) >= 0.4 and float(r["sog"] or 0) >= 3.0 and float(r["hdcf"] or 0) >= 2.5 and float(r["ga_g"] or 0) >= 2.8),
            ("AGRESSIF (SG>=0.3+HDCF>=2+GA>=2.8)",
             lambda r, qs=None: r["is_home"] and float(r["season_g"] or 0) >= 0.3 and float(r["hdcf"] or 0) >= 2.0 and float(r["ga_g"] or 0) >= 2.8),
            ("ULTRA SELECT (SG>=0.4+HDCF>=2.5+iXG>=0.45+GA>=2.8)",
             lambda r, qs=None: r["is_home"] and float(r["season_g"] or 0) >= 0.4 and float(r["hdcf"] or 0) >= 2.5 and float(r["ixg"] or 0) >= 0.45 and float(r["ga_g"] or 0) >= 2.8),
        ],
        "ASSISTS": [
            ("V17 actuel (SA>=0.5+L10A>=0.8)",
             lambda r, qs=None: r["is_home"] and float(r["season_a"] or 0) >= 0.5 and float(r["l10_a"] or 0) >= 0.8),
            ("OPTIMAL (SA>=0.5+L10A>=0.8+ATOI>=18+GA>=2.8)",
             lambda r, qs=None: r["is_home"] and float(r["season_a"] or 0) >= 0.5 and float(r["l10_a"] or 0) >= 0.8 and float(r["atoi"] or 0) >= 18 and float(r["ga_g"] or 0) >= 2.8),
            ("VOLUME (SA>=0.4+L10A>=0.6+ATOI>=18+GA>=2.8)",
             lambda r, qs=None: r["is_home"] and float(r["season_a"] or 0) >= 0.4 and float(r["l10_a"] or 0) >= 0.6 and float(r["atoi"] or 0) >= 18 and float(r["ga_g"] or 0) >= 2.8),
        ],
        "POINTS": [
            ("V17 actuel (SP>=0.8+L10P>=0.4)",
             lambda r, qs=None: r["is_home"] and float(r["season_pts"] or 0) >= 0.8 and float(r["l10_pts"] or 0) >= 0.4),
            ("OPTIMAL (SP>=0.9+L10P>=0.8+ATOI>=16+GA>=2.8)",
             lambda r, qs=None: r["is_home"] and float(r["season_pts"] or 0) >= 0.9 and float(r["l10_pts"] or 0) >= 0.8 and float(r["atoi"] or 0) >= 16 and float(r["ga_g"] or 0) >= 2.8),
            ("SAFE (SP>=0.9+L10P>=0.8)",
             lambda r, qs=None: r["is_home"] and float(r["season_pts"] or 0) >= 0.9 and float(r["l10_pts"] or 0) >= 0.8),
            ("ULTRA VOLUME (SP>=0.7+L10P>=0.6)",
             lambda r, qs=None: r["is_home"] and float(r["season_pts"] or 0) >= 0.7 and float(r["l10_pts"] or 0) >= 0.6),
        ],
    }

    result_cols = {"BUTS": "but", "ASSISTS": "assist", "POINTS": "point"}

    for market, config_list in configs.items():
        print(f"\n  --- {market} (cote estimee: {avg_cotes[market]:.2f}) ---")
        col = result_cols[market]
        est_cote = avg_cotes[market]

        for name, filt in config_list:
            subset = [r for r in all_players if filt(r)]
            if not subset:
                print(f"    {name}: 0 picks")
                continue

            total = len(subset)
            won = sum(1 for r in subset if r[col] and int(r[col]) > 0)
            wr = won / total * 100
            units = won * (est_cote - 1) - (total - won) * 1
            roi = units / total * 100
            picks_per_day = total / 19

            print(f"    {name}")
            print(f"      WR={wr:.1f}% ({won}/{total}) | {units:+.1f}U ({roi:+.1f}%) | ~{picks_per_day:.1f}/jour")

    # ═══════════════════════════════════════════════════
    # 4. SIMULATION COMBINÉS (PARLAYS)
    # ═══════════════════════════════════════════════════
    section("SIMULATION COMBINES (PARLAYS)")

    # Pour les combinés, on doit regrouper par date+vague
    # et chercher les paires/triples de bons picks sur des matchs différents

    # POINTS est le marché le plus fiable, explore les combis Points
    print("\n  --- Combinés POINTS (2 legs) sur memes dates ---")

    # Regrouper les joueurs par date
    by_date = defaultdict(list)
    for r in all_players:
        # Filtre optimal POINTS
        if (r["is_home"]
            and float(r["season_pts"] or 0) >= 0.90
            and float(r["l10_pts"] or 0) >= 0.80
            and float(r["atoi"] or 0) >= 16
            and float(r["ga_g"] or 0) >= 2.8):
            by_date[r["date"]].append(r)

    total_parlays_2 = 0
    won_parlays_2 = 0
    total_parlays_3 = 0
    won_parlays_3 = 0
    est_cote_pts = 1.50

    for date, players in by_date.items():
        # Grouper par match (equipe)
        by_match = defaultdict(list)
        for p in players:
            match_key = f"{p['equipe']}-{p['adversaire']}"
            by_match[match_key].append(p)

        match_keys = list(by_match.keys())

        # Combinés 2 legs : 1 joueur de chaque match différent
        if len(match_keys) >= 2:
            for m1, m2 in combinations(match_keys, 2):
                for p1 in by_match[m1]:
                    for p2 in by_match[m2]:
                        total_parlays_2 += 1
                        res1 = p1["point"] and int(p1["point"]) > 0
                        res2 = p2["point"] and int(p2["point"]) > 0
                        if res1 and res2:
                            won_parlays_2 += 1

        # Combinés 3 legs
        if len(match_keys) >= 3:
            for m1, m2, m3 in combinations(match_keys, 3):
                # Prendre le meilleur joueur de chaque match
                best1 = max(by_match[m1], key=lambda p: float(p["season_pts"] or 0))
                best2 = max(by_match[m2], key=lambda p: float(p["season_pts"] or 0))
                best3 = max(by_match[m3], key=lambda p: float(p["season_pts"] or 0))
                total_parlays_3 += 1
                if all(p["point"] and int(p["point"]) > 0 for p in [best1, best2, best3]):
                    won_parlays_3 += 1

    if total_parlays_2 > 0:
        wr_2 = won_parlays_2 / total_parlays_2 * 100
        cote_combo_2 = est_cote_pts ** 2
        units_2 = won_parlays_2 * (cote_combo_2 - 1) - (total_parlays_2 - won_parlays_2)
        roi_2 = units_2 / total_parlays_2 * 100
        print(f"  Double (2 legs POINTS): {won_parlays_2}/{total_parlays_2} ({wr_2:.1f}%)")
        print(f"    Cote combo estimee: {cote_combo_2:.2f} | {units_2:+.1f}U ({roi_2:+.1f}%)")
        print(f"    Breakeven: {1/cote_combo_2*100:.1f}%")

    if total_parlays_3 > 0:
        wr_3 = won_parlays_3 / total_parlays_3 * 100
        cote_combo_3 = est_cote_pts ** 3
        units_3 = won_parlays_3 * (cote_combo_3 - 1) - (total_parlays_3 - won_parlays_3)
        roi_3 = units_3 / total_parlays_3 * 100
        print(f"\n  Triple (3 legs POINTS best-of-match): {won_parlays_3}/{total_parlays_3} ({wr_3:.1f}%)")
        print(f"    Cote combo estimee: {cote_combo_3:.2f} | {units_3:+.1f}U ({roi_3:+.1f}%)")
        print(f"    Breakeven: {1/cote_combo_3*100:.1f}%")

    # COMBINÉ MIXTE : 1 POINT + 1 ASSIST
    print("\n  --- Combinés MIXTES (1 Point + 1 Assist, matchs differents) ---")

    pts_by_date = defaultdict(list)
    ast_by_date = defaultdict(list)

    for r in all_players:
        if (r["is_home"] and float(r["season_pts"] or 0) >= 0.90
            and float(r["l10_pts"] or 0) >= 0.80 and float(r["atoi"] or 0) >= 16
            and float(r["ga_g"] or 0) >= 2.8):
            pts_by_date[r["date"]].append(r)

        if (r["is_home"] and float(r["season_a"] or 0) >= 0.50
            and float(r["l10_a"] or 0) >= 0.80 and float(r["atoi"] or 0) >= 18
            and float(r["ga_g"] or 0) >= 2.8):
            ast_by_date[r["date"]].append(r)

    total_mix = 0
    won_mix = 0

    for date in set(pts_by_date.keys()) & set(ast_by_date.keys()):
        for p_pt in pts_by_date[date]:
            for p_as in ast_by_date[date]:
                # Matchs différents seulement
                if p_pt["equipe"] != p_as["equipe"] and p_pt["adversaire"] != p_as["equipe"]:
                    total_mix += 1
                    res_pt = p_pt["point"] and int(p_pt["point"]) > 0
                    res_as = p_as["assist"] and int(p_as["assist"]) > 0
                    if res_pt and res_as:
                        won_mix += 1

    if total_mix > 0:
        wr_mix = won_mix / total_mix * 100
        cote_mix = 1.50 * 1.94  # Point × Assist cotes moyennes
        units_mix = won_mix * (cote_mix - 1) - (total_mix - won_mix)
        roi_mix = units_mix / total_mix * 100
        print(f"  Point+Assist combo: {won_mix}/{total_mix} ({wr_mix:.1f}%)")
        print(f"    Cote combo estimee: {cote_mix:.2f} | {units_mix:+.1f}U ({roi_mix:+.1f}%)")
        print(f"    Breakeven: {1/cote_mix*100:.1f}%")

    # ═══════════════════════════════════════════════════
    # 5. STRATÉGIE DE MISE OPTIMALE
    # ═══════════════════════════════════════════════════
    section("STRATEGIE DE MISE OPTIMALE")

    print("""
  Pour maximiser le GAIN (pas juste le WR), il faut :

  1. MISER PLUS sur les paris avec le plus d'edge (EV = WR × cote - 1)
     - Plus l'EV est haute, plus la mise doit etre grosse (Kelly)

  2. MISER MOINS sur les paris a faible cote meme avec WR eleve
     - Points a 1.30 avec 70% WR = EV faible (0.70×1.30-1 = -0.09 = NEGATIF!)
     - Points a 1.60 avec 70% WR = EV correcte (0.70×1.60-1 = +0.12)

  3. Les COMBINES sont plus rentables SI les legs sont independants
     - 2 picks Points independants a 70% chacun = 49% combo
     - Cote combo 1.50² = 2.25 → EV = 0.49×2.25-1 = +0.10 (+10%)
     - MAIS les legs d'un meme match NE sont PAS independants !
""")

    # Calcul EV par marché avec les filtres optimaux
    print("  EV estimee par marche (filtres optimaux):")
    scenarios = [
        ("BUTS OPTIMAL",      0.445, 3.20, "HIGH RISK / HIGH REWARD"),
        ("ASSISTS OPTIMAL",   0.585, 1.94, "MOYEN"),
        ("POINTS OPTIMAL",    0.696, 1.50, "SAFE"),
        ("POINTS cote>=1.60", 0.696, 1.60, "SWEET SPOT"),
        ("COMBO 2x POINTS",   0.696**2, 1.50**2, "COMBO SAFE"),
        ("COMBO PT+AST",      0.696*0.585, 1.50*1.94, "COMBO MIXTE"),
    ]

    print(f"    {'Scenario':25s} | {'WR':>6s} | {'Cote':>5s} | {'EV':>7s} | {'Type'}")
    print(f"    {'-'*25}-+-{'-'*6}-+-{'-'*5}-+-{'-'*7}-+-{'-'*20}")
    for name, wr, cote, typ in scenarios:
        ev = wr * cote - 1
        ev_pct = ev * 100
        flag = "[+]" if ev > 0 else "[-]"
        print(f"    {name:25s} | {wr:.1%} | {cote:.2f} | {ev_pct:+.1f}%  | {flag} {typ}")

    # ═══════════════════════════════════════════════════
    # 6. MEILLEURE STRATÉGIE COMBINÉE PAR JOUR
    # ═══════════════════════════════════════════════════
    section("SIMULATION JOUR PAR JOUR — Meilleure strategie")

    # Simuler chaque jour : paris simples optimaux + meilleur combiné
    dates = sorted(set(r["date"] for r in all_players))

    simple_total_u = 0
    combo_total_u = 0
    simple_bets = 0
    combo_bets = 0

    for date in dates:
        day_players = [r for r in all_players if r["date"] == date]

        # Paris simples POINTS optimal
        pts_picks = [r for r in day_players if (
            r["is_home"] and float(r["season_pts"] or 0) >= 0.90
            and float(r["l10_pts"] or 0) >= 0.80
            and float(r["atoi"] or 0) >= 16 and float(r["ga_g"] or 0) >= 2.8
        )]

        day_simple_u = 0
        for p in pts_picks:
            simple_bets += 1
            if p["point"] and int(p["point"]) > 0:
                day_simple_u += (est_cote_pts - 1)
            else:
                day_simple_u -= 1
        simple_total_u += day_simple_u

        # Combiné 2 legs (best picks de matchs différents)
        by_match = defaultdict(list)
        for p in pts_picks:
            by_match[p["equipe"]].append(p)

        match_keys = list(by_match.keys())
        if len(match_keys) >= 2:
            # Prendre le meilleur par match
            bests = []
            for mk in match_keys:
                best = max(by_match[mk], key=lambda p: float(p["season_pts"] or 0))
                bests.append(best)

            # Toutes les paires
            for p1, p2 in combinations(bests, 2):
                combo_bets += 1
                r1 = p1["point"] and int(p1["point"]) > 0
                r2 = p2["point"] and int(p2["point"]) > 0
                if r1 and r2:
                    combo_total_u += (est_cote_pts ** 2 - 1)
                else:
                    combo_total_u -= 1

    print(f"\n  PARIS SIMPLES (Points optimal, 1U/pari):")
    print(f"    {simple_bets} paris | {simple_total_u:+.1f} U | ROI: {simple_total_u/max(1,simple_bets)*100:+.1f}%")

    print(f"\n  COMBINES 2 LEGS (Points optimal, 1U/combo):")
    if combo_bets > 0:
        print(f"    {combo_bets} combos | {combo_total_u:+.1f} U | ROI: {combo_total_u/combo_bets*100:+.1f}%")
    else:
        print(f"    0 combos possibles")

    # ═══════════════════════════════════════════════════
    # 7. LE SWEET SPOT : Filtrer par cote minimum
    # ═══════════════════════════════════════════════════
    section("FILTRAGE PAR COTE MINIMUM — Le Sweet Spot")

    for label, rows in markets.items():
        if not rows:
            continue

        print(f"\n  {label}:")
        for cote_min in [1.30, 1.40, 1.50, 1.60, 1.70, 1.80, 2.00, 2.50, 3.00]:
            subset = [r for r in rows if r["cote"] and r["cote"] >= cote_min]
            if len(subset) < 10:
                continue
            won = sum(1 for r in subset if r["result"] and int(r["result"]) > 0)
            units = sum(
                (r["cote"] - 1) if (r["result"] and int(r["result"]) > 0) else -1
                for r in subset
            )
            wr = won / len(subset) * 100
            roi = units / len(subset) * 100
            avg_c = sum(r["cote"] for r in subset) / len(subset)
            print(f"    Cote >= {cote_min:.2f}: {won}/{len(subset)} ({wr:.1f}%) | {units:+.1f}U ({roi:+.1f}%) | Avg: {avg_c:.2f}")

    conn.close()
    print("\n[FIN]")


if __name__ == "__main__":
    main()
