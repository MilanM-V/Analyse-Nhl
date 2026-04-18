"""
Backtest V16.5 — Analyse des performances sur les 2 dernières semaines.
Requête directe sur la DB SQLite pour vérifier les winrates réels.
"""
import sqlite3
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot_database.db")

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Tables disponibles
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in c.fetchall()]
    print(f"Tables: {tables}\n")

    # ==================== PICKS BUTS ====================
    print("=" * 70)
    print("MARCHÉ BUTS (table: picks)")
    print("=" * 70)

    c.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM picks")
    row = c.fetchone()
    print(f"  Plage: {row[0]} → {row[1]} | Total picks: {row[2]}")

    c.execute("SELECT COUNT(*) FROM picks WHERE but IS NOT NULL")
    resolved = c.fetchone()[0]
    print(f"  Résolus: {resolved}")

    # Global
    c.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN but > 0 THEN 1 ELSE 0 END) as won,
            verdict
        FROM picks 
        WHERE but IS NOT NULL AND but != ''
        GROUP BY verdict
    """)
    rows = c.fetchall()
    total_all = 0
    won_all = 0
    for r in rows:
        total_all += r["total"]
        won_all += r["won"]
        wr = (r["won"] / r["total"] * 100) if r["total"] > 0 else 0
        print(f"  [{r['verdict']}] {r['won']}✅ / {r['total']} ({wr:.1f}%)")
    
    if total_all > 0:
        print(f"  >> GLOBAL BUTS: {won_all}✅ / {total_all} ({won_all/total_all*100:.1f}%)")

    # 2 dernières semaines
    print("\n  --- 2 DERNIÈRES SEMAINES ---")
    c.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN but > 0 THEN 1 ELSE 0 END) as won,
            verdict
        FROM picks 
        WHERE but IS NOT NULL AND but != ''
        AND date >= date('now', '-14 days')
        GROUP BY verdict
    """)
    rows = c.fetchall()
    total_2w = 0
    won_2w = 0
    for r in rows:
        total_2w += r["total"]
        won_2w += r["won"]
        wr = (r["won"] / r["total"] * 100) if r["total"] > 0 else 0
        print(f"  [{r['verdict']}] {r['won']}✅ / {r['total']} ({wr:.1f}%)")
    
    if total_2w > 0:
        print(f"  >> BUTS 2 SEMAINES: {won_2w}✅ / {total_2w} ({won_2w/total_2w*100:.1f}%)")

    # ROI avec cotes
    print("\n  --- ROI (avec cotes réelles) ---")
    c.execute("""
        SELECT but, cote, verdict FROM picks 
        WHERE but IS NOT NULL AND but != ''
        AND date >= date('now', '-14 days')
    """)
    rows = c.fetchall()
    if rows:
        cotes_valides = [r["cote"] for r in rows if r["cote"] is not None]
        mean_cote = sum(cotes_valides) / len(cotes_valides) if cotes_valides else 1.85
        units = 0
        for r in rows:
            cote = r["cote"] if r["cote"] else mean_cote
            if r["but"] and int(r["but"]) > 0:
                units += (cote - 1)
            else:
                units -= 1
        print(f"  Units: {units:+.1f} U | ROI: {units/len(rows)*100:+.1f}% | Cote moy: {mean_cote:.2f}")

    # ==================== PICKS ASSISTS ====================
    print("\n" + "=" * 70)
    print("MARCHÉ ASSISTS (table: picks_assists)")
    print("=" * 70)

    c.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM picks_assists")
    row = c.fetchone()
    print(f"  Plage: {row[0]} → {row[1]} | Total picks: {row[2]}")

    c.execute("SELECT COUNT(*) FROM picks_assists WHERE assist IS NOT NULL")
    resolved = c.fetchone()[0]
    print(f"  Résolus: {resolved}")

    c.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN assist > 0 THEN 1 ELSE 0 END) as won,
            verdict
        FROM picks_assists 
        WHERE assist IS NOT NULL AND assist != ''
        GROUP BY verdict
    """)
    rows = c.fetchall()
    total_all = 0
    won_all = 0
    for r in rows:
        total_all += r["total"]
        won_all += r["won"]
        wr = (r["won"] / r["total"] * 100) if r["total"] > 0 else 0
        print(f"  [{r['verdict']}] {r['won']}✅ / {r['total']} ({wr:.1f}%)")
    if total_all > 0:
        print(f"  >> GLOBAL ASSISTS: {won_all}✅ / {total_all} ({won_all/total_all*100:.1f}%)")

    # 2 dernières semaines
    print("\n  --- 2 DERNIÈRES SEMAINES ---")
    c.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN assist > 0 THEN 1 ELSE 0 END) as won,
            verdict
        FROM picks_assists 
        WHERE assist IS NOT NULL AND assist != ''
        AND date >= date('now', '-14 days')
        GROUP BY verdict
    """)
    rows = c.fetchall()
    total_2w = 0
    won_2w = 0
    for r in rows:
        total_2w += r["total"]
        won_2w += r["won"]
        wr = (r["won"] / r["total"] * 100) if r["total"] > 0 else 0
        print(f"  [{r['verdict']}] {r['won']}✅ / {r['total']} ({wr:.1f}%)")
    if total_2w > 0:
        print(f"  >> ASSISTS 2 SEMAINES: {won_2w}✅ / {total_2w} ({won_2w/total_2w*100:.1f}%)")

    # ROI Assists
    print("\n  --- ROI (avec cotes réelles) ---")
    c.execute("""
        SELECT assist, cote, verdict FROM picks_assists 
        WHERE assist IS NOT NULL AND assist != ''
        AND date >= date('now', '-14 days')
    """)
    rows = c.fetchall()
    if rows:
        cotes_valides = [r["cote"] for r in rows if r["cote"] is not None]
        mean_cote = sum(cotes_valides) / len(cotes_valides) if cotes_valides else 1.85
        units = 0
        for r in rows:
            cote = r["cote"] if r["cote"] else mean_cote
            if r["assist"] and int(r["assist"]) > 0:
                units += (cote - 1)
            else:
                units -= 1
        print(f"  Units: {units:+.1f} U | ROI: {units/len(rows)*100:+.1f}% | Cote moy: {mean_cote:.2f}")

    # ==================== PICKS POINTS ====================
    print("\n" + "=" * 70)
    print("MARCHÉ POINTS (table: picks_points)")
    print("=" * 70)

    c.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM picks_points")
    row = c.fetchone()
    print(f"  Plage: {row[0]} → {row[1]} | Total picks: {row[2]}")

    c.execute("SELECT COUNT(*) FROM picks_points WHERE point IS NOT NULL")
    resolved = c.fetchone()[0]
    print(f"  Résolus: {resolved}")

    c.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN point > 0 THEN 1 ELSE 0 END) as won,
            verdict
        FROM picks_points 
        WHERE point IS NOT NULL AND point != ''
        GROUP BY verdict
    """)
    rows = c.fetchall()
    total_all = 0
    won_all = 0
    for r in rows:
        total_all += r["total"]
        won_all += r["won"]
        wr = (r["won"] / r["total"] * 100) if r["total"] > 0 else 0
        print(f"  [{r['verdict']}] {r['won']}✅ / {r['total']} ({wr:.1f}%)")
    if total_all > 0:
        print(f"  >> GLOBAL POINTS: {won_all}✅ / {total_all} ({won_all/total_all*100:.1f}%)")

    # 2 dernières semaines
    print("\n  --- 2 DERNIÈRES SEMAINES ---")
    c.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN point > 0 THEN 1 ELSE 0 END) as won,
            verdict
        FROM picks_points 
        WHERE point IS NOT NULL AND point != ''
        AND date >= date('now', '-14 days')
        GROUP BY verdict
    """)
    rows = c.fetchall()
    total_2w = 0
    won_2w = 0
    for r in rows:
        total_2w += r["total"]
        won_2w += r["won"]
        wr = (r["won"] / r["total"] * 100) if r["total"] > 0 else 0
        print(f"  [{r['verdict']}] {r['won']}✅ / {r['total']} ({wr:.1f}%)")
    if total_2w > 0:
        print(f"  >> POINTS 2 SEMAINES: {won_2w}✅ / {total_2w} ({won_2w/total_2w*100:.1f}%)")

    # ROI Points
    print("\n  --- ROI (avec cotes réelles) ---")
    c.execute("""
        SELECT point, cote, verdict FROM picks_points 
        WHERE point IS NOT NULL AND point != ''
        AND date >= date('now', '-14 days')
    """)
    rows = c.fetchall()
    if rows:
        cotes_valides = [r["cote"] for r in rows if r["cote"] is not None]
        mean_cote = sum(cotes_valides) / len(cotes_valides) if cotes_valides else 1.85
        units = 0
        for r in rows:
            cote = r["cote"] if r["cote"] else mean_cote
            if r["point"] and int(r["point"]) > 0:
                units += (cote - 1)
            else:
                units -= 1
        print(f"  Units: {units:+.1f} U | ROI: {units/len(rows)*100:+.1f}% | Cote moy: {mean_cote:.2f}")

    # ==================== DÉTAIL JOUR PAR JOUR ====================
    print("\n" + "=" * 70)
    print("DÉTAIL JOUR PAR JOUR (2 dernières semaines)")
    print("=" * 70)

    for table, col, label in [("picks", "but", "BUTS"), ("picks_assists", "assist", "ASSISTS"), ("picks_points", "point", "POINTS")]:
        print(f"\n  >>> {label}")
        c.execute(f"""
            SELECT date, 
                   COUNT(*) as total,
                   SUM(CASE WHEN {col} > 0 THEN 1 ELSE 0 END) as won
            FROM {table} 
            WHERE {col} IS NOT NULL AND {col} != ''
            AND date >= date('now', '-14 days')
            GROUP BY date
            ORDER BY date
        """)
        rows = c.fetchall()
        for r in rows:
            wr = (r["won"] / r["total"] * 100) if r["total"] > 0 else 0
            bar = "█" * r["won"] + "░" * (r["total"] - r["won"])
            print(f"    {r['date']}  {r['won']}/{r['total']} ({wr:.0f}%) {bar}")

    # ==================== JOUEURS NON RÉSOLUS ====================
    print("\n" + "=" * 70)
    print("PICKS NON RÉSOLUS (en attente)")
    print("=" * 70)
    for table, col in [("picks", "but"), ("picks_assists", "assist"), ("picks_points", "point")]:
        c.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL")
        pending = c.fetchone()[0]
        c.execute(f"SELECT COUNT(*) FROM {table}")
        total = c.fetchone()[0]
        print(f"  {table}: {pending} / {total} non résolus")

    conn.close()

if __name__ == "__main__":
    main()
