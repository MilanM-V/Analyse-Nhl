import sqlite3
import pandas as pd
import numpy as np
import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

conn = sqlite3.connect('nhl/bot_database.db')

print("======================================================================")
print(" 1. AUDIT TECHNIQUE DES COTES DANS bot_database.db")
print("======================================================================")
for table in ['picks', 'picks_assists', 'picks_points', 'players']:
    df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
    print(f"\nTable : {table} ({len(df)} enregistrements)")
    if 'cote' in df.columns:
        cotes = pd.to_numeric(df['cote'], errors='coerce')
        valid = cotes[cotes > 1.05]
        invalid = cotes[(cotes <= 1.05) | cotes.isna()]
        print(f"  • Cotes valides (> 1.05) : {len(valid)} ({len(valid)/len(df)*100:.1f}%)")
        print(f"  • Cotes invalides / nulles : {len(invalid)} ({len(invalid)/len(df)*100:.1f}%)")
        if len(valid) > 0:
            print(f"  • Min: {valid.min():.2f} | Max: {valid.max():.2f} | Moyenne: {valid.mean():.2f} | Médiane: {valid.median():.2f}")
            print(f"  • Top 5 valeurs les plus récurrentes :")
            for val, cnt in valid.value_counts().head(5).items():
                pct = (cnt / len(valid)) * 100
                print(f"      Cote {val:.2f} : {cnt} fois ({pct:.1f}%)")
    if 'date' in df.columns:
        print(f"  • Période : {df['date'].min()} à {df['date'].max()}")

print("\n======================================================================")
print(" 2. AUDIT APPROFONDI DE LA JOURNÉE ANORMALE DU 04 AVRIL 2026 (+23.34 U)")
print("======================================================================")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nhl.scripts.walk_forward_backtest import load_all_data, walk_forward, FEATURES_BUT, FEATURES_AST

df_players, odds = load_all_data()
df_but = walk_forward(df_players, odds['but'], FEATURES_BUT, 'target_but', 'BUT', ev_threshold=0.05, adaptive_ev=True)
df_ast = walk_forward(df_players, odds['ast'], FEATURES_AST, 'target_ast', 'AST', ev_threshold=0.05, adaptive_ev=True)

df_all = pd.concat([df_but, df_ast], ignore_index=True)
df_all['profit'] = df_all['gain']
df_all['date'] = pd.to_datetime(df_all['date'])

april4 = df_all[df_all['date'] == '2026-04-04']
print(f"Nombre de paris le 04 avril : {len(april4)}")
print(f"Mise totale le 04 avril : {april4['mise'].sum():.2f} U")
print(f"Profit net le 04 avril : +{april4['profit'].sum():.2f} U")
print(f"Gagnés : {april4['won'].sum()} / {len(april4)} (Win rate: {april4['won'].mean()*100:.1f}%)")

print("\nDétail complet des 17 paris du 04 avril :")
cols_show = ['joueur', 'cat', 'proba', 'cote', 'ev', 'mise', 'profit', 'won']
for _, r in april4[cols_show].iterrows():
    status = "GAGNÉ" if r['won'] else "PERDU"
    print(f"  {r['joueur']:<22} | {r['cat']:<3} | Proba: {r['proba']:.2f} | Cote: {r['cote']:4.2f} | EV: {r['ev']*100:+5.1f}% | Mise: {r['mise']:3.1f} U | P&L: {r['profit']:+6.2f} U | {status}")

print("\n======================================================================")
print(" 3. IMPACT DE L'EXCLUSION DU 04 AVRIL (TEST DE ROBUSTESSE HORS-OUTLIER)")
print("======================================================================")
without_april4 = df_all[df_all['date'] != '2026-04-04']
print(f"Nombre de paris sans le 04 avril : {len(without_april4)}")
print(f"Mises totales : {without_april4['mise'].sum():.2f} U")
print(f"Profit net sans le 04 avril : {without_april4['profit'].sum():+.2f} U ({without_april4['profit'].sum():+.2f} €)")
print(f"ROI sans le 04 avril : {(without_april4['profit'].sum() / without_april4['mise'].sum())*100:+.1f}%")

print("\n======================================================================")
print(" 4. AUDIT DE SÉLECTION & TIMING DES COTES")
print("======================================================================")
# Vérifier d'où viennent les cotes dans odds_df
# Dans walk_forward_backtest, odds_df est extrait de 'picks' et 'picks_assists'
# Mais est-ce que seuls les picks générés par l'ancien bot ont des cotes ?
q_picks_cnt = conn.execute("SELECT count(*) FROM picks WHERE cote IS NOT NULL").fetchone()[0]
q_ast_cnt = conn.execute("SELECT count(*) FROM picks_assists WHERE cote IS NOT NULL").fetchone()[0]
print(f"Picks avec cotes disponibles en base : {q_picks_cnt} (buteurs), {q_ast_cnt} (passeurs)")

# Comparaison avec les joueurs réels
total_players_evaluated = len(df_players)
print(f"Joueurs dans la table players : {total_players_evaluated}")
pct_with_odds = (q_picks_cnt + q_ast_cnt) / total_players_evaluated * 100
print(f"Ratio joueurs avec cotes réelles : {pct_with_odds:.1f}% des lignes de players")

conn.close()
