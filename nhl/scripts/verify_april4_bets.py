import pandas as pd
import sqlite3
import sys

sys.path.insert(0, '.')
from nhl.scripts.walk_forward_backtest import load_all_data, walk_forward, FEATURES_BUT, FEATURES_AST

df_players, odds = load_all_data()
df_players_clean = df_players.drop_duplicates(subset=['date', 'joueur']).reset_index(drop=True)
odds_but_clean = odds['but'].drop_duplicates(subset=['date', 'joueur']).reset_index(drop=True)
odds_ast_clean = odds['ast'].drop_duplicates(subset=['date', 'joueur']).reset_index(drop=True)

df_but = walk_forward(df_players_clean, odds_but_clean, FEATURES_BUT, 'target_but', 'BUT', ev_threshold=0.05, adaptive_ev=True)
df_ast = walk_forward(df_players_clean, odds_ast_clean, FEATURES_AST, 'target_ast', 'AST', ev_threshold=0.05, adaptive_ev=True)

df_all = pd.concat([df_but, df_ast], ignore_index=True)
df_all['date'] = pd.to_datetime(df_all['date'])

april4 = df_all[df_all['date'] == '2026-04-04']
print('=== DETAIL EXACT DU 04 AVRIL 2026 (DEDUPLIQUE) ===')
for _, r in april4.iterrows():
    print(f"Joueur: {r['joueur']:<22} | Marche: {r['cat']} | Cote: {r['cote']:4.2f} | Proba: {r['proba']:.2f} | EV: {r['ev']*100:+5.1f}% | Mise: {r['mise']} U | Gain Net: {r['gain']:+5.2f} U | Gagne: {r['won']}")

# Verifier dans SQLite d'ou viennent ces cotes
conn = sqlite3.connect('nhl/bot_database.db')
print('\n=== ORIGINE DES COTES DANS PICKS ET PICKS_ASSISTS POUR LE 04 AVRIL ===')
names = tuple(april4['joueur'].tolist())
res_picks = pd.read_sql_query(f"SELECT date, joueur, cote, bookmaker, but, gain FROM picks WHERE date = '2026-04-04'", conn)
print('Picks (Buteurs) le 04 avril :')
print(res_picks)

res_picks_ast = pd.read_sql_query(f"SELECT date, joueur, cote, bookmaker, assist, gain FROM picks_assists WHERE date = '2026-04-04'", conn)
print('\nPicks (Assists) le 04 avril :')
print(res_picks_ast.drop_duplicates(subset=['joueur']))
conn.close()
