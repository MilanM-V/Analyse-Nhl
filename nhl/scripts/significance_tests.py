"""
scripts/significance_tests.py — Tests de significativité statistique.

Répond à la question : "Mon win rate est-il statistiquement supérieur
au break-even implicite du marché, ou est-ce du bruit ?"

Tests implémentés :
- Test binomial exact (one-sided)
- Intervalle de confiance Wilson (plus précis que normal pour petits n)
- Estimation du nombre de picks nécessaires pour la significativité

Usage:
    python nhl/scripts/significance_tests.py
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


def binomial_test_market(table: str, target_col: str, label: str) -> None:
    """Test binomial exact sur un marché.

    H0: le win rate réel = probabilité implicite moyenne du marché
    H1: le win rate réel > probabilité implicite (= edge)

    Args:
        table: Nom de la table SQL.
        target_col: Colonne de résultat ('but', 'assist', 'point').
        label: Nom affiché du marché.
    """
    conn = sqlite3.connect(DB_PATH)
    query = f"""
        SELECT {target_col} as result, cote FROM {table}
        WHERE {target_col} IS NOT NULL AND {target_col} != ''
          AND cote IS NOT NULL AND cote > 1.05
    """
    try:
        df = pd.read_sql(query, conn)
    except Exception as e:
        print(f"  [{label}] Erreur SQL : {e}")
        conn.close()
        return
    conn.close()

    if len(df) < 20:
        print(f"  [{label}] Échantillon trop petit ({len(df)} < 20).")
        return

    n = len(df)
    k = int(
        (pd.to_numeric(df['result'], errors='coerce').fillna(0) > 0).sum()
    )

    # Probabilité de break-even = 1/cote_moyenne
    mean_cote = float(df['cote'].mean())
    p0 = 1.0 / mean_cote  # Break-even implicite

    # Test binomial exact (one-sided : H1 = win rate > p0)
    try:
        res = stats.binomtest(k, n, p0, alternative='greater')
        p_value = float(res.pvalue)
    except AttributeError:
        p_value = float(stats.binom_test(k, n, p0, alternative='greater'))

    wr = k / n * 100
    wr_breakeven = p0 * 100

    # Intervalle de confiance Wilson (plus précis que normal pour petits n)
    z = 1.96  # 95%
    p_hat = k / n
    denom = 1 + z ** 2 / n
    center = (p_hat + z ** 2 / (2 * n)) / denom
    margin = (
        z * np.sqrt((p_hat * (1 - p_hat) + z ** 2 / (4 * n)) / n) / denom
    )
    ci_low = max(0, center - margin) * 100
    ci_high = min(1, center + margin) * 100

    # Nombre de picks nécessaires pour la significativité
    effect_size = max(0.001, p_hat - p0)
    if effect_size > 0:
        n_needed = int((z ** 2 * p0 * (1 - p0)) / (effect_size ** 2))
    else:
        n_needed = 99999

    # Profit réel (ROI)
    df['won'] = (
        pd.to_numeric(df['result'], errors='coerce').fillna(0) > 0
    ).astype(int)
    profit = (df['won'] * (df['cote'] - 1) - (1 - df['won'])).sum()
    roi = profit / n * 100

    print(f"\n  {'─' * 55}")
    print(f"  {label}")
    print(f"  {'─' * 55}")
    print(f"  Picks:            {n}")
    print(f"  Wins:             {k} ({wr:.1f}%)")
    print(f"  Break-even:       {wr_breakeven:.1f}% "
          f"(cote moy: {mean_cote:.2f})")
    print(f"  Edge observé:     {wr - wr_breakeven:+.1f} points")
    print(f"  IC 95% win rate:  [{ci_low:.1f}%, {ci_high:.1f}%]")
    print(f"  P-value (H1>H0):  {p_value:.4f}")
    print(f"  ROI:              {roi:+.1f}% ({profit:+.1f} U)")
    print(f"  N nécessaire:     ~{n_needed} picks pour significativité")

    # Diagnostic
    if wr_breakeven < ci_low:
        confidence = "forte"
    elif wr_breakeven < center * 100:
        confidence = "faible"
    else:
        confidence = "aucune"

    if p_value < 0.05:
        print(f"  ✅ SIGNIFICATIF (p < 0.05) — edge probable "
              f"(confiance {confidence})")
    elif p_value < 0.10:
        print(f"  ⚠️ TENDANCE (p < 0.10) — signal faible, "
              f"besoin de {n_needed - n} picks supplémentaires")
    else:
        print(
            f"  ❌ NON SIGNIFICATIF — indistinguable de la variance"
        )
        if n_needed > n:
            print(f"     → Il faut encore ~{n_needed - n} picks "
                  f"pour conclure")


def run_all_tests():
    """Lance tous les tests de significativité."""
    print("=" * 60)
    print(" TESTS DE SIGNIFICATIVITÉ STATISTIQUE")
    print(" (Question : Avez-vous un edge ou est-ce de la chance ?)")
    print("=" * 60)

    binomial_test_market("picks", "but", "BUTEURS")
    binomial_test_market("picks_assists", "assist", "PASSEURS")
    binomial_test_market("picks_points", "point", "POINTEURS")

    print(f"\n{'=' * 60}")
    print(" GUIDE D'INTERPRÉTATION:")
    print("  p < 0.05  → Edge statistiquement prouvé")
    print("  p < 0.10  → Tendance, besoin de plus de données")
    print("  p > 0.10  → Pas de preuve d'edge (variance ou breakeven)")
    print("  IC 95%    → Si le break-even est HORS de l'IC → signal fort")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    run_all_tests()
