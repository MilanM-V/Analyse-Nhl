"""
scripts/clv_analysis.py — Analyse du Closing Line Value (CLV).

Le CLV mesure si nos prises sont en moyenne à une meilleure cote que la
cote de clôture. Un CLV > 0% est le signal le plus fiable d'un edge
dans les paris sportifs (bien plus fiable que le ROI à court terme).

Usage:
    python nhl/scripts/clv_analysis.py
"""
import sqlite3
import pandas as pd
import numpy as np
import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "bot_database.db")


def analyze_clv():
    """Analyse le CLV pour chaque marché avec test de significativité.

    Pour chaque marché (Buteurs, Passeurs, Pointeurs) :
    - Calcule le CLV moyen et médian
    - Effectue un test t de Student (H0: CLV moyen = 0)
    - Affiche l'évolution mensuelle pour détecter les tendances
    """
    conn = sqlite3.connect(DB_PATH)

    markets = [
        ("picks", "but", "BUTEURS"),
        ("picks_assists", "assist", "PASSEURS"),
        ("picks_points", "point", "POINTEURS"),
    ]

    print("=" * 70)
    print(" ANALYSE CLV (Closing Line Value) — Indicateur #1 d'Edge")
    print("=" * 70)
    print("\n Le CLV mesure si vous prenez systématiquement de meilleures")
    print(" cotes que le marché de clôture. CLV > 0% = edge probable.\n")

    for table, target_col, label in markets:
        query = f"""
            SELECT date, joueur, cote, closing_cote, {target_col} as result
            FROM {table}
            WHERE cote IS NOT NULL AND closing_cote IS NOT NULL
              AND cote > 1.05 AND closing_cote > 1.05
        """
        try:
            df = pd.read_sql(query, conn)
        except Exception:
            print(f"\n[{label}] Table ou colonnes manquantes. Skipping.")
            continue

        if df.empty or len(df) < 10:
            print(f"\n[{label}] Pas assez de données CLV ({len(df)} picks).")
            continue

        # CLV = (closing_implied - opening_implied) / opening_implied
        # Un CLV positif = la cote a BAISSÉ après notre prise = le marché
        # converge vers notre estimation = signal d'edge
        df['implied_open'] = 1.0 / df['cote']
        df['implied_close'] = 1.0 / df['closing_cote']
        df['clv_pct'] = (
            (df['implied_close'] - df['implied_open'])
            / df['implied_open']
        ) * 100

        mean_clv = df['clv_pct'].mean()
        median_clv = df['clv_pct'].median()
        pct_positive = (df['clv_pct'] > 0).mean() * 100

        # Test t de Student : H0 = CLV moyen = 0 (pas d'edge)
        t_stat, p_value = stats.ttest_1samp(df['clv_pct'], 0)

        # Corrélation CLV vs résultat
        df['won'] = (
            pd.to_numeric(df['result'], errors='coerce').fillna(0) > 0
        ).astype(int)
        clv_winners = df[df['won'] == 1]['clv_pct'].mean()
        clv_losers = df[df['won'] == 0]['clv_pct'].mean()

        print(f"\n{'─' * 55}")
        print(f"  {label} ({len(df)} picks avec CLV)")
        print(f"{'─' * 55}")
        print(f"  CLV Moyen:       {mean_clv:+.2f}%")
        print(f"  CLV Médian:      {median_clv:+.2f}%")
        print(f"  % de CLV > 0:    {pct_positive:.1f}%")
        print(f"  T-stat:          {t_stat:.3f}")
        print(f"  P-value:         {p_value:.4f}")
        print(f"  CLV gagnants:    {clv_winners:+.2f}%")
        print(f"  CLV perdants:    {clv_losers:+.2f}%")

        if p_value < 0.05 and mean_clv > 0:
            print(f"  ✅ EDGE CONFIRMÉ (p < 0.05, CLV positif)")
        elif p_value < 0.05 and mean_clv < 0:
            print(
                f"  ❌ ANTI-EDGE CONFIRMÉ "
                f"(le marché vous bat systématiquement)"
            )
        elif p_value < 0.10 and mean_clv > 0:
            print(f"  ⚠️ TENDANCE POSITIVE (p < 0.10) — besoin de plus "
                  f"de données")
        else:
            print(
                f"  ⚠️ NON SIGNIFICATIF — échantillon insuffisant "
                f"ou pas d'edge"
            )

        # Breakdown par mois
        df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
        monthly = df.groupby('month').agg(
            clv_mean=('clv_pct', 'mean'),
            count=('clv_pct', 'count')
        )
        if len(monthly) > 1:
            print(f"\n  Évolution mensuelle CLV:")
            for month, row in monthly.iterrows():
                bar = "▓" * max(1, int(abs(row['clv_mean'])))
                sign = "+" if row['clv_mean'] > 0 else ""
                print(
                    f"    {month}: {sign}{row['clv_mean']:.2f}% "
                    f"({int(row['count'])} picks) {bar}"
                )

    conn.close()
    print(f"\n{'=' * 70}")
    print(" INTERPRÉTATION:")
    print("  CLV > 0% systématique = votre modèle capture de la value")
    print("  CLV ≈ 0% = performance aléatoire (pas d'edge)")
    print("  CLV < 0% = le marché est meilleur que votre modèle")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    analyze_clv()
