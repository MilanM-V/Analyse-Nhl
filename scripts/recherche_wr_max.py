"""
Recherche du Winrate Absolu Maximum sur les Buteurs.
"""
import sqlite3
import pandas as pd
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot_database.db")

def main():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM players WHERE but IS NOT NULL AND but != ''", conn)
    conn.close()
    
    numeric_cols = ['ixg', 'hdcf', 'sog', 'season_g', 'score_but', 'is_home', 'but']
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    df['scored'] = (df['but'] > 0).astype(int)
    
    # Grid search plus agressive
    qs_list = [10.0, 10.5, 11.0, 11.5]
    sog_list = [2.0, 2.5, 3.0, 3.5, 4.0]
    hdcf_list = [2.0, 2.5, 3.0, 3.5]
    sg_list = [0.30, 0.35, 0.40, 0.45]
    
    results = []
    
    for qs in qs_list:
        for sog in sog_list:
            for hdcf in hdcf_list:
                for sg in sg_list:
                    # Test Seulement Domicile
                    mask = (df['score_but'] >= qs) & (df['sog'] >= sog) & \
                           (df['hdcf'] >= hdcf) & (df['season_g'] >= sg) & \
                           (df['is_home'] == 1)
                           
                    subset = df[mask]
                    total = len(subset)
                    
                    if total > 0:
                        won = subset['scored'].sum()
                        wr = won / total * 100
                        results.append({
                            'qs': qs, 'sog': sog, 'hdcf': hdcf, 'sg': sg,
                            'total': total, 'won': won, 'wr': wr
                        })
                        
    res_df = pd.DataFrame(results)
    
    print("=== RECHERCHE DU WINRATE MAXIMAL ===\n")
    
    for min_picks in [5, 15, 30, 50]:
        print(f"--- En exigeant au moins {min_picks} picks sur 2 semaines ---")
        valid = res_df[res_df['total'] >= min_picks]
        if valid.empty:
            print("  Aucune configuration ne donne autant de picks.")
            continue
            
        top = valid.sort_values('wr', ascending=False).iloc[0]
        print(f"  Max WR: {top['wr']:.1f}% ({int(top['won'])}/{int(top['total'])})")
        print(f"  Filtres: QS>={top['qs']}, HDCF>={top['hdcf']}, SOG>={top['sog']}, SG>={top['sg']}")
        print()

if __name__ == "__main__":
    main()
