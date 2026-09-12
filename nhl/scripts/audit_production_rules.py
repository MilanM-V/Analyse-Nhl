import pandas as pd
import numpy as np
import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nhl.scripts.walk_forward_backtest import load_all_data, walk_forward, FEATURES_BUT, FEATURES_AST

df_players, odds = load_all_data()

# 1. Déduplication stricte
df_clean = df_players.drop_duplicates(subset=['date', 'joueur']).reset_index(drop=True)
odds_but_clean = odds['but'].drop_duplicates(subset=['date', 'joueur']).reset_index(drop=True)
odds_ast_clean = odds['ast'].drop_duplicates(subset=['date', 'joueur']).reset_index(drop=True)

# 2. Filtrage des défenseurs pour le marché Buteurs (Règle stricte de production market_filter.py)
# Dans df_clean, vérifions la colonne position
print("Colonnes disponibles dans df_clean :", [c for c in df_clean.columns if 'pos' in c.lower() or 'atoi' in c.lower()])
# Si position existe :
has_pos = 'position' in df_clean.columns
if has_pos:
    df_forwards_only = df_clean[~df_clean['position'].isin(['D', 'LD', 'RD'])].copy()
    print(f"Filtrage Buteurs : {len(df_forwards_only)} attaquants vs {len(df_clean)} joueurs totaux")
else:
    # Si position n'est pas dans players, récupérons-la depuis skaters_all ou historical_players
    df_sk = pd.read_csv('nhl/data/skaters.csv', usecols=['name', 'position']).drop_duplicates(subset=['name'])
    df_sk = df_sk.rename(columns={'name': 'joueur'})
    df_clean = df_clean.merge(df_sk, on='joueur', how='left')
    df_forwards_only = df_clean[df_clean['position'] != 'D'].copy()
    print(f"Filtrage Buteurs : {len(df_forwards_only)} attaquants identifiés sur {len(df_clean)} joueurs")

# Exécution du walk-forward strictement conforme à la production
df_but = walk_forward(df_forwards_only, odds_but_clean, FEATURES_BUT, 'target_but', 'BUT', ev_threshold=0.05, adaptive_ev=True)
df_ast = walk_forward(df_clean, odds_ast_clean, FEATURES_AST, 'target_ast', 'AST', ev_threshold=0.05, adaptive_ev=True)

df_all = pd.concat([df_but, df_ast], ignore_index=True)
df_all['profit'] = df_all['gain']
df_all['date'] = pd.to_datetime(df_all['date'])

print("\n======================================================================")
print(" RÉSULTAT DU BACKTEST APRÈS APPLICATION DES VRAIES RÈGLES DE PRODUCTION")
print(" (Déduplication + Exclusion stricte des défenseurs sur les Buteurs)")
print("======================================================================")
for cat in ['BUT', 'AST']:
    sub = df_all[df_all['cat'] == cat]
    n = len(sub)
    wins = int(sub['won'].sum()) if n > 0 else 0
    total_mise = sub['mise'].sum() if n > 0 else 0
    total_profit = sub['profit'].sum() if n > 0 else 0
    roi = (total_profit / total_mise * 100) if total_mise > 0 else 0
    wr = (wins / n * 100) if n > 0 else 0
    print(f"\n  [{cat}]")
    print(f"    Paris :        {n}")
    print(f"    Win Rate :     {wr:.1f}% ({wins}/{n})")
    print(f"    Cote Moyenne : {sub['cote'].mean():.2f}" if n > 0 else "    Cote Moyenne : N/A")
    print(f"    Mise Totale :  {total_mise:.1f} U")
    print(f"    Profit Net :   {total_profit:+.2f} U ({total_profit:+.2f} €)")
    print(f"    ROI :          {roi:+.1f}%")

total_mise = df_all['mise'].sum()
total_profit = df_all['profit'].sum()
print("\n  --------------------------------------------------")
print("  TOTAL GLOBAL PRODUCTION-READY")
print("  --------------------------------------------------")
print(f"    Paris Totaux : {len(df_all)}")
print(f"    Mise Totale :  {total_mise:.1f} U")
print(f"    Profit Net :   {total_profit:+.2f} U ({total_profit:+.2f} €)")
print(f"    ROI Global :   {(total_profit / total_mise * 100):+.1f}%")

print("\nDétail par jour :")
daily = df_all.groupby('date').agg({'joueur': 'count', 'mise': 'sum', 'profit': 'sum'}).rename(columns={'joueur': 'nb_paris', 'profit': 'pnl'}).reset_index()
for _, r in daily.iterrows():
    sign = '+' if r['pnl'] > 0 else ''
    dt = r['date'].strftime('%Y-%m-%d')
    print(f"  {dt} | {int(r['nb_paris']):2d} paris | Mises: {r['mise']:4.1f} U | P&L: {sign}{r['pnl']:5.2f} U")
