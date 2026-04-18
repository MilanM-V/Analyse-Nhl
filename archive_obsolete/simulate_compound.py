import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect('./bot_database.db')

df_b = pd.read_sql_query("SELECT * FROM picks WHERE but IS NOT NULL AND but != '' AND verdict IN ('ELITE', 'SAFE')", conn)
df_b['real_cote'] = pd.to_numeric(df_b['cote'], errors='coerce')
mc_b = round(df_b['real_cote'].mean(), 2) if pd.notna(df_b['real_cote'].mean()) else 2.50
df_b['cote_used'] = df_b['real_cote'].fillna(mc_b)
df_b['won'] = df_b['but'].astype(int).apply(lambda x: 1 if x > 0 else 0)
df_b['date'] = pd.to_datetime(df_b['date'])

df_a = pd.read_sql_query("SELECT * FROM picks_assists WHERE assist IS NOT NULL AND assist != ''", conn)
df_a['real_cote'] = pd.to_numeric(df_a['cote'], errors='coerce')
mc_a = round(df_a['real_cote'].mean(), 2) if pd.notna(df_a['real_cote'].mean()) else 1.90
df_a['cote_used'] = df_a['real_cote'].fillna(mc_a)
df_a['won'] = df_a['assist'].astype(int).apply(lambda x: 1 if x > 0 else 0)
df_a['adj_score'] = np.where(df_a['is_home'] == 1, df_a['score'], df_a['score'] - 1.0)
df_a = df_a[df_a['adj_score'] >= 10.25]
df_a['date'] = pd.to_datetime(df_a['date'])

conn.close()

df_bet = pd.concat([
    df_b[['date', 'joueur', 'cote_used', 'won']],
    df_a[['date', 'joueur', 'cote_used', 'won']]
]).sort_values('date')

RATIO = 0.70
bankroll = 10.0

print("=" * 75)
print(f"BANKROLL COMPOSEE 70% : 10 EUR de depart, on mise 70% chaque soir")
print("(Buteurs + Passeurs uniquement)")
print("=" * 75)

for date, group in df_bet.groupby(df_bet['date'].dt.date):
    n_picks = len(group)
    mise_totale = bankroll * RATIO
    reserve = bankroll * (1 - RATIO)
    mise_par_pick = mise_totale / n_picks
    
    retour = 0.0
    for _, row in group.iterrows():
        if row['won'] == 1:
            retour += mise_par_pick * row['cote_used']

    old_bankroll = bankroll
    bankroll = reserve + retour
    profit = bankroll - old_bankroll
    
    emoji = "+" if profit >= 0 else ""
    print(f"  {date} | {n_picks:>2} picks | Mise: {mise_totale:.2f}E | Retour: {retour:.2f}E | {emoji}{profit:.2f}E | Bankroll: {bankroll:.2f}E")

print(f"\n  DEPART:  10.00 EUR")
print(f"  FINAL:   {bankroll:.2f} EUR")
print(f"  PROFIT:  {bankroll - 10:+.2f} EUR")
print(f"  ROI:     {((bankroll - 10) / 10) * 100:+.1f}%")
