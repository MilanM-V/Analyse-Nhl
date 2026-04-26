import sqlite3

conn = sqlite3.connect('bot_database.db')
c = conn.cursor()

# Check how many players have full data (l10_a, l10_pts, season_a, season_pts)
c.execute("""
    SELECT COUNT(*) FROM players 
    WHERE but IS NOT NULL AND but != ''
    AND l10_a IS NOT NULL AND season_a IS NOT NULL
""")
print(f"Players with full multi-market data: {c.fetchone()[0]}")

c.execute("""
    SELECT COUNT(*) FROM players 
    WHERE but IS NOT NULL AND but != ''
    AND (l10_a IS NULL OR season_a IS NULL)
""")
print(f"Players with ONLY goal data (legacy): {c.fetchone()[0]}")

# Game mode distribution
c.execute("SELECT game_mode, COUNT(*) FROM players WHERE but IS NOT NULL GROUP BY game_mode")
print(f"\nGame mode distribution: {c.fetchall()}")

# Picks distribution by date
c.execute("""
    SELECT date, COUNT(*) as total, 
           SUM(CASE WHEN but > 0 THEN 1 ELSE 0 END) as goals,
           SUM(CASE WHEN assist > 0 THEN 1 ELSE 0 END) as assists,
           SUM(CASE WHEN point > 0 THEN 1 ELSE 0 END) as points
    FROM players 
    WHERE but IS NOT NULL AND but != ''
    GROUP BY date ORDER BY date
""")
print("\nDate | Total | Goals | Assists | Points")
for row in c.fetchall():
    print(f"{row[0]} | {row[1]:>5} | {row[2]:>5} | {row[3]:>7} | {row[4]:>6}")

# Cotes distribution in picks tables
for table, res_col in [('picks', 'but'), ('picks_assists', 'assist'), ('picks_points', 'point')]:
    c.execute(f"""
        SELECT COUNT(*), 
               SUM(CASE WHEN {res_col} > 0 THEN 1 ELSE 0 END),
               AVG(cote),
               MIN(cote),
               MAX(cote)
        FROM {table} WHERE {res_col} IS NOT NULL AND {res_col} != ''
    """)
    row = c.fetchone()
    print(f"\n{table}: total={row[0]}, won={row[1]}, avg_cote={row[2]}, min={row[3]}, max={row[4]}")
    
    # WR
    if row[0] and row[0] > 0:
        wr = (row[1] / row[0]) * 100
        print(f"  Winrate: {wr:.1f}%")

# Verdict distribution in picks
c.execute("SELECT verdict, COUNT(*), SUM(CASE WHEN but > 0 THEN 1 ELSE 0 END) FROM picks WHERE but IS NOT NULL GROUP BY verdict")
print("\nGoal picks by verdict:")
for row in c.fetchall():
    wr = (row[2]/row[1]*100) if row[1] > 0 else 0
    print(f"  {row[0]}: {row[1]} picks, {row[2]} won ({wr:.1f}%)")

# Check pos column
c.execute("SELECT DISTINCT pos FROM players LIMIT 20")
print(f"\npos column values: ", end="")
try:
    print(c.fetchall())
except:
    print("NOT AVAILABLE")
    # Check if pos exists
    c.execute("PRAGMA table_info(players)")
    cols = c.fetchall()
    print("Available columns:", [col[1] for col in cols])

conn.close()
