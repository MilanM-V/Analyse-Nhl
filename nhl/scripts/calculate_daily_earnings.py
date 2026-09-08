import pandas as pd
import numpy as np
import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nhl.scripts.walk_forward_backtest import load_all_data, walk_forward, FEATURES_BUT, FEATURES_AST

df_players, odds = load_all_data()
df_but = walk_forward(df_players, odds['but'], FEATURES_BUT, 'target_but', 'BUT', ev_threshold=0.05, adaptive_ev=True)
df_ast = walk_forward(df_players, odds['ast'], FEATURES_AST, 'target_ast', 'AST', ev_threshold=0.05, adaptive_ev=True)

df_all = pd.concat([df_but, df_ast], ignore_index=True)
df_all['profit'] = df_all['gain']  # 'gain' is already net profit
df_all['date'] = pd.to_datetime(df_all['date'])

daily = df_all.groupby('date').agg({
    'joueur': 'count',
    'mise': 'sum',
    'gain': 'sum',
    'profit': 'sum'
}).rename(columns={'joueur': 'nb_paris', 'mise': 'mise_totale', 'gain': 'gain_total', 'profit': 'pnl'}).reset_index()

total_days_calendar = (df_all['date'].max() - df_all['date'].min()).days + 1
active_days = len(daily)

print('=== ANALYSE EMPIRIQUE DES GAINS QUOTIDIENS (100% OUT-OF-SAMPLE) ===')
d_min = df_all['date'].min().strftime('%Y-%m-%d')
d_max = df_all['date'].max().strftime('%Y-%m-%d')
print(f"Période évaluée : du {d_min} au {d_max} ({total_days_calendar} jours calendaires)")
print(f"Jours de compétition avec opportunités : {active_days} jours")
print(f"Jours sans opportunité validée : {total_days_calendar - active_days} jours")
print(f"Total des paris : {len(df_all)}")
print(f"Mise totale : {df_all['mise'].sum():.2f} U")
print(f"Profit net total : +{df_all['profit'].sum():.2f} U (+{df_all['profit'].sum():.2f} €)")
print(f"ROI Global : {(df_all['profit'].sum() / df_all['mise'].sum()) * 100:.1f}%\n")

pnl_mean_active = daily['pnl'].mean()
pnl_median_active = daily['pnl'].median()
std_active = daily['pnl'].std()

print("--- 1. RENDEMENT PAR JOUR DE MATCH (JOUR ACTIF) ---")
print(f"• Nombre moyen de paris par jour : {daily['nb_paris'].mean():.1f} paris (min {daily['nb_paris'].min()}, max {daily['nb_paris'].max()})")
print(f"• Capital moyen engagé par jour : {daily['mise_totale'].mean():.2f} U / jour ({daily['mise_totale'].mean():.2f} €)")
print(f"• Gain net moyen par jour actif : +{pnl_mean_active:.2f} U / jour (+{pnl_mean_active:.2f} € / jour)")
print(f"• Médiane journalière : {pnl_median_active:+.2f} U / jour")
print(f"• Volatilité journalière (Écart-type) : ±{std_active:.2f} U / jour")

pnl_mean_cal = df_all['profit'].sum() / total_days_calendar
print("\n--- 2. RENDEMENT LISSÉ PAR JOUR CALENDAIRE ---")
print(f"• Espérance journalière lissée : +{pnl_mean_cal:.2f} U / jour (+{pnl_mean_cal:.2f} € / jour)")
print(f"• Espérance mensuelle (30 jours) : +{pnl_mean_cal * 30:.2f} U / mois (+{pnl_mean_cal * 30:.2f} € / mois)")

pos = daily[daily['pnl'] > 0]
neg = daily[daily['pnl'] < 0]
zero = daily[daily['pnl'] == 0]

print("\n--- 3. DISTRIBUTION ET RÉALITÉ DE LA VARIANCE ---")
print(f"• Jours GAGNANTS : {len(pos)}/{active_days} ({len(pos)/active_days*100:.1f}%) — Gain moyen : +{pos['pnl'].mean():.2f} U (+{pos['pnl'].mean():.2f} €)")
print(f"• Jours PERDANTS : {len(neg)}/{active_days} ({len(neg)/active_days*100:.1f}%) — Perte moyenne : {neg['pnl'].mean():.2f} U ({neg['pnl'].mean():.2f} €)")
print(f"• Jours ÉQUILIBRE : {len(zero)}/{active_days} ({len(zero)/active_days*100:.1f}%)")
print(f"• Meilleure journée : +{daily['pnl'].max():.2f} U (+{daily['pnl'].max():.2f} €)")
print(f"• Pire journée (Drawdown max sur 24h) : {daily['pnl'].min():.2f} U ({daily['pnl'].min():.2f} €)")

print("\n--- 4. DÉTAIL CHRONOLOGIQUE DES JOURNÉES ---")
for _, r in daily.iterrows():
    sign = '+' if r['pnl'] > 0 else ''
    dt = r['date'].strftime('%Y-%m-%d')
    print(f"  {dt} | {int(r['nb_paris'])} paris | Mises: {r['mise_totale']:4.1f} U | P&L: {sign}{r['pnl']:5.2f} U")
