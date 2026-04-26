import sqlite3

conn = sqlite3.connect('bot_database.db')
c = conn.cursor()

# Tables
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:", [r[0] for r in c.fetchall()])

# Row counts
for t in ['players', 'picks', 'picks_assists', 'picks_points', 'picks_parlays']:
    try:
        c.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"\n{t}: {c.fetchone()[0]} rows")
    except:
        print(f"\n{t}: NOT FOUND")

# Players with results
c.execute("SELECT COUNT(*) FROM players WHERE but IS NOT NULL AND but != ''")
print(f"\nPlayers with goal results: {c.fetchone()[0]}")
c.execute("SELECT COUNT(*) FROM players WHERE assist IS NOT NULL AND assist != ''")
print(f"Players with assist results: {c.fetchone()[0]}")
c.execute("SELECT COUNT(*) FROM players WHERE point IS NOT NULL AND point != ''")
print(f"Players with point results: {c.fetchone()[0]}")

# Date range
c.execute("SELECT MIN(date), MAX(date) FROM players")
print(f"\nDate range (players): {c.fetchone()}")

# Sample data
c.execute("SELECT * FROM players LIMIT 3")
cols = [d[0] for d in c.description]
print(f"\nPlayers columns ({len(cols)}): {cols}")
rows = c.fetchall()
for row in rows:
    print(dict(zip(cols, row)))

# Picks with cotes
for t in ['picks', 'picks_assists', 'picks_points']:
    c.execute(f"SELECT COUNT(*) FROM {t} WHERE cote IS NOT NULL AND cote > 0")
    total_cote = c.fetchone()[0]
    c.execute(f"SELECT COUNT(*) FROM {t}")
    total = c.fetchone()[0]
    print(f"\n{t}: {total_cote}/{total} with odds")
    c.execute(f"SELECT AVG(cote) FROM {t} WHERE cote IS NOT NULL AND cote > 0")
    avg = c.fetchone()[0]
    print(f"  Average odds: {avg}")

# Sample picks
print("\n--- Sample picks ---")
c.execute("SELECT date, joueur, equipe, adversaire, score, verdict, cote, but FROM picks LIMIT 5")
for row in c.fetchall():
    print(row)

# Check unique dates
c.execute("SELECT DISTINCT date FROM players ORDER BY date")
dates = [r[0] for r in c.fetchall()]
print(f"\nUnique dates ({len(dates)}): {dates}")

conn.close()
