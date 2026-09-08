import pandas as pd
import numpy as np
import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nhl.scripts.walk_forward_backtest import load_all_data, walk_forward, FEATURES_BUT, FEATURES_AST

df_players, odds = load_all_data()

print(f"Lignes brutes dans df_players : {len(df_players)}")
# Déduplication stricte par joueur et par date
df_players_clean = df_players.drop_duplicates(subset=['date', 'joueur']).reset_index(drop=True)
print(f"Lignes après déduplication (date, joueur) : {len(df_players_clean)} (-{len(df_players) - len(df_players_clean)} doublons supprimés)")

odds_but_clean = odds['but'].drop_duplicates(subset=['date', 'joueur']).reset_index(drop=True)
odds_ast_clean = odds['ast'].drop_duplicates(subset=['date', 'joueur']).reset_index(drop=True)

df_but = walk_forward(df_players_clean, odds_but_clean, FEATURES_BUT, 'target_but', 'BUT', ev_threshold=0.05, adaptive_ev=True)
df_ast = walk_forward(df_players_clean, odds_ast_clean, FEATURES_AST, 'target_ast', 'AST', ev_threshold=0.05, adaptive_ev=True)

df_all = pd.concat([df_but, df_ast], ignore_index=True)
df_all['profit'] = df_all['gain']
df_all['date'] = pd.to_datetime(df_all['date'])

print("\n======================================================================")
print(" RÉSULTATS WALK-FORWARD CORRIGÉS (SANS AUCUN DOUBLON)")
print("======================================================================")
for cat in ['BUT', 'AST']:
    sub = df_all[df_all['cat'] == cat]
    n = len(sub)
    wins = int(sub['won'].sum())
    total_mise = sub['mise'].sum()
    total_profit = sub['profit'].sum()
    roi = (total_profit / total_mise * 100) if total_mise > 0 else 0
    wr = (wins / n * 100) if n > 0 else 0
    print(f"\n  [{cat}]")
    print(f"    Paris:        {n}")
    print(f"    Win Rate:     {wr:.1f}% ({wins}/{n})")
    print(f"    Cote Moy:     {sub['cote'].mean():.2f}")
    print(f"    Mise Totale:  {total_mise:.1f} U")
    print(f"    Profit Net:   {total_profit:+.2f} U ({total_profit:+.2f} €)")
    print(f"    ROI:          {roi:+.1f}%")

total_mise = df_all['mise'].sum()
total_profit = df_all['profit'].sum()
print("\n  --------------------------------------------------")
print("  GLOBAL RÉEL (DÉDUPLIQUÉ)")
print("  --------------------------------------------------")
print(f"    Paris Totaux: {len(df_all)}")
print(f"    Mise Totale:  {total_mise:.1f} U")
print(f"    Profit Net:   {total_profit:+.2f} U ({total_profit:+.2f} €)")
print(f"    ROI Global:   {(total_profit / total_mise * 100):+.1f}%")

print("\n--- DÉTAIL PAR JOUR DÉDUPLIQUÉ ---")
daily = df_all.groupby('date').agg({'joueur': 'count', 'mise': 'sum', 'profit': 'sum'}).rename(columns={'joueur': 'nb_paris', 'profit': 'pnl'}).reset_index()
for _, r in daily.iterrows():
    sign = '+' if r['pnl'] > 0 else ''
    dt = r['date'].strftime('%Y-%m-%d')
    print(f"  {dt} | {int(r['nb_paris']):2d} paris | Mises: {r['mise']:4.1f} U | P&L: {sign}{r['pnl']:5.2f} U")
