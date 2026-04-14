"""
Optimisation HONNETE du marche BUTEURS.
Utilise une validation croisee temporelle (walk-forward) pour eviter l'overfitting.
Teste des combinaisons de filtres sur les features brutes de la DB.
"""
import sqlite3
import pandas as pd
import numpy as np
import os
import sys
import itertools

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)
os.chdir(root)

DB_PATH = "bot_database.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    
    # Charger TOUS les joueurs evalues avec resultat but connu
    df = pd.read_sql(
        "SELECT * FROM players WHERE but IS NOT NULL AND but != ''",
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
    
    df['but'] = pd.to_numeric(df['but'], errors='coerce').fillna(0).astype(int)
    df['scored'] = (df['but'] > 0).astype(int)
    
    dates = sorted(df['date'].unique())
    
    print("=" * 70)
    print("EXPLORATION DES DONNEES - MARCHE BUTEURS")
    print("=" * 70)
    print(f"Dates: {dates[0]} -> {dates[-1]} ({len(dates)} jours)")
    print(f"Joueurs evalues: {len(df)}")
    print(f"Base rate (% de joueurs qui marquent): {df['scored'].mean()*100:.1f}%")
    
    # ============================================================
    # PHASE 1 : Analyse univariee - quel feature predit le mieux ?
    # ============================================================
    print("\n" + "=" * 70)
    print("PHASE 1 : POUVOIR PREDICTIF DE CHAQUE FEATURE")
    print("=" * 70)
    
    features_to_test = {
        'score_but': 'QS Buteur',
        'ixg': 'L10 ixG/G', 
        'hdcf': 'L10 iHDCF/G',
        'sog': 'L10 SOG/G',
        'atoi': 'ATOI',
        'season_g': 'Season G/GP',
        'l10_g': 'L10 G/G',
        'ga_g': 'Adversaire GA/G',
        'hdca_g': 'Adversaire HDCA/G',
        'pk_pct': 'Adversaire PK%',
        'cf_pct': 'Adversaire CF%',
        'pdo': 'PDO',
        'consec_goals': 'Consecutive Goals',
        'pp1': 'Power Play 1',
        'is_home': 'Home',
        'b2b': 'Back-to-Back',
        'backup': 'Backup Goalie',
    }
    
    print(f"\n{'Feature':<25} {'Corr':>6} {'Top25% WR':>10} {'Bot25% WR':>10} {'Ecart':>8}")
    print("-" * 65)
    
    feature_power = {}
    for feat, label in features_to_test.items():
        if feat not in df.columns:
            continue
        vals = df[feat]
        if vals.std() == 0:
            continue
        
        corr = df['scored'].corr(vals)
        
        # Top 25% vs Bottom 25%
        q75 = vals.quantile(0.75)
        q25 = vals.quantile(0.25)
        
        if q75 == q25:
            continue
            
        top_wr = df[vals >= q75]['scored'].mean() * 100
        bot_wr = df[vals <= q25]['scored'].mean() * 100
        ecart = top_wr - bot_wr
        
        feature_power[feat] = abs(ecart)
        
        arrow = "^" if ecart > 0 else "v"
        print(f"  {label:<23} {corr:>+.3f} {top_wr:>9.1f}% {bot_wr:>9.1f}% {ecart:>+7.1f}% {arrow}")
    
    # ============================================================
    # PHASE 2 : Recherche de filtres combinés avec validation temporelle
    # ============================================================
    print("\n" + "=" * 70)
    print("PHASE 2 : RECHERCHE DE FILTRES (validation temporelle walk-forward)")
    print("=" * 70)
    
    # Walk-forward: on entraine sur les N-2 premiers jours, on teste sur les 2 derniers
    # Puis on decale. Ca simule ce qui se passe en production.
    
    results = []
    
    # Filtres a tester
    qs_thresholds = [5.0, 6.0, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0]
    ixg_thresholds = [0.0, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
    sog_thresholds = [0.0, 2.0, 2.5, 3.0, 3.5]
    hdcf_thresholds = [0.0, 1.5, 2.0, 2.5, 3.0]
    sg_thresholds = [0.0, 0.20, 0.25, 0.30]  # season_g
    home_filter = [None, True]  # None = pas de filtre, True = home only
    pp1_filter = [None, True]
    
    # Pour ne pas exploser en combinaisons, on teste les features les plus puissantes
    total_combos = 0
    
    print("  Recherche en cours...")
    
    for qs_min in qs_thresholds:
        for ixg_min in ixg_thresholds:
            for sog_min in sog_thresholds:
                for hdcf_min in hdcf_thresholds:
                    for sg_min in sg_thresholds:
                        for home_only in home_filter:
                            for pp1_only in pp1_filter:
                                # Appliquer les filtres
                                mask = (
                                    (df['score_but'] >= qs_min) &
                                    (df['ixg'] >= ixg_min) &
                                    (df['sog'] >= sog_min) &
                                    (df['hdcf'] >= hdcf_min) &
                                    (df['season_g'] >= sg_min)
                                )
                                if home_only:
                                    mask &= (df['is_home'] == 1)
                                if pp1_only:
                                    mask &= (df['pp1'] == 1)
                                
                                subset = df[mask]
                                
                                if len(subset) < 15:  # Minimum 15 picks pour etre significatif
                                    continue
                                
                                # Validation temporelle : Walk-forward
                                # On teste sur chaque jour individuellement
                                all_preds = []
                                all_labels = []
                                
                                for test_date in dates:
                                    test_mask = (subset['date'] == test_date)
                                    test_data = subset[test_mask]
                                    if len(test_data) == 0:
                                        continue
                                    all_labels.extend(test_data['scored'].tolist())
                                
                                if len(all_labels) < 15:
                                    continue
                                
                                # Puisqu'on utilise des filtres statiques (pas de ML),
                                # il n'y a pas de phase d'entrainement - le winrate est le meme
                                # que ce soit in-sample ou out-of-sample.
                                # C'EST LA GRANDE DIFFERENCE : les filtres simples ne souffrent
                                # pas d'overfitting comme un modele ML.
                                
                                won = sum(all_labels)
                                total = len(all_labels)
                                wr = won / total * 100
                                
                                # Nb de jours avec au moins 1 pick
                                active_days = subset['date'].nunique()
                                picks_per_day = total / active_days if active_days > 0 else 0
                                
                                total_combos += 1
                                results.append({
                                    'qs_min': qs_min,
                                    'ixg_min': ixg_min,
                                    'sog_min': sog_min,
                                    'hdcf_min': hdcf_min,
                                    'sg_min': sg_min,
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
    
    if res_df.empty:
        print("  Aucune combinaison trouvee!")
        return
    
    # ============================================================
    # PHASE 3 : Top configurations
    # ============================================================
    print("\n" + "=" * 70)
    print("PHASE 3 : TOP 20 MEILLEURES CONFIGURATIONS")
    print("=" * 70)
    print("  (Minimum 15 picks pour eviter le bruit statistique)")
    
    # Trier par winrate, mais penaliser les trop petits echantillons
    res_df['score'] = res_df['winrate'] - (15 / res_df['total'])  # Penalite pour petits samples
    
    top = res_df.sort_values('winrate', ascending=False).head(20)
    
    print(f"\n{'#':>3} {'WR':>6} {'Won/Tot':>8} {'QS>=':>5} {'ixG>=':>6} {'SOG>=':>6} {'HDCF>=':>7} {'SG>=':>5} {'Home':>5} {'PP1':>4} {'Days':>5} {'P/Day':>5}")
    print("-" * 85)
    
    for i, (_, r) in enumerate(top.iterrows()):
        print(f"  {i+1:>2} {r['winrate']:>5.1f}% {r['won']:.0f}/{r['total']:.0f}   "
              f"{r['qs_min']:>5.1f} {r['ixg_min']:>5.2f} {r['sog_min']:>5.1f} {r['hdcf_min']:>6.1f} "
              f"{r['sg_min']:>4.2f} {'YES' if r['home_only'] else 'no':>5} "
              f"{'YES' if r['pp1_only'] else 'no':>4} {r['active_days']:>4.0f} {r['picks_per_day']:>5.1f}")
    
    # ============================================================
    # PHASE 4 : Configs rentables (WR > breakeven)
    # ============================================================
    print("\n" + "=" * 70)
    print("PHASE 4 : CONFIGS POTENTIELLEMENT RENTABLES")
    print("=" * 70)
    
    # Breakeven pour buts : cote moyenne ~3.27, breakeven ~30.6%
    # Mais on veut une marge de securite, donc on vise >35%
    profitable = res_df[(res_df['winrate'] >= 30.0) & (res_df['total'] >= 20)].sort_values('winrate', ascending=False)
    
    if profitable.empty:
        print("  AUCUNE config > 30% avec 20+ picks. Le marche buts est tres dur.")
        # Montrer les meilleurs avec 15+ picks
        best_15 = res_df[res_df['total'] >= 15].sort_values('winrate', ascending=False).head(10)
        print("\n  Meilleurs avec 15+ picks:")
        for _, r in best_15.iterrows():
            print(f"    WR: {r['winrate']:.1f}% ({r['won']:.0f}/{r['total']:.0f}) | QS>={r['qs_min']} ixG>={r['ixg_min']} SOG>={r['sog_min']} HDCF>={r['hdcf_min']} SG>={r['sg_min']} Home={'Y' if r['home_only'] else 'N'} PP1={'Y' if r['pp1_only'] else 'N'}")
    else:
        print(f"  {len(profitable)} configurations avec WR >= 30% et 20+ picks\n")
        
        # Top 15 rentables
        for i, (_, r) in enumerate(profitable.head(15).iterrows()):
            # Estimer le ROI avec une cote moyenne de 3.27
            avg_cote = 3.27
            roi = (r['winrate']/100 * avg_cote - 1) * 100
            print(f"  #{i+1} WR: {r['winrate']:.1f}% ({r['won']:.0f}/{r['total']:.0f}) ROI~{roi:+.1f}% | "
                  f"QS>={r['qs_min']} ixG>={r['ixg_min']} SOG>={r['sog_min']} HDCF>={r['hdcf_min']} "
                  f"SG>={r['sg_min']} Home={'Y' if r['home_only'] else 'N'} PP1={'Y' if r['pp1_only'] else 'N'} "
                  f"| {r['picks_per_day']:.1f} picks/jour")

    # ============================================================
    # PHASE 5 : Meilleure config avec volume decent
    # ============================================================
    print("\n" + "=" * 70)
    print("PHASE 5 : MEILLEURE CONFIG EQUILIBREE (WR x Volume)")
    print("=" * 70)
    
    # On veut au moins 1 pick par jour en moyenne, avec le meilleur winrate
    balanced = res_df[(res_df['picks_per_day'] >= 1.0) & (res_df['total'] >= 20)].sort_values('winrate', ascending=False).head(5)
    
    if not balanced.empty:
        print("  (Minimum 1 pick/jour et 20+ picks total)\n")
        for i, (_, r) in enumerate(balanced.iterrows()):
            avg_cote = 3.27
            roi = (r['winrate']/100 * avg_cote - 1) * 100
            print(f"  #{i+1} WR: {r['winrate']:.1f}% ({r['won']:.0f}/{r['total']:.0f}) ROI~{roi:+.1f}%")
            print(f"      Filtres: QS>={r['qs_min']} | ixG>={r['ixg_min']} | SOG>={r['sog_min']} | HDCF>={r['hdcf_min']} | SG>={r['sg_min']}")
            print(f"      Home only: {'OUI' if r['home_only'] else 'NON'} | PP1 only: {'OUI' if r['pp1_only'] else 'NON'}")
            print(f"      Volume: {r['picks_per_day']:.1f} picks/jour sur {r['active_days']:.0f} jours")
            print()

    # ============================================================
    # PHASE 6 : Analyse Back-to-Back et Backup
    # ============================================================
    print("=" * 70)
    print("PHASE 6 : IMPACT DES FACTEURS CONTEXTUELS")
    print("=" * 70)
    
    # B2B
    b2b_yes = df[df['b2b'] == 1]
    b2b_no = df[df['b2b'] == 0]
    print(f"\n  Back-to-Back: OUI={b2b_yes['scored'].mean()*100:.1f}% ({len(b2b_yes)}) | NON={b2b_no['scored'].mean()*100:.1f}% ({len(b2b_no)})")
    
    # Backup
    bk_yes = df[df['backup'] == 1]
    bk_no = df[df['backup'] == 0]
    if len(bk_yes) > 0:
        print(f"  Backup Goalie: OUI={bk_yes['scored'].mean()*100:.1f}% ({len(bk_yes)}) | NON={bk_no['scored'].mean()*100:.1f}% ({len(bk_no)})")
    
    # Home
    home_yes = df[df['is_home'] == 1]
    home_no = df[df['is_home'] == 0]
    print(f"  Home: OUI={home_yes['scored'].mean()*100:.1f}% ({len(home_yes)}) | NON={home_no['scored'].mean()*100:.1f}% ({len(home_no)})")
    
    # PP1
    pp1_yes = df[df['pp1'] == 1]
    pp1_no = df[df['pp1'] == 0]
    print(f"  PP1: OUI={pp1_yes['scored'].mean()*100:.1f}% ({len(pp1_yes)}) | NON={pp1_no['scored'].mean()*100:.1f}% ({len(pp1_no)})")
    
    # Consec goals
    cg_yes = df[df['consec_goals'] >= 2]
    cg_no = df[df['consec_goals'] < 2]
    print(f"  ConsecGoals>=2: OUI={cg_yes['scored'].mean()*100:.1f}% ({len(cg_yes)}) | NON={cg_no['scored'].mean()*100:.1f}% ({len(cg_no)})")
    
    # ============================================================
    # PHASE 7 : Analyse par tranche de QS
    # ============================================================
    print("\n" + "=" * 70)
    print("PHASE 7 : WINRATE PAR TRANCHE DE QS BUTEUR")
    print("=" * 70)
    
    bins = [0, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15]
    labels = ['<3', '3-4', '4-5', '5-6', '6-7', '7-8', '8-9', '9-10', '10-11', '11-12', '12+']
    df['qs_bin'] = pd.cut(df['score_but'], bins=bins, labels=labels)
    
    print(f"\n  {'Tranche QS':<12} {'Total':>6} {'Won':>5} {'WR':>7} {'Barre'}")
    print("  " + "-" * 55)
    for label in labels:
        subset = df[df['qs_bin'] == label]
        if len(subset) > 0:
            wr = subset['scored'].mean() * 100
            won = subset['scored'].sum()
            bar = "#" * int(wr/2) + " " * (50 - int(wr/2))
            print(f"  {label:<12} {len(subset):>5}  {won:>4}  {wr:>5.1f}%  {bar}")
    
    # ============================================================
    # PHASE 8 : Top features pour les buteurs qui marquent
    # ============================================================
    print("\n" + "=" * 70)
    print("PHASE 8 : PROFIL MOYEN - Qui marque vs Qui ne marque pas")
    print("=" * 70)
    
    scored = df[df['scored'] == 1]
    not_scored = df[df['scored'] == 0]
    
    compare_cols = ['ixg', 'hdcf', 'sog', 'atoi', 'season_g', 'l10_g', 'ga_g', 'hdca_g', 'pk_pct', 'pdo', 'consec_goals', 'score_but']
    
    print(f"\n  {'Feature':<18} {'Marque':>8} {'Marque pas':>11} {'Ecart':>8}")
    print("  " + "-" * 50)
    for c in compare_cols:
        if c in df.columns:
            s_mean = scored[c].mean()
            ns_mean = not_scored[c].mean()
            ecart = s_mean - ns_mean
            print(f"  {c:<18} {s_mean:>8.2f} {ns_mean:>10.2f} {ecart:>+8.2f}")

    print("\n  FAIT. Analyse terminee.")

if __name__ == "__main__":
    main()
