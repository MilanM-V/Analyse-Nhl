import sqlite3
import pandas as pd

conn = sqlite3.connect('nhl/bot_database.db')
print('=== J.T. MILLER IN PLAYERS (2026-04-04) ===')
df_p = pd.read_sql_query("SELECT * FROM players WHERE date = '2026-04-04' AND joueur LIKE '%Miller%'", conn)
print(f'Rows in players: {len(df_p)}')
print(df_p[['date', 'joueur', 'vague', 'equipe', 'adversaire', 'but', 'assist']])

print('\n=== TOTAL DUPLICATES IN PLAYERS BY (DATE, JOUEUR) ===')
df_all_p = pd.read_sql_query("SELECT date, joueur, count(*) as c FROM players GROUP BY date, joueur HAVING count(*) > 1", conn)
print(f'Duplicate (date, joueur) entries in players table: {len(df_all_p)}')
if len(df_all_p) > 0:
    print(df_all_p.head(10))

print('\n=== TOTAL DUPLICATES IN PICKS_ASSISTS BY (DATE, JOUEUR) ===')
df_all_a = pd.read_sql_query("SELECT date, joueur, count(*) as c FROM picks_assists GROUP BY date, joueur HAVING count(*) > 1", conn)
print(f'Duplicate (date, joueur) entries in picks_assists table: {len(df_all_a)}')
if len(df_all_a) > 0:
    print(df_all_a.head(10))

conn.close()
