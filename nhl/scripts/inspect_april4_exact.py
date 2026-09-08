import sqlite3
import pandas as pd

conn = sqlite3.connect('nhl/bot_database.db')
names = ('Rasmus Andersson', 'Erik Karlsson', 'Dawson Mercer', 'Rasmus Dahlin', 'Darren Raddysh', 'Josh Morrissey')
names_str = "', '".join(names)
q = f"SELECT date, joueur, equipe, adversaire, but, assist, ixg, sog FROM players WHERE date = '2026-04-04' AND joueur IN ('{names_str}')"
df = pd.read_sql_query(q, conn)
print("=== PLAYERS IN PLAYERS TABLE ON 2026-04-04 ===")
print(df.drop_duplicates(subset=['joueur']))

print("\n=== PICKS IN PICKS TABLE ON 2026-04-04 ===")
q_picks = f"SELECT * FROM picks WHERE date = '2026-04-04'"
df_picks = pd.read_sql_query(q_picks, conn)
print(df_picks[['date', 'joueur', 'cote', 'but', 'gain', 'mise', 'score', 'consec_goals']])

conn.close()
