"""
Simulation V16.5 — Que se passerait-il si on avait appliqué les filtres V16.5
sur les picks des 2 dernières semaines ?

V16.5 supprime :
  - DÉFENSEUR (buteurs D bloqués)
  - TIREUR (catégorie supprimée)
  - Garde uniquement : ELITE, SAFE, PASSEUR, POINTEUR
"""
import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot_database.db")

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("=" * 70)
    print("SIMULATION V16.5 — Filtrage rétroactif sur les 2 dernières semaines")
    print("=" * 70)

    # ==================== BUTS ====================
    # V16.5 garde ELITE + SAFE, supprime DÉFENSEUR + TIREUR
    print("\n🔥 MARCHÉ BUTS (V16.5 = ELITE + SAFE uniquement)")
    
    c = conn.cursor()
    c.execute("""
        SELECT but, cote, verdict, joueur, date, equipe, adversaire
        FROM picks 
        WHERE but IS NOT NULL AND but != ''
        AND date >= date('now', '-14 days')
    """)
    rows = c.fetchall()
    
    # Tous les picks originaux
    all_buts = list(rows)
    # Filtrage V16.5 : seulement ELITE et SAFE
    v165_buts = [r for r in all_buts if r["verdict"] in ("ELITE", "SAFE")]
    
    print(f"  Picks originaux: {len(all_buts)} | Picks V16.5: {len(v165_buts)}")
    
    if v165_buts:
        won = sum(1 for r in v165_buts if r["but"] and int(r["but"]) > 0)
        wr = won / len(v165_buts) * 100
        print(f"  Winrate V16.5: {won}✅ / {len(v165_buts)} ({wr:.1f}%)")
        
        cotes_v = [r["cote"] for r in v165_buts if r["cote"]]
        mean_cote = sum(cotes_v) / len(cotes_v) if cotes_v else 3.0
        units = 0
        for r in v165_buts:
            cote = r["cote"] if r["cote"] else mean_cote
            if r["but"] and int(r["but"]) > 0:
                units += (cote - 1)
            else:
                units -= 1
        print(f"  Units: {units:+.1f} U | ROI: {units/len(v165_buts)*100:+.1f}% | Cote moy: {mean_cote:.2f}")
    
    # Comparatif par catégorie supprimée
    removed_buts = [r for r in all_buts if r["verdict"] in ("DÉFENSEUR", "TIREUR")]
    if removed_buts:
        won_removed = sum(1 for r in removed_buts if r["but"] and int(r["but"]) > 0)
        wr_removed = won_removed / len(removed_buts) * 100
        units_removed = 0
        for r in removed_buts:
            cote = r["cote"] if r["cote"] else 3.0
            if r["but"] and int(r["but"]) > 0:
                units_removed += (cote - 1)
            else:
                units_removed -= 1
        print(f"  >> Picks SUPPRIMÉS (DÉFENSEUR+TIREUR): {won_removed}/{len(removed_buts)} ({wr_removed:.1f}%) | {units_removed:+.1f} U")

    # ==================== ASSISTS ====================
    # V16.5 garde PASSEUR (qui remplace ELITE_PASSEUR, SAFE_PASSEUR)
    # Le filtre est désormais double : QS >= 10.75 ET proba >= 0.70
    print("\n🅰️  MARCHÉ ASSISTS (V16.5 = PASSEUR avec double filtre QS+IA)")
    
    c.execute("""
        SELECT assist, cote, verdict, joueur, date
        FROM picks_assists 
        WHERE assist IS NOT NULL AND assist != ''
        AND date >= date('now', '-14 days')
    """)
    rows = c.fetchall()
    all_ast = list(rows)
    
    # Dans la DB actuelle, les anciens picks utilisent ELITE_PASSEUR, SAFE_PASSEUR, PASSEUR
    # V16.5 unifierait tout en PASSEUR mais avec des seuils plus stricts
    # On peut approximer en gardant les meilleurs (ELITE_PASSEUR ≈ ceux qui passeraient le double filtre)
    
    won_all = sum(1 for r in all_ast if r["assist"] and int(r["assist"]) > 0)
    print(f"  Picks originaux: {len(all_ast)} | Winrate: {won_all}/{len(all_ast)} ({won_all/len(all_ast)*100:.1f}%)")
    
    for verdict in ("ELITE_PASSEUR", "SAFE_PASSEUR", "PASSEUR"):
        subset = [r for r in all_ast if r["verdict"] == verdict]
        if subset:
            won_sub = sum(1 for r in subset if r["assist"] and int(r["assist"]) > 0)
            cotes_v = [r["cote"] for r in subset if r["cote"]]
            mean_c = sum(cotes_v) / len(cotes_v) if cotes_v else 1.9
            units_sub = 0
            for r in subset:
                cote = r["cote"] if r["cote"] else mean_c
                if r["assist"] and int(r["assist"]) > 0:
                    units_sub += (cote - 1)
                else:
                    units_sub -= 1
            print(f"    [{verdict}] {won_sub}/{len(subset)} ({won_sub/len(subset)*100:.1f}%) | {units_sub:+.1f} U")

    # ==================== POINTS ====================
    print("\n🏆 MARCHÉ POINTS (V16.5 = POINTEUR avec double filtre QS+IA)")
    
    c.execute("""
        SELECT point, cote, verdict, joueur, date
        FROM picks_points 
        WHERE point IS NOT NULL AND point != ''
        AND date >= date('now', '-14 days')
    """)
    rows = c.fetchall()
    all_pts = list(rows)
    
    won_all = sum(1 for r in all_pts if r["point"] and int(r["point"]) > 0)
    print(f"  Picks originaux: {len(all_pts)} | Winrate: {won_all}/{len(all_pts)} ({won_all/len(all_pts)*100:.1f}%)")
    
    for verdict in ("ELITE_POINTEUR", "SAFE_POINTEUR", "POINTEUR"):
        subset = [r for r in all_pts if r["verdict"] == verdict]
        if subset:
            won_sub = sum(1 for r in subset if r["point"] and int(r["point"]) > 0)
            cotes_v = [r["cote"] for r in subset if r["cote"]]
            mean_c = sum(cotes_v) / len(cotes_v) if cotes_v else 1.5
            units_sub = 0
            for r in subset:
                cote = r["cote"] if r["cote"] else mean_c
                if r["point"] and int(r["point"]) > 0:
                    units_sub += (cote - 1)
                else:
                    units_sub -= 1
            print(f"    [{verdict}] {won_sub}/{len(subset)} ({won_sub/len(subset)*100:.1f}%) | {units_sub:+.1f} U")

    # ==================== RÉSUMÉ FINAL ====================
    print("\n" + "=" * 70)
    print("RÉSUMÉ COMPARATIF : ANCIEN vs V16.5")
    print("=" * 70)
    
    # Ancien (tout confondu)
    c.execute("""
        SELECT but, cote FROM picks 
        WHERE but IS NOT NULL AND but != '' AND date >= date('now', '-14 days')
    """)
    old_buts = c.fetchall()
    c.execute("""
        SELECT assist, cote FROM picks_assists 
        WHERE assist IS NOT NULL AND assist != '' AND date >= date('now', '-14 days')
    """)
    old_asts = c.fetchall()
    c.execute("""
        SELECT point, cote FROM picks_points 
        WHERE point IS NOT NULL AND point != '' AND date >= date('now', '-14 days')
    """)
    old_pts = c.fetchall()
    
    total_old = len(old_buts) + len(old_asts) + len(old_pts)
    won_old = sum(1 for r in old_buts if r[0] and int(r[0]) > 0) + \
              sum(1 for r in old_asts if r[0] and int(r[0]) > 0) + \
              sum(1 for r in old_pts if r[0] and int(r[0]) > 0)
    
    units_old = 0
    for r in old_buts:
        cote = r[1] if r[1] else 3.0
        units_old += (cote - 1) if r[0] and int(r[0]) > 0 else -1
    for r in old_asts:
        cote = r[1] if r[1] else 1.9
        units_old += (cote - 1) if r[0] and int(r[0]) > 0 else -1
    for r in old_pts:
        cote = r[1] if r[1] else 1.5
        units_old += (cote - 1) if r[0] and int(r[0]) > 0 else -1
    
    print(f"  ANCIEN: {won_old}/{total_old} ({won_old/total_old*100:.1f}%) | {units_old:+.1f} U | ROI: {units_old/total_old*100:+.1f}%")
    
    # V16.5 (filtré) - Buts: ELITE+SAFE only
    v165_total = len(v165_buts)
    v165_won = sum(1 for r in v165_buts if r["but"] and int(r["but"]) > 0) if v165_buts else 0
    v165_units = 0
    for r in v165_buts:
        cote = r["cote"] if r["cote"] else 3.0
        v165_units += (cote - 1) if r["but"] and int(r["but"]) > 0 else -1
    
    # Pour assists et points on garde tout (car la DB n'a pas les QS/probas pour re-filtrer)
    v165_total += len(old_asts) + len(old_pts)
    v165_won += sum(1 for r in old_asts if r[0] and int(r[0]) > 0) + sum(1 for r in old_pts if r[0] and int(r[0]) > 0)
    for r in old_asts:
        cote = r[1] if r[1] else 1.9
        v165_units += (cote - 1) if r[0] and int(r[0]) > 0 else -1
    for r in old_pts:
        cote = r[1] if r[1] else 1.5
        v165_units += (cote - 1) if r[0] and int(r[0]) > 0 else -1
    
    print(f"  V16.5:  {v165_won}/{v165_total} ({v165_won/v165_total*100:.1f}%) | {v165_units:+.1f} U | ROI: {v165_units/v165_total*100:+.1f}%")
    
    delta_units = v165_units - units_old
    print(f"\n  >> IMPACT V16.5: {delta_units:+.1f} U gagnées par le filtrage")

    conn.close()

if __name__ == "__main__":
    main()
