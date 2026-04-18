"""
Backtest V17 HONNÊTE — Recalcul complet avec le moteur V17 actuel.

Prend TOUS les joueurs évalués dans la DB, les passe dans les scorers V17
actuels (GoalScorer, AssistScorer, PointScorer), applique les filtres V17
depuis settings.toml, et mesure le vrai winrate.

IMPORTANT : La table 'players' ne stocke pas Position ni oiSH.
On utilise des heuristiques pour les approcher :
  - Position : si season_g < 0.15 et atoi > 18 → probablement Défenseur
  - oiSH : non disponible, fixé à 10.0 (valeur neutre, pas de pénalité)
"""
import sqlite3
import os
import sys
import math

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)
os.chdir(root)

from core.predictor_v14 import GoalScorer, AssistScorer, PointScorer
from config.settings import cfg

DB_PATH = "bot_database.db"


def estimate_position(season_g: float, atoi: float) -> str:
    """Heuristique pour deviner la position depuis les stats.

    Les défenseurs ont typiquement :
    - Très peu de buts par match (< 0.15 G/GP)
    - Beaucoup de temps de glace (> 18 min)

    Args:
        season_g: Goals per game on the season.
        atoi: Average time on ice.

    Returns:
        'D' if likely a defenseman, 'F' otherwise.
    """
    if season_g < 0.15 and atoi > 18.0:
        return "D"
    return "F"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT * FROM players 
        WHERE but IS NOT NULL AND assist IS NOT NULL AND point IS NOT NULL
    """)
    rows = c.fetchall()
    print(f"Joueurs évalués avec résultats résolus : {len(rows)}")
    print(f"Moteur : V17 (GoalScorer + AssistScorer + PointScorer)")
    print(f"Filtres : settings.toml (buteurs.qs_min={cfg.thresholds.buteurs.qs_min}, "
          f"passeurs.qs_min={cfg.thresholds.passeurs.qs_min}, "
          f"pointeurs.qs_min={cfg.thresholds.pointeurs.qs_min})")
    print("=" * 70)

    # Compteurs
    stats = {
        "BUTS": {"picked": 0, "won": 0, "details": []},
        "ASSISTS": {"picked": 0, "won": 0, "details": []},
        "POINTS": {"picked": 0, "won": 0, "details": []},
    }

    for row in rows:
        # Reconstruire les dicts d'entrée pour les scorers
        v5_stats = {
            "oiSH": 10.0,  # Non disponible en DB, valeur neutre
            "PDO": float(row["pdo"] or 100.0),
            "GP": 50,  # Non disponible, valeur moyenne
            "G_GP": float(row["season_g"] or 0),
            "A_GP": float(row["season_a"] or 0),
            "Pts_GP": float(row["season_pts"] or 0),
            "Position": estimate_position(
                float(row["season_g"] or 0), float(row["atoi"] or 0)
            ),
        }

        p_form = {
            "L10_ixG_G": float(row["ixg"] or 0),
            "L10_iHDCF_G": float(row["hdcf"] or 0),
            "L10_SOG_G": float(row["sog"] or 0),
            "ATOI": float(row["atoi"] or 0),
            "L10_G_G": float(row["l10_g"] or 0),
            "L10_A_G": float(row["l10_a"] or 0),
            "L10_Pts_G": float(row["l10_pts"] or 0),
            "ConsecGoals": int(row["consec_goals"] or 0),
        }

        opp_stats = {
            "GA_G": float(row["ga_g"] or 2.7),
            "PK%": float(row["pk_pct"] or 80.0),
            "HDCA_G": float(row["hdca_g"] or 8.0),
            "SA_G": 30.0,  # Non disponible
            "CF_pct": float(row["cf_pct"] or 50.0),
        }

        is_pp1 = bool(row["pp1"])
        is_home = bool(row["is_home"])
        is_backup = bool(row["backup"])
        is_b2b = bool(row["b2b"])

        # Filtre ATOI minimum
        if p_form["ATOI"] < cfg.thresholds.general.atoi_min:
            continue

        # ═══ Recalcul QS avec le moteur V17 actuel ═══
        qs_but = GoalScorer(
            v5_stats, p_form, opp_stats, is_pp1, is_home,
            False, is_backup, is_b2b
        ).calculate_qs()

        qs_ast = AssistScorer(
            v5_stats, p_form, opp_stats, is_pp1, is_home,
            False, is_backup, is_b2b
        ).calculate_qs()

        qs_pts = PointScorer(
            v5_stats, p_form, opp_stats, is_pp1, is_home,
            False, is_backup, is_b2b
        ).calculate_qs()

        pos = v5_stats["Position"]
        season_g = v5_stats["G_GP"]
        season_a = v5_stats["A_GP"]
        season_pts = v5_stats["Pts_GP"]
        l10_sog = p_form["L10_SOG_G"]
        l10_hdcf = p_form["L10_iHDCF_G"]
        l10_a = p_form["L10_A_G"]
        l10_pts = p_form["L10_Pts_G"]

        # ═══ Filtre V17 BUTEURS ═══
        if (
            (is_home or not cfg.thresholds.buteurs.home_only)
            and pos not in ("D", "LD", "RD")
            and season_g >= cfg.thresholds.buteurs.season_g_min
            and l10_sog >= cfg.thresholds.buteurs.l10_sog_min
            and l10_hdcf >= cfg.thresholds.buteurs.l10_hdcf_min
            and qs_but >= cfg.thresholds.buteurs.qs_min
        ):
            stats["BUTS"]["picked"] += 1
            if row["but"] and int(row["but"]) > 0:
                stats["BUTS"]["won"] += 1
            stats["BUTS"]["details"].append({
                "joueur": row["joueur"], "date": row["date"],
                "qs": qs_but, "result": int(row["but"] or 0),
            })

        # ═══ Filtre V17 PASSEURS ═══
        if (
            (is_home or not cfg.thresholds.passeurs.home_only)
            and season_a >= cfg.thresholds.passeurs.season_a_min
            and l10_a >= cfg.thresholds.passeurs.l10_a_min
            and qs_ast >= cfg.thresholds.passeurs.qs_min
        ):
            stats["ASSISTS"]["picked"] += 1
            if row["assist"] and int(row["assist"]) > 0:
                stats["ASSISTS"]["won"] += 1
            stats["ASSISTS"]["details"].append({
                "joueur": row["joueur"], "date": row["date"],
                "qs": qs_ast, "result": int(row["assist"] or 0),
            })

        # ═══ Filtre V17 POINTEURS ═══
        if (
            (is_home or not cfg.thresholds.pointeurs.home_only)
            and season_pts >= cfg.thresholds.pointeurs.season_pts_min
            and l10_pts >= cfg.thresholds.pointeurs.l10_pts_min
            and qs_pts >= cfg.thresholds.pointeurs.qs_min
        ):
            stats["POINTS"]["picked"] += 1
            if row["point"] and int(row["point"]) > 0:
                stats["POINTS"]["won"] += 1
            stats["POINTS"]["details"].append({
                "joueur": row["joueur"], "date": row["date"],
                "qs": qs_pts, "result": int(row["point"] or 0),
            })

    # ═══ Résultats ═══
    print("\n" + "=" * 70)
    print("RÉSULTATS V17 — BACKTEST SUR TOUS LES JOUEURS ÉVALUÉS")
    print("=" * 70)

    for market, data in stats.items():
        picked = data["picked"]
        won = data["won"]
        if picked > 0:
            wr = won / picked * 100
            avg_qs = sum(d["qs"] for d in data["details"]) / len(data["details"])
            print(f"\n  {market}: {won}/{picked} ({wr:.1f}%) | QS moyen: {avg_qs:.2f}")

            # Par tranches de QS
            for qs_min in [10.0, 10.5, 11.0, 11.5, 12.0]:
                subset = [d for d in data["details"] if d["qs"] >= qs_min]
                if subset:
                    sub_won = sum(1 for d in subset if d["result"] > 0)
                    sub_wr = sub_won / len(subset) * 100
                    print(f"    QS >= {qs_min}: {sub_won}/{len(subset)} ({sub_wr:.1f}%)")
        else:
            print(f"\n  {market}: AUCUN PICK (filtres trop stricts)")

    # ═══ Comparaison avec les probas hardcodées ═══
    print("\n" + "=" * 70)
    print("COMPARAISON PROBAS HARDCODÉES VS RÉALITÉ V17")
    print("=" * 70)

    hardcoded = {"BUTS": 0.455, "ASSISTS": 0.554, "POINTS": 0.675}
    for market, data in stats.items():
        picked = data["picked"]
        won = data["won"]
        if picked > 0:
            real_wr = won / picked
            hc = hardcoded[market]
            delta = (real_wr - hc) * 100
            print(f"  {market}: Hardcodé={hc:.1%} | Réel V17={real_wr:.1%} | Écart={delta:+.1f}%")

    # ═══ Impact du seuil QS sur le winrate BUTEURS ═══
    if stats["BUTS"]["details"]:
        print("\n" + "=" * 70)
        print("OPTIMISATION SEUIL QS — BUTEURS")
        print("=" * 70)
        for qs_min in [10.0, 10.5, 11.0, 11.5, 12.0, 12.5]:
            subset = [d for d in stats["BUTS"]["details"] if d["qs"] >= qs_min]
            if len(subset) >= 5:
                sub_won = sum(1 for d in subset if d["result"] > 0)
                sub_wr = sub_won / len(subset) * 100
                print(f"  QS >= {qs_min:.1f}: {sub_won}/{len(subset)} ({sub_wr:.1f}%) "
                      f"{'[OK] RENTABLE si cote > ' + f'{1/sub_wr*100:.2f}' if sub_wr > 0 else '[X]'}")

    conn.close()


if __name__ == "__main__":
    main()
