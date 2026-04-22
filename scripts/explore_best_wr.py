"""
EXPLORATION EXHAUSTIVE — Trouver les filtres avec le meilleur winrate.

Ce script teste systématiquement TOUTES les combinaisons de critères
sur les 2893 joueurs résolus pour identifier les configs optimales.

Approches testées :
  1. Analyse de chaque feature individuellement (corrélation avec le résultat)
  2. Impact de chaque flag (home, PP1, backup, b2b, etc.)
  3. Grid search sur les seuils statistiques
  4. Combinaisons multi-critères
  5. Régression logistique (quelles features prédisent réellement ?)
  6. Interactions (PP1 + faible PK adverse, form récente vs saison, etc.)
  7. Approches non-conventionnelles (underlays, contrarian, etc.)

Contrainte : minimum 30 picks pour éviter le bruit statistique.
"""
import sqlite3
import os
import sys
import math
from itertools import product

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)
os.chdir(root)

DB_PATH = "bot_database.db"
MIN_SAMPLE = 30  # Minimum pour qu'un résultat soit fiable


def load_data():
    """Charge tous les joueurs résolus depuis la DB."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM players 
        WHERE but IS NOT NULL AND assist IS NOT NULL AND point IS NOT NULL
        AND atoi >= 13.0
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    
    # Nettoyage des None
    for r in rows:
        for key in r:
            if r[key] is None:
                r[key] = 0
    
    return rows


def winrate(subset, col):
    """Calcule le winrate d'un subset pour une colonne donnée."""
    if not subset:
        return 0, 0, 0
    total = len(subset)
    won = sum(1 for r in subset if r[col] and int(r[col]) > 0)
    return won, total, won / total * 100 if total > 0 else 0


def section(title):
    """Affiche un titre de section."""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def main():
    rows = load_data()
    print(f"Joueurs charges: {len(rows)}")
    
    markets = [
        ("BUTS", "but", "season_g", "l10_g"),
        ("ASSISTS", "assist", "season_a", "l10_a"),
        ("POINTS", "point", "season_pts", "l10_pts"),
    ]
    
    for market_name, result_col, season_col, l10_col in markets:
        section(f"MARCHE {market_name}")
        
        # ═══════════════════════════════════════════════════
        # 1. BASELINE : Winrate brut de tout le monde
        # ═══════════════════════════════════════════════════
        w, t, wr = winrate(rows, result_col)
        print(f"\n  [BASELINE] Tous joueurs: {w}/{t} ({wr:.1f}%)")
        
        # ═══════════════════════════════════════════════════
        # 2. IMPACT DE CHAQUE FLAG INDIVIDUEL
        # ═══════════════════════════════════════════════════
        print(f"\n  --- Impact des flags ---")
        for flag, label in [
            ("is_home", "HOME"), ("pp1", "PP1"), 
            ("backup", "BACKUP adverse"), ("b2b", "B2B"),
        ]:
            on = [r for r in rows if r[flag]]
            off = [r for r in rows if not r[flag]]
            w_on, t_on, wr_on = winrate(on, result_col)
            w_off, t_off, wr_off = winrate(off, result_col)
            delta = wr_on - wr_off if t_on > 0 and t_off > 0 else 0
            print(f"    {label:15s}: ON={w_on}/{t_on} ({wr_on:.1f}%) | OFF={w_off}/{t_off} ({wr_off:.1f}%) | Delta={delta:+.1f}%")
        
        # ═══════════════════════════════════════════════════
        # 3. CORRÉLATION DE CHAQUE FEATURE NUMÉRIQUE
        # ═══════════════════════════════════════════════════
        print(f"\n  --- Pouvoir predictif par feature (top/bottom 50%) ---")
        features = [
            ("season_g", "Season G/GP"), ("season_a", "Season A/GP"), 
            ("season_pts", "Season Pts/GP"),
            ("l10_g", "L10 G/GP"), ("l10_a", "L10 A/GP"), ("l10_pts", "L10 Pts/GP"),
            ("ixg", "L10 ixG"), ("hdcf", "L10 HDCF"), ("sog", "L10 SOG"),
            ("atoi", "ATOI"), ("pdo", "PDO"), 
            ("ga_g", "Opp GA/G"), ("pk_pct", "Opp PK%"), 
            ("hdca_g", "Opp HDCA/G"), ("cf_pct", "Opp CF%"),
            ("consec_goals", "ConsecGoals"),
        ]
        
        feature_scores = []
        for feat, label in features:
            vals = sorted(rows, key=lambda r: float(r[feat] or 0))
            mid = len(vals) // 2
            bottom = vals[:mid]
            top = vals[mid:]
            _, _, wr_top = winrate(top, result_col)
            _, _, wr_bot = winrate(bottom, result_col)
            delta = wr_top - wr_bot
            feature_scores.append((abs(delta), delta, feat, label))
        
        feature_scores.sort(reverse=True)
        for _, delta, feat, label in feature_scores[:10]:
            direction = "HIGH=+" if delta > 0 else "LOW=+"
            print(f"    {label:18s}: {direction} ({abs(delta):.1f}% gap)")
        
        # ═══════════════════════════════════════════════════
        # 4. ANALYSE PAR TRANCHES (chaque feature)
        # ═══════════════════════════════════════════════════
        print(f"\n  --- Meilleurs seuils par feature individuelle ---")
        
        best_single_filters = []
        for feat, label in features:
            vals = [float(r[feat] or 0) for r in rows]
            if not vals:
                continue
            
            # Tester des percentiles
            import numpy as np
            percentiles = [25, 50, 60, 70, 75, 80, 85, 90]
            
            best_wr = 0
            best_threshold = 0
            best_n = 0
            best_direction = ">="
            
            for pct in percentiles:
                threshold = float(np.percentile(vals, pct))
                
                # Filtre >= threshold
                subset_high = [r for r in rows if float(r[feat] or 0) >= threshold]
                w, t, wr_val = winrate(subset_high, result_col)
                if t >= MIN_SAMPLE and wr_val > best_wr:
                    best_wr = wr_val
                    best_threshold = threshold
                    best_n = t
                    best_direction = ">="
                
                # Filtre <= threshold (pour PDO bas, PK% bas, etc.)
                subset_low = [r for r in rows if float(r[feat] or 0) <= threshold]
                w, t, wr_val = winrate(subset_low, result_col)
                if t >= MIN_SAMPLE and wr_val > best_wr:
                    best_wr = wr_val
                    best_threshold = threshold
                    best_n = t
                    best_direction = "<="
            
            if best_wr > 0:
                best_single_filters.append((best_wr, feat, label, best_direction, best_threshold, best_n))
        
        best_single_filters.sort(reverse=True)
        for wr_val, feat, label, direction, threshold, n in best_single_filters[:8]:
            w_count = int(wr_val * n / 100)
            print(f"    {label:18s} {direction} {threshold:.2f}: {w_count}/{n} ({wr_val:.1f}%)")
        
        # ═══════════════════════════════════════════════════
        # 5. GRID SEARCH : Meilleures combinaisons multi-critères
        # ═══════════════════════════════════════════════════
        section(f"GRID SEARCH — {market_name}")
        
        # Définir les ranges de recherche selon le marché
        if market_name == "BUTS":
            grid = {
                "is_home": [None, True],
                "pp1": [None, True],
                "season_g_min": [0.0, 0.20, 0.30, 0.40],
                "sog_min": [0.0, 2.0, 2.5, 3.0],
                "hdcf_min": [0.0, 1.5, 2.0, 2.5],
                "ixg_min": [0.0, 0.25, 0.35, 0.45],
                "ga_g_min": [0.0, 2.5, 2.8, 3.0],
            }
        elif market_name == "ASSISTS":
            grid = {
                "is_home": [None, True],
                "pp1": [None, True],
                "season_a_min": [0.0, 0.30, 0.40, 0.50, 0.60],
                "l10_a_min": [0.0, 0.40, 0.60, 0.80, 1.0],
                "atoi_min": [13.0, 16.0, 18.0, 20.0],
                "ga_g_min": [0.0, 2.5, 2.8, 3.0],
            }
        else:  # POINTS
            grid = {
                "is_home": [None, True],
                "pp1": [None, True],
                "season_pts_min": [0.0, 0.50, 0.60, 0.70, 0.80, 0.90],
                "l10_pts_min": [0.0, 0.30, 0.40, 0.60, 0.80],
                "atoi_min": [13.0, 16.0, 18.0],
                "ga_g_min": [0.0, 2.5, 2.8],
            }
        
        keys = list(grid.keys())
        values = list(grid.values())
        
        results = []
        for combo in product(*values):
            params = dict(zip(keys, combo))
            
            subset = rows[:]
            desc_parts = []
            
            if params.get("is_home") is True:
                subset = [r for r in subset if r["is_home"]]
                desc_parts.append("HOME")
            if params.get("pp1") is True:
                subset = [r for r in subset if r["pp1"]]
                desc_parts.append("PP1")
            
            for key, val in params.items():
                if key in ("is_home", "pp1"):
                    continue
                if val <= 0:
                    continue
                
                feat_name = key.replace("_min", "")
                # Map param name to DB column
                col_map = {
                    "season_g": "season_g", "sog": "sog", "hdcf": "hdcf",
                    "ixg": "ixg", "ga_g": "ga_g", "season_a": "season_a",
                    "l10_a": "l10_a", "atoi": "atoi", "season_pts": "season_pts",
                    "l10_pts": "l10_pts",
                }
                db_col = col_map.get(feat_name, feat_name)
                
                if feat_name in ("ga_g",):
                    # Pour GA_G, on veut les adversaires FAIBLES (GA élevé)
                    subset = [r for r in subset if float(r[db_col] or 0) >= val]
                    desc_parts.append(f"opp_ga>={val}")
                else:
                    subset = [r for r in subset if float(r[db_col] or 0) >= val]
                    desc_parts.append(f"{feat_name}>={val}")
            
            w, t, wr_val = winrate(subset, result_col)
            if t >= MIN_SAMPLE:
                desc = " + ".join(desc_parts) if desc_parts else "ALL"
                results.append((wr_val, w, t, desc, params))
        
        # Trier par winrate décroissant
        results.sort(key=lambda x: (-x[0], -x[2]))
        
        print(f"\n  TOP 15 configs (min {MIN_SAMPLE} picks) :")
        seen_wrs = set()
        count = 0
        for wr_val, w, t, desc, params in results:
            key = f"{wr_val:.1f}_{t}"
            if key in seen_wrs:
                continue
            seen_wrs.add(key)
            
            breakeven = 1 / (wr_val / 100) if wr_val > 0 else 999
            print(f"    {wr_val:.1f}% ({w}/{t}) | BE@{breakeven:.2f} | {desc}")
            count += 1
            if count >= 15:
                break
        
        # ═══════════════════════════════════════════════════
        # 6. APPROCHES NON-CONVENTIONNELLES
        # ═══════════════════════════════════════════════════
        section(f"APPROCHES NON-CONVENTIONNELLES — {market_name}")
        
        # A. Régression vers la moyenne : PDO bas = chance en notre faveur
        print("\n  --- PDO (régression vers la moyenne) ---")
        for pdo_max in [96, 97, 98, 99, 100]:
            subset = [r for r in rows if float(r["pdo"] or 100) <= pdo_max and r["is_home"]]
            w, t, wr_val = winrate(subset, result_col)
            if t >= MIN_SAMPLE:
                print(f"    HOME + PDO <= {pdo_max}: {w}/{t} ({wr_val:.1f}%)")
        
        # B. "Shark" : Forme récente TRÈS chaude
        print(f"\n  --- Forme recente explosive ---")
        if market_name == "BUTS":
            for l10_min in [0.3, 0.4, 0.5, 0.6]:
                subset = [r for r in rows if float(r["l10_g"] or 0) >= l10_min and r["is_home"]]
                w, t, wr_val = winrate(subset, result_col)
                if t >= MIN_SAMPLE:
                    print(f"    HOME + L10_G >= {l10_min}: {w}/{t} ({wr_val:.1f}%)")
        elif market_name == "ASSISTS":
            for l10_min in [0.4, 0.6, 0.8, 1.0]:
                subset = [r for r in rows if float(r["l10_a"] or 0) >= l10_min and r["is_home"]]
                w, t, wr_val = winrate(subset, result_col)
                if t >= MIN_SAMPLE:
                    print(f"    HOME + L10_A >= {l10_min}: {w}/{t} ({wr_val:.1f}%)")
        else:
            for l10_min in [0.4, 0.6, 0.8, 1.0]:
                subset = [r for r in rows if float(r["l10_pts"] or 0) >= l10_min and r["is_home"]]
                w, t, wr_val = winrate(subset, result_col)
                if t >= MIN_SAMPLE:
                    print(f"    HOME + L10_Pts >= {l10_min}: {w}/{t} ({wr_val:.1f}%)")
        
        # C. "Underdog" : Adversaire très faible (GA élevé + PK bas)
        print(f"\n  --- Adversaire faible (GA eleve + PK bas) ---")
        for ga_min in [2.8, 3.0, 3.2]:
            for pk_max in [85, 82, 80, 78]:
                subset = [r for r in rows 
                         if float(r["ga_g"] or 0) >= ga_min 
                         and float(r["pk_pct"] or 80) <= pk_max
                         and r["is_home"]]
                w, t, wr_val = winrate(subset, result_col)
                if t >= MIN_SAMPLE:
                    print(f"    HOME + opp_GA>={ga_min} + opp_PK<={pk_max}: {w}/{t} ({wr_val:.1f}%)")
        
        # D. PP1 + Adversaire faible en PK
        print(f"\n  --- PP1 + adversaire faible PK ---")
        for pk_max in [85, 82, 80, 78, 75]:
            subset = [r for r in rows 
                     if r["pp1"] and float(r["pk_pct"] or 80) <= pk_max]
            w, t, wr_val = winrate(subset, result_col)
            if t >= MIN_SAMPLE:
                print(f"    PP1 + opp_PK<={pk_max}: {w}/{t} ({wr_val:.1f}%)")
        
        # E. Backup goalie adverse
        print(f"\n  --- Backup goalie adverse ---")
        subset = [r for r in rows if r["backup"] and r["is_home"]]
        w, t, wr_val = winrate(subset, result_col)
        if t >= MIN_SAMPLE:
            print(f"    HOME + BACKUP: {w}/{t} ({wr_val:.1f}%)")
        else:
            print(f"    HOME + BACKUP: {w}/{t} (trop peu de donnees)")
        
        # F. ConsecGoals (série en cours)
        if market_name == "BUTS":
            print(f"\n  --- Streaks (ConsecGoals) ---")
            for streak in [1, 2, 3]:
                subset = [r for r in rows 
                         if int(r["consec_goals"] or 0) >= streak and r["is_home"]]
                w, t, wr_val = winrate(subset, result_col)
                if t >= MIN_SAMPLE:
                    print(f"    HOME + streak>={streak}: {w}/{t} ({wr_val:.1f}%)")
                elif t > 0:
                    print(f"    HOME + streak>={streak}: {w}/{t} ({wr_val:.1f}%) [petit echantillon]")
        
        # G. ATOI élevé (grosses minutes = plus d'opportunités)
        print(f"\n  --- Temps de glace eleve ---")
        for atoi_min in [16, 18, 19, 20, 21]:
            subset = [r for r in rows 
                     if float(r["atoi"] or 0) >= atoi_min and r["is_home"]]
            w, t, wr_val = winrate(subset, result_col)
            if t >= MIN_SAMPLE:
                print(f"    HOME + ATOI>={atoi_min}: {w}/{t} ({wr_val:.1f}%)")
        
        # H. Combinaison "TOUT" : Home + PP1 + gros ATOI + bonne forme
        print(f"\n  --- Combinaisons 'Elite' ---")
        if market_name == "BUTS":
            combos_elite = [
                ("HOME+PP1+SG>=0.3+SOG>=2.5", 
                 lambda r: r["is_home"] and r["pp1"] and float(r["season_g"] or 0) >= 0.3 and float(r["sog"] or 0) >= 2.5),
                ("HOME+PP1+ixG>=0.35+HDCF>=2.0",
                 lambda r: r["is_home"] and r["pp1"] and float(r["ixg"] or 0) >= 0.35 and float(r["hdcf"] or 0) >= 2.0),
                ("HOME+iXG>=0.35+HDCF>=2+L10G>=0.2",
                 lambda r: r["is_home"] and float(r["ixg"] or 0) >= 0.35 and float(r["hdcf"] or 0) >= 2.0 and float(r["l10_g"] or 0) >= 0.2),
                ("HOME+SG>=0.30+ATOI>=18+SOG>=2.5",
                 lambda r: r["is_home"] and float(r["season_g"] or 0) >= 0.30 and float(r["atoi"] or 0) >= 18 and float(r["sog"] or 0) >= 2.5),
                ("PP1+SG>=0.30+oppGA>=2.8",
                 lambda r: r["pp1"] and float(r["season_g"] or 0) >= 0.30 and float(r["ga_g"] or 0) >= 2.8),
                ("HOME+PP1+HDCF>=2+oppGA>=2.8",
                 lambda r: r["is_home"] and r["pp1"] and float(r["hdcf"] or 0) >= 2.0 and float(r["ga_g"] or 0) >= 2.8),
            ]
        elif market_name == "ASSISTS":
            combos_elite = [
                ("HOME+PP1+SA>=0.50+L10A>=0.60",
                 lambda r: r["is_home"] and r["pp1"] and float(r["season_a"] or 0) >= 0.50 and float(r["l10_a"] or 0) >= 0.60),
                ("HOME+SA>=0.40+L10A>=0.60+ATOI>=18",
                 lambda r: r["is_home"] and float(r["season_a"] or 0) >= 0.40 and float(r["l10_a"] or 0) >= 0.60 and float(r["atoi"] or 0) >= 18),
                ("PP1+SA>=0.50+oppGA>=2.8",
                 lambda r: r["pp1"] and float(r["season_a"] or 0) >= 0.50 and float(r["ga_g"] or 0) >= 2.8),
                ("HOME+PP1+SA>=0.40+ATOI>=18",
                 lambda r: r["is_home"] and r["pp1"] and float(r["season_a"] or 0) >= 0.40 and float(r["atoi"] or 0) >= 18),
                ("HOME+SA>=0.50+L10A>=0.80",
                 lambda r: r["is_home"] and float(r["season_a"] or 0) >= 0.50 and float(r["l10_a"] or 0) >= 0.80),
                ("PP1+oppPK<=80+SA>=0.40",
                 lambda r: r["pp1"] and float(r["pk_pct"] or 80) <= 80 and float(r["season_a"] or 0) >= 0.40),
            ]
        else:
            combos_elite = [
                ("HOME+SP>=0.70+L10P>=0.60",
                 lambda r: r["is_home"] and float(r["season_pts"] or 0) >= 0.70 and float(r["l10_pts"] or 0) >= 0.60),
                ("HOME+PP1+SP>=0.60",
                 lambda r: r["is_home"] and r["pp1"] and float(r["season_pts"] or 0) >= 0.60),
                ("HOME+SP>=0.80+ATOI>=18",
                 lambda r: r["is_home"] and float(r["season_pts"] or 0) >= 0.80 and float(r["atoi"] or 0) >= 18),
                ("HOME+SP>=0.60+L10P>=0.60+ATOI>=18",
                 lambda r: r["is_home"] and float(r["season_pts"] or 0) >= 0.60 and float(r["l10_pts"] or 0) >= 0.60 and float(r["atoi"] or 0) >= 18),
                ("PP1+SP>=0.70+oppGA>=2.8",
                 lambda r: r["pp1"] and float(r["season_pts"] or 0) >= 0.70 and float(r["ga_g"] or 0) >= 2.8),
                ("HOME+PP1+SP>=0.70+ATOI>=18",
                 lambda r: r["is_home"] and r["pp1"] and float(r["season_pts"] or 0) >= 0.70 and float(r["atoi"] or 0) >= 18),
            ]
        
        elite_results = []
        for desc, filt in combos_elite:
            subset = [r for r in rows if filt(r)]
            w, t, wr_val = winrate(subset, result_col)
            elite_results.append((wr_val, w, t, desc))
        
        elite_results.sort(reverse=True)
        for wr_val, w, t, desc in elite_results:
            flag = "" if t >= MIN_SAMPLE else " [PETIT ECHANTILLON]"
            print(f"    {wr_val:.1f}% ({w}/{t}) | {desc}{flag}")
    
    # ═══════════════════════════════════════════════════
    # 7. LOGISTIC REGRESSION - Quelles features comptent vraiment ?
    # ═══════════════════════════════════════════════════
    section("REGRESSION LOGISTIQUE — Features qui predisent reellement")
    
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import cross_val_score
        
        feat_cols = [
            "season_g", "season_a", "season_pts", 
            "l10_g", "l10_a", "l10_pts",
            "ixg", "hdcf", "sog", "atoi", "pdo",
            "ga_g", "pk_pct", "hdca_g", "cf_pct",
            "consec_goals", "is_home", "pp1", "backup", "b2b",
        ]
        
        for market_name, result_col in [("BUTS", "but"), ("ASSISTS", "assist"), ("POINTS", "point")]:
            X = np.array([[float(r[f] or 0) for f in feat_cols] for r in rows])
            y = np.array([1 if r[result_col] and int(r[result_col]) > 0 else 0 for r in rows])
            
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            
            model = LogisticRegression(max_iter=1000, C=0.1)
            scores = cross_val_score(model, X_scaled, y, cv=5, scoring='accuracy')
            
            model.fit(X_scaled, y)
            coefs = list(zip(feat_cols, model.coef_[0]))
            coefs.sort(key=lambda x: abs(x[1]), reverse=True)
            
            print(f"\n  {market_name} — CV Accuracy: {scores.mean()*100:.1f}% (+/- {scores.std()*100:.1f}%)")
            print(f"  Top features (par importance) :")
            for feat, coef in coefs[:8]:
                direction = "+" if coef > 0 else "-"
                print(f"    {direction} {feat:18s}: {coef:+.3f}")
    
    except ImportError:
        print("  sklearn non installe - skip regression logistique")
    
    # ═══════════════════════════════════════════════════
    # RÉSUMÉ FINAL
    # ═══════════════════════════════════════════════════
    section("RESUME FINAL — MEILLEURE CONFIG PAR MARCHE")
    print("""
  Ce script a explore les approches suivantes :
  
  1. Chaque feature individuellement (correlation avec resultat)
  2. Chaque flag (HOME, PP1, BACKUP, B2B)
  3. Grid search systematique sur les seuils
  4. Combinaisons multi-criteres intelligentes
  5. Regression vers la moyenne (PDO)
  6. Forme recente explosive
  7. Faiblesse adverse (GA + PK)
  8. PP1 + PK adverse faible
  9. Backup goalie
  10. Streaks (serie de buts)
  11. Temps de glace
  12. Regression logistique (ML simple)
  
  Regarde les resultats ci-dessus pour identifier les configs 
  avec le meilleur WR ET un echantillon >= 30 picks.
  
  ATTENTION : Meme avec >= 30 picks, les resultats restent
  sensibles au bruit statistique. Les vrais gagnants sont ceux
  qui ont un WR eleve ET un grand echantillon.
""")


if __name__ == "__main__":
    main()
