"""
Script hebdomadaire pour recalculer les probabilités réelles des picks basées sur la DB.
Utilise un lissage bayésien pour éviter les probas extrêmes si peu de data.
Met à jour config/probas.json.
"""
import sqlite3
import json
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)
os.chdir(root)

DB_PATH = "bot_database.db"
PROBAS_JSON = "config/probas.json"

# Priors Bayésiens très conservateurs (basés sur les moyennes de la ligue)
# Si on a 0 data, voila les probas qu'on aura.
PRIORS = {
    "buteurs":   {"prior_wr": 0.15, "weight": 20}, # C'est dur de marquer
    "passeurs":  {"prior_wr": 0.35, "weight": 20},
    "pointeurs": {"prior_wr": 0.50, "weight": 50}  # Beaucoup de data
}

def bayesian_smoothing(success, total, prior_wr, weight):
    """Lissage bayésien : (succès réels + prior_wr*weight) / (total réel + weight)"""
    return (success + prior_wr * weight) / (total + weight)

def fetch_stats():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    stats = {}
    
    for tbl, col, market in [("picks", "but", "buteurs"), ("picks_assists", "assist", "passeurs"), ("picks_points", "point", "pointeurs")]:
        # Récupérer les verdicts réels non nuls
        c.execute(f"SELECT COUNT(*) as total, SUM(CASE WHEN {col} > 0 THEN 1 ELSE 0 END) as won FROM {tbl} WHERE {col} IS NOT NULL")
        row = c.fetchone()
        
        total = row["total"] or 0
        won = row["won"] or 0
        
        # Bayes smoothing
        prior_wr = PRIORS[market]["prior_wr"]
        weight = PRIORS[market]["weight"]
        smoothed_proba = bayesian_smoothing(won, total, prior_wr, weight)
        
        # Winrate brut (informatif)
        raw_wr = won / total if total > 0 else 0.0
        
        stats[market] = {
            "total_picks": total,
            "won_picks": won,
            "raw_wr": round(raw_wr, 4),
            "proba": round(smoothed_proba, 4)
        }
        
    conn.close()
    return stats

def main():
    print("Recalcul des probabilités réelles des modèles...")
    stats = fetch_stats()
    
    os.makedirs(os.path.dirname(PROBAS_JSON), exist_ok=True)
    with open(PROBAS_JSON, "w") as f:
        json.dump(stats, f, indent=4)
        
    for market, s in stats.items():
        print(f"{market.upper()}:")
        print(f"  Picks resolus : {s['won_picks']}/{s['total_picks']} ({s['raw_wr'] * 100:.1f}%)")
        print(f"  Proba LISSÉE  : {s['proba'] * 100:.1f}%\n")
        
    print(f"[OK] Mis à jour : {PROBAS_JSON}")

if __name__ == "__main__":
    main()
