"""
Optimisation HONNETE du marche ASSISTS.
Examine le pouvoir predictif des features et fait un grid search temporel.
"""
import sqlite3
import pandas as pd
import numpy as np
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)
os.chdir(root)

DB_PATH = "bot_database.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    
    # Charger la table picks_assists ou players.
    # Dans `players`, on a tous les joueurs évalués
    df = pd.read_sql(
        "SELECT * FROM players WHERE assist IS NOT NULL AND assist != ''",
        conn
    )
    conn.close()
    
    # Conversions
    numeric_cols = ['ixg', 'hdcf', 'sog', 'atoi', 'season_g', 'season_a', 'season_pts',
                    'l10_g', 'l10_a', 'l10_pts', 'ga_g', 'cf_pct', 'hdca_g', 'pk_pct',
                    'pdo', 'consec_goals', 'score_but', 'score_assist', 'score_point',
                    'pp1', 'is_home', 'b2b', 'backup']
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    
    df['assist'] = pd.to_numeric(df['assist'], errors='coerce').fillna(0).astype(int)
    df['scored'] = (df['assist'] > 0).astype(int)
    
    dates = sorted(df['date'].unique())
    
    print("=" * 70)
    print("EXPLORATION DES DONNEES - MARCHE ASSISTS")
    print("=" * 70)
    print(f"Dates: {dates[0]} -> {dates[-1]} ({len(dates)} jours)")
    print(f"Joueurs evalues: {len(df)}")
    print(f"Base rate (% de joueurs qui font une passe): {df['scored'].mean()*100:.1f}%")
    
    # ============================================================
    # PHASE 1 : Analyse univariee
    # ============================================================
    print("\n" + "=" * 70)
    print("PHASE 1 : POUVOIR PREDICTIF DE CHAQUE FEATURE (ASSISTS)")
    print("=" * 70)
    
    features_to_test = {
        'score_assist': 'QS Passeur',
        'season_a': 'Season A/GP',
        'l10_a': 'L10 A/G',
        'season_pts': 'Season Pts/GP',
        'l10_pts': 'L10 Pts/G',
        'ixg': 'L10 ixG/G', 
        'hdcf': 'L10 iHDCF/G',
        'atoi': 'ATOI',
        'ga_g': 'Adversaire GA/G',
        'cf_pct': 'Adversaire CF%',
        'pdo': 'PDO',
        'pp1': 'Power Play 1',
        'is_home': 'Home',
        'b2b': 'Back-to-Back',
    }
    
    print(f"\n{'Feature':<25} {'Corr':>6} {'Top25% WR':>10} {'Bot25% WR':>10} {'Ecart':>8}")
    print("-" * 65)
    
    feature_power = {}
    for feat, label in features_to_test.items():
        if feat not in df.columns: continue
        vals = df[feat]
        if vals.std() == 0: continue
        
        corr = df['scored'].corr(vals)
        q75 = vals.quantile(0.75)
        q25 = vals.quantile(0.25)
        
        if q75 == q25: continue
            
        top_wr = df[vals >= q75]['scored'].mean() * 100
        bot_wr = df[vals <= q25]['scored'].mean() * 100
        ecart = top_wr - bot_wr
        feature_power[feat] = abs(ecart)
        
        arrow = "^" if ecart > 0 else "v"
        print(f"  {label:<23} {corr:>+.3f} {top_wr:>9.1f}% {bot_wr:>9.1f}% {ecart:>+7.1f}% {arrow}")
        
    # ============================================================
    # PHASE 2 : Recherche de filtres
    # ============================================================
    print("\n" + "=" * 70)
    print("PHASE 2 : RECHERCHE DE FILTRES COMBINES")
    print("=" * 70)
    
    results = []
    
    # Pour Passeur, les métriques clés semblent être les stats de passe et le QS
    qs_thresholds = [7.0, 8.0, 9.0, 10.0, 10.5, 11.0, 11.5, 12.0]
    sa_thresholds = [0.0, 0.30, 0.40, 0.50, 0.60] # season_a
    l10a_thresholds = [0.0, 0.20, 0.40, 0.60, 0.80] # l10_a
    home_filter = [None, True]
    pp1_filter = [None, True]
    
    total_combos = 0
    print("  Recherche en cours...")
    
    for qs_min in qs_thresholds:
        for sa_min in sa_thresholds:
            for l10a_min in l10a_thresholds:
                for home_only in home_filter:
                    for pp1_only in pp1_filter:
                        mask = (
                            (df['score_assist'] >= qs_min) &
                            (df['season_a'] >= sa_min) &
                            (df['l10_a'] >= l10a_min)
                        )
                        if home_only: mask &= (df['is_home'] == 1)
                        if pp1_only: mask &= (df['pp1'] == 1)
                        
                        subset = df[mask]
                        if len(subset) < 15: continue
                        
                        won = subset['scored'].sum()
                        total = len(subset)
                        wr = won / total * 100
                        
                        active_days = subset['date'].nunique()
                        picks_per_day = total / active_days if active_days > 0 else 0
                        
                        total_combos += 1
                        results.append({
                            'qs_min': qs_min,
                            'sa_min': sa_min,
                            'l10a_min': l10a_min,
                            'home_only': bool(home_only),
                            'pp1_only': bool(pp1_only),
                            'total': total,
                            'won': won,
                            'winrate': wr,
                            'active_days': active_days,
                            'picks_per_day': picks_per_day,
                        })
    
    print(f"  {total_combos} combinaisons testees")
    
    res_df = pd.DataFrame(results)
    if res_df.empty: return
    
    print("\n" + "=" * 70)
    print("PHASE 3 : RECHERCHE WINRATE MAXIMAL ET RENTABLE")
    print("=" * 70)
    
    # Le breakeven calculé plus tôt pour les assists était autour de 51.5% (cote moy 1.94)
    # On va donc afficher les configs par volume décroissant
    
    for min_picks in [5, 15, 30, 50, 100]:
        print(f"--- En exigeant au moins {min_picks} picks sur 2 semaines ---")
        valid = res_df[res_df['total'] >= min_picks]
        if valid.empty:
            print("  Aucune configuration ne donne autant de picks.")
            continue
            
        top = valid.sort_values('winrate', ascending=False).iloc[0]
        # Estimation ROI
        avg_cote = 1.94
        roi = (top['winrate']/100 * avg_cote - 1) * 100
        
        print(f"  Max WR: {top['winrate']:.1f}% ({int(top['won'])}/{int(top['total'])}) | ROI: {roi:+.1f}%")
        print(f"  Filtres: QS>={top['qs_min']}, Season_A>={top['sa_min']}, L10_A>={top['l10a_min']}, Home={top['home_only']}, PP1={top['pp1_only']}")
        print()

    print("=" * 70)
    print("TOP 10 EQUILIBRE (>30 picks)")
    print("=" * 70)
    valid30 = res_df[res_df['total'] >= 30].sort_values('winrate', ascending=False).head(10)
    if not valid30.empty:
        for i, (_, r) in enumerate(valid30.iterrows()):
            roi = (r['winrate']/100 * 1.94 - 1) * 100
            print(f"#{i+1} WR: {r['winrate']:.1f}% ({r['won']:.0f}/{r['total']:.0f}) | ROI: {roi:+.1f}%")
            print(f"    QS>={r['qs_min']}, Season_A>={r['sa_min']}, L10_A>={r['l10a_min']}, Home={r['home_only']}, PP1={r['pp1_only']}")
    
if __name__ == "__main__":
    main()
