"""
TRUTH CHECK - Pourquoi les winrates de 70%+ annonces hier etaient faux.

Ce script reproduit EXACTEMENT la methode utilisee hier pour generer les
"82.9% Assists / 100% Points / 78.8% Buts" et montre le probleme.
"""
import sqlite3
import pandas as pd
import numpy as np
import os
import sys
import joblib

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)
os.chdir(root)

DB_PATH = "bot_database.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    
    # ============================================================
    # PROBLEME 1 : Le modele a ete entraine sur les MEMES donnees
    # utilisees pour le backtest = OVERFITTING
    # ============================================================
    print("=" * 70)
    print("PROBLEME 1 : OVERFITTING (Train = Test = memes donnees)")
    print("=" * 70)
    
    df = pd.read_sql("SELECT * FROM players WHERE but IS NOT NULL AND but != ''", conn)
    print(f"\n  Donnees totales dans 'players' : {len(df)} lignes")
    print(f"  Plage de dates : {df['date'].min()} -> {df['date'].max()}")
    print(f"  Le modele XGBoost a ete entraine sur ces {len(df)} lignes")
    print(f"  Le 'backtest' de hier a aussi ete fait sur ces {len(df)} lignes")
    print(f"  => C'est comme reviser avec les reponses de l'examen puis")
    print(f"     se vanter d'avoir eu 100%.")
    
    # ============================================================
    # PROBLEME 2 : Predictions du modele sur ses propres donnees
    # vs sur des donnees inconnues
    # ============================================================
    print("\n" + "=" * 70)
    print("PROBLEME 2 : Comparaison Train vs Test reel")
    print("=" * 70)
    
    # Charger le modele BUT
    model_path = os.path.join(root, 'models', 'xg_model_but.pkl')
    if os.path.exists(model_path):
        model_data = joblib.load(model_path)
        m = model_data['model']
        
        # Preparer les features exactement comme le training
        df_train = df.copy()
        df_train = df_train.rename(columns={
            'ixg': 'ixg_l10', 'hdcf': 'hdcf_l10', 'sog': 'sog_l10', 'atoi': 'atoi_l10'
        })
        
        for col in ['pp1', 'is_home', 'b2b', 'opp_b2b', 'but']:
            if col in df_train.columns:
                df_train[col] = pd.to_numeric(df_train[col], errors='coerce').fillna(0).astype(int)
        
        df_train['is_b2b'] = df_train['b2b']
        df_train['opp_is_b2b'] = df_train.get('opp_b2b', 0)
        df_train['luck_factor'] = 1.0
        df_train['ixg_x_hdcf'] = df_train['ixg_l10'] * df_train['hdcf_l10']
        df_train['sog_x_atoi'] = df_train['sog_l10'] * df_train['atoi_l10']
        df_train['ixg_x_ga'] = df_train['ixg_l10'] * df_train['ga_g']
        df_train['streak_x_ixg'] = df_train['consec_goals'] * df_train['ixg_l10']
        df_train['qs_v10'] = df_train['score_but']
        
        features = [
            'ixg_l10', 'hdcf_l10', 'sog_l10', 'atoi_l10', 'season_g',
            'ga_g', 'hdca_g', 'pp1', 'is_home', 'is_b2b', 'opp_is_b2b',
            'consec_goals', 'qs_v10',
            'luck_factor', 'ixg_x_hdcf', 'sog_x_atoi', 'ixg_x_ga', 'streak_x_ixg'
        ]
        
        # Remplir NaN
        for f in features:
            if f not in df_train.columns:
                df_train[f] = 0
            df_train[f] = pd.to_numeric(df_train[f], errors='coerce').fillna(0)
        
        X = df_train[features].values
        y = df_train['but'].apply(lambda x: 1 if x > 0 else 0).values
        
        # Predictions sur les donnees d'entrainement (= ce qui a ete montre hier)
        probas = m.predict_proba(X)[:, 1]
        
        # Reproduire le filtre "Sniper" exact de hier
        qs_threshold = 10.25
        xgb_threshold = 0.70
        
        mask = (df_train['score_but'] >= qs_threshold) & (probas >= xgb_threshold)
        picks_train = y[mask]
        probas_train = probas[mask]
        
        if len(picks_train) > 0:
            wr_train = picks_train.sum() / len(picks_train) * 100
            print(f"\n  BUTS sur donnees d'ENTRAINEMENT (ce qui a ete montre hier):")
            print(f"  Seuils: QS >= {qs_threshold}, XGB >= {xgb_threshold}")
            print(f"  Picks: {len(picks_train)} | Won: {picks_train.sum()} | Winrate: {wr_train:.1f}%")
            print(f"  Proba IA moyenne: {probas_train.mean():.2f}")
        
        # Maintenant, validation croisee honnete (Leave-One-Out ou Train/Test split)
        print(f"\n  --- VALIDATION CROISEE HONNETE (80/20 split x5) ---")
        from sklearn.model_selection import StratifiedKFold
        from xgboost import XGBClassifier
        
        kf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        all_real_preds = []
        all_real_labels = []
        all_real_scores = []
        
        for fold, (train_idx, test_idx) in enumerate(kf.split(X, y)):
            X_tr, X_te = X[train_idx], X[test_idx]
            y_tr, y_te = y[train_idx], y[test_idx]
            qs_te = df_train['score_but'].values[test_idx]
            
            scale = (len(y_tr) - y_tr.sum()) / max(1, y_tr.sum())
            fold_model = XGBClassifier(
                n_estimators=150, max_depth=4, learning_rate=0.04,
                scale_pos_weight=scale, eval_metric='logloss', random_state=42
            )
            fold_model.fit(X_tr, y_tr)
            fold_probas = fold_model.predict_proba(X_te)[:, 1]
            
            mask_fold = (qs_te >= qs_threshold) & (fold_probas >= xgb_threshold)
            if mask_fold.sum() > 0:
                all_real_preds.extend(y_te[mask_fold].tolist())
                all_real_labels.extend(fold_probas[mask_fold].tolist())
                all_real_scores.extend(qs_te[mask_fold].tolist())
        
        if all_real_preds:
            real_wr = sum(all_real_preds) / len(all_real_preds) * 100
            print(f"\n  BUTS - Validation Croisee REELLE (donnees jamais vues):")
            print(f"  Picks: {len(all_real_preds)} | Won: {sum(all_real_preds)} | Winrate: {real_wr:.1f}%")
            print(f"  Proba IA moyenne: {np.mean(all_real_labels):.2f}")
            print(f"\n  >> ECART: {wr_train:.1f}% (hier) vs {real_wr:.1f}% (reel)")
        else:
            print("  Aucun pick passe le filtre en validation croisee (seuils trop hauts)")
    
    # ============================================================
    # PROBLEME 3 : Taille d'echantillon ridicule
    # ============================================================
    print("\n" + "=" * 70)
    print("PROBLEME 3 : Taille d'echantillon")
    print("=" * 70)
    
    # Recalcul de combien de picks passent chaque filtre
    df_all = pd.read_sql("SELECT * FROM players WHERE but IS NOT NULL AND but != '' AND date >= date('now', '-14 days')", conn)
    print(f"  Joueurs evalues (2 semaines): {len(df_all)}")
    print(f"  Avec score_but >= 10.25:  {len(df_all[df_all['score_but'] >= 10.25])}")
    
    for table, col, label in [
        ("picks", "but", "BUTS"),
        ("picks_assists", "assist", "ASSISTS"), 
        ("picks_points", "point", "POINTS")
    ]:
        c = conn.cursor()
        c.execute(f"""
            SELECT COUNT(*), SUM(CASE WHEN {col} > 0 THEN 1 ELSE 0 END)
            FROM {table} 
            WHERE {col} IS NOT NULL AND {col} != '' 
            AND date >= date('now', '-14 days')
        """)
        total, won = c.fetchone()
        won = won or 0
        wr = won/total*100 if total > 0 else 0
        print(f"  {label}: {won}/{total} ({wr:.1f}%)")
    
    # ============================================================
    # PROBLEME 4 : Le vrai test = picks REELS du bot
    # ============================================================
    print("\n" + "=" * 70)
    print("PROBLEME 4 : Le seul chiffre qui compte = les VRAIS picks du bot")
    print("=" * 70)
    
    # Les vrais picks sont dans picks, picks_assists, picks_points
    # PAS dans la table 'players' (qui contient tous les joueurs evalues)
    for table, col, label in [
        ("picks", "but", "BUTS"),
        ("picks_assists", "assist", "ASSISTS"),
        ("picks_points", "point", "POINTS")
    ]:
        c = conn.cursor()
        c.execute(f"""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN {col} > 0 THEN 1 ELSE 0 END) as won,
                   AVG(cote) as avg_cote
            FROM {table}
            WHERE {col} IS NOT NULL AND {col} != ''
            AND date >= date('now', '-14 days')
        """)
        total, won, avg_cote = c.fetchone()
        won = won or 0
        avg_cote = avg_cote or 0
        
        if total > 0:
            wr = won/total*100
            # ROI
            c.execute(f"""
                SELECT {col}, cote FROM {table}
                WHERE {col} IS NOT NULL AND {col} != ''
                AND date >= date('now', '-14 days')
            """)
            rows = c.fetchall()
            units = 0
            for res, cote in rows:
                cote = cote if cote else avg_cote
                if res and int(res) > 0:
                    units += (cote - 1)
                else:
                    units -= 1
            roi = units/total*100
            
            # Breakeven
            breakeven = (1/avg_cote)*100 if avg_cote > 0 else 0
            
            print(f"  {label}: {won}/{total} ({wr:.1f}%) | Cote moy:{avg_cote:.2f} | {units:+.1f} U ({roi:+.1f}% ROI)")
            print(f"          Breakeven requis: {breakeven:.1f}% | {'RENTABLE' if wr > breakeven else 'PAS RENTABLE'}")
    
    # ============================================================
    # CONCLUSION
    # ============================================================
    print("\n" + "=" * 70)
    print("CONCLUSION")
    print("=" * 70)
    print("""
  Les winrates de 70-100% montres hier etaient des ILLUSIONS causees par :

  1. OVERFITTING : Le modele a ete entraine et teste sur les memes donnees.
     C'est comme apprendre les reponses de l'examen par coeur.
     
  2. CHERRY-PICKING : Les seuils ont ete optimises APRES avoir vu les resultats,
     en choisissant les combinaisons qui donnaient les meilleurs chiffres.

  3. ECHANTILLON MINUSCULE : Avec seulement 5-10 picks qui passent les filtres
     super stricts, un seul pick en plus ou en moins change le winrate de 10%.

  4. DATA LEAKAGE : Le score QS (feature du modele) inclut deja le resultat
     dans sa construction quand on backteste sur les memes donnees.

  REALITE : Sur les 2 dernieres semaines de picks REELS du bot :
  - Buts: ~25-30% winrate (cotes hautes, mais pas assez pour compenser)
  - Assists: ~47% (proche du breakeven mais negatif)
  - Points: ~61% (le meilleur marche, mais cotes trop basses)
  - TOUS les marches sont en ROI NEGATIF.
""")
    
    conn.close()

if __name__ == "__main__":
    main()
