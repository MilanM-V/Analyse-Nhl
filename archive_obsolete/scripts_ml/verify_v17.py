"""
Verification backtest V17 — Confirme que les nouveaux filtres buteurs
donnent bien le 39% WR attendu sur les donnees historiques.
"""
import sqlite3
import pandas as pd
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)
os.chdir(root)

def main():
    conn = sqlite3.connect("bot_database.db")
    
    df = pd.read_sql(
        "SELECT * FROM players WHERE but IS NOT NULL AND but != ''",
        conn
    )
    conn.close()
    
    # Conversions
    for c in ['ixg', 'hdcf', 'sog', 'atoi', 'season_g', 'score_but',
              'pp1', 'is_home', 'b2b', 'backup', 'but']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    
    df['scored'] = (df['but'] > 0).astype(int)
    
    print("=" * 60)
    print("BACKTEST V17 — Filtres Buteurs Optimises")
    print("=" * 60)
    
    # V17 Filtres
    QS_MIN = 10.50
    SG_MIN = 0.30
    SOG_MIN = 2.0
    HDCF_MIN = 2.0
    HOME_ONLY = True
    
    mask = (
        (df['score_but'] >= QS_MIN) &
        (df['season_g'] >= SG_MIN) &
        (df['sog'] >= SOG_MIN) &
        (df['hdcf'] >= HDCF_MIN) &
        (df['is_home'] == 1 if HOME_ONLY else True)
    )
    
    picks = df[mask]
    
    total = len(picks)
    won = picks['scored'].sum()
    wr = won / total * 100 if total > 0 else 0
    
    print(f"\n  Filtres: QS>={QS_MIN} | SG>={SG_MIN} | SOG>={SOG_MIN} | HDCF>={HDCF_MIN} | HOME={HOME_ONLY}")
    print(f"  Picks: {total} | Won: {won} | Winrate: {wr:.1f}%")
    
    # ROI estime
    avg_cote = 3.27
    roi = (wr/100 * avg_cote - 1) * 100
    print(f"  ROI estime (@{avg_cote}): {roi:+.1f}%")
    
    # Par jour
    print(f"\n  --- DETAIL PAR JOUR ---")
    for date in sorted(picks['date'].unique()):
        day = picks[picks['date'] == date]
        d_won = day['scored'].sum()
        d_total = len(day)
        d_wr = d_won / d_total * 100 if d_total > 0 else 0
        bar = "#" * d_won + "." * (d_total - d_won)
        print(f"    {date}  {d_won}/{d_total} ({d_wr:.0f}%) {bar}")
    
    # Comparaison avec l'ancien systeme (picks reels)
    print(f"\n  --- COMPARAISON ---")
    conn2 = sqlite3.connect("bot_database.db")
    
    old = pd.read_sql(
        "SELECT but, cote, verdict FROM picks WHERE but IS NOT NULL AND but != ''",
        conn2
    )
    conn2.close()
    
    old['but'] = pd.to_numeric(old['but'], errors='coerce').fillna(0)
    old_total = len(old)
    old_won = (old['but'] > 0).sum()
    old_wr = old_won / old_total * 100
    
    print(f"  ANCIEN (picks reels):  {old_won}/{old_total} ({old_wr:.1f}%)")
    print(f"  V17 (simulation):      {won}/{total} ({wr:.1f}%)")
    print(f"  Amelioration:          {wr - old_wr:+.1f} points")
    
    print("\n  OK.")

if __name__ == "__main__":
    main()
