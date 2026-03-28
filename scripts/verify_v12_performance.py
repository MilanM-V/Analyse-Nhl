import sqlite3
import pandas as pd
import math
import os
import joblib
import predictor_v11

# Configuration
ODDS_AVG = 2.6
STAKE = 1.0

def _get_new_categorie(score, hdcf):
    if score >= 11.5 and hdcf >= 2.8: return "ELITE"
    if score >= 10.0 and hdcf >= 2.0: return "SAFE"
    if score >= 8.5 and hdcf >= 1.8: return "JOUABLE"
    return None

def main():
    conn = sqlite3.connect('bot_database.db')
    # Charger tous les picks terminés
    df = pd.read_sql_query("SELECT * FROM picks WHERE but IS NOT NULL AND but != ''", conn)
    conn.close()

    # Nettoyage des données
    for col in ['score', 'hdcf', 'ixg', 'sog', 'atoi', 'l10_g', 'season_g', 'pdo', 'ga_g', 'cf_pct', 'hdca_g', 'pk_pct', 'rebounds', 'rush']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
    
    df['but'] = pd.to_numeric(df['but'], errors='coerce')
    df['win'] = (df['but'] > 0).astype(int)

    results = []

    print("--- RE-CALCUL DES SCORES AVEC LA NOUVELLE LOGIQUE V12 ---")
    
    for _, row in df.iterrows():
        # Reconstruction des objets pour calculate_base_qs
        v5_stats = {
            'G_GP': row['season_g'],
            'PDO': row['pdo'],
            'Position': 'F' # On assume Attaquant pour le test
        }
        p_form = {
            'L10_ixG_G': row['ixg'],
            'L10_iHDCF_G': row['hdcf'],
            'L10_SOG_G': row['sog'],
            'ATOI': row['atoi'],
            'L10_G_G': row['l10_g'],
            'L10_Rebounds_G': row['rebounds'],
            'L10_Rush_G': row['rush']
        }
        opp_stats = {
            'GA_G': row['ga_g'],
            'CF_pct': row['cf_pct'],
            'HDCA_G': row['hdca_g'],
            'PK%': row['pk_pct']
        }
        
        is_pp1 = str(row['pp1']).lower() in ['true', '1', 'oui', '⭐']
        is_backup = str(row['backup']).lower() in ['true', '1', 'oui']
        is_b2b = str(row['b2b']).lower() in ['true', '1', 'oui']

        # Calcul du nouveau score QS
        new_score = predictor_v11.calculate_base_qs(
            v5_stats, p_form, opp_stats, 
            is_pp1, False, False, is_backup, is_b2b
        )
        
        # Nouvelle catégorie
        new_cat = _get_new_categorie(new_score, row['hdcf'])
        
        if new_cat:
            results.append({
                'joueur': row['joueur'],
                'new_score': new_score,
                'new_cat': new_cat,
                'win': row['win']
            })

    new_df = pd.DataFrame(results)
    
    if new_df.empty:
        print("Aucun pick trouvé avec la nouvelle logique.")
        return

    print("\n" + "="*40)
    print("RÉSULTATS APRÈS REFONTE V12 (Simulé)")
    print("="*40)

    total_bets = len(new_df)
    total_wins = new_df['win'].sum()
    wr_total = (total_wins / total_bets) * 100 if total_bets > 0 else 0

    print(f"Total des paris retenus : {total_bets} / 200")
    print(f"Winrate Global V12      : {wr_total:.1f}%")
    
    # Rapport par catégorie
    for cat in ['ELITE', 'SAFE', 'JOUABLE']:
        cat_df = new_df[new_df['new_cat'] == cat]
        if not cat_df.empty:
            c_win = cat_df['win'].sum()
            c_total = len(cat_df)
            c_wr = (c_win / c_total) * 100
            print(f"  {cat:8s} : {c_win}/{c_total} = {c_wr:.1f}%")

    # Calcul des gains
    # Gain = (Mises gagnantes * Cote * Mise) - (Mises totales * Mise)
    profit = (total_wins * ODDS_AVG * STAKE) - (total_bets * STAKE)
    roi = (profit / (total_bets * STAKE)) * 100 if total_bets > 0 else 0

    print("\n" + "="*40)
    print("ESTIMATION FINANCIÈRE (Basée sur tes 200 données)")
    print("="*40)
    print(f"Mise par pari      : {STAKE:.2f} €")
    print(f"Cote moyenne       : {ODDS_AVG:.2f}")
    print(f"Profit Net (réel)  : {profit:.2f} €")
    print(f"ROI                : {roi:.1f} %")

    # Extrapolations (On considère que 200 picks = 1 mois comme dans tes logs)
    # Note: 200 picks correspondent à la session enregistrée (Mars 2026).
    print("\nEXTRAPOLATION :")
    print(f"Gain estimé / mois : {profit:.2f} €")
    print(f"Gain estimé / an   : {profit * 12:.2f} €")

if __name__ == "__main__":
    main()
