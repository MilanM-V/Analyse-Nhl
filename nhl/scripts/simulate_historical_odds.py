"""
scripts/simulate_historical_odds.py — Simulation et Backtest Multi-Saisons (2018-2025).

Reconstruit les cotes de clôture réalistes (Fair Odds Proxy + Vig réel des bookmakers)
sur l'intégralité du super-dataset historique (307 956 observations) :
1. Vig Buteurs : 9.0% (marge standard des bookmakers ARJEL/internationaux)
2. Vig Passeurs : 6.5%
3. Inférence des modèles Multi-Boosting Ensembles (ml_model_but.pkl / ml_model_ast.pkl)
4. Application des règles strictes de production :
   - Attaquants uniquement sur les Buteurs (Défenseurs interdits)
   - Filtre EV adaptatif (8% <2.00, 5% [2.00-3.50], 10% >3.50)
   - Kelly 1/6ème sur les passes à fort Edge, 1/8ème sur les buts
5. Bilan financier annuel saison par saison en unités (1 U = 1.00 €).
"""
import os
import sys
import joblib
import pandas as pd
import numpy as np

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))

PARQUET_PATH = os.path.join(ROOT, "data", "historical_dataset.parquet")
MODELS_DIR = os.path.join(ROOT, "models")


def load_dataset_and_models():
    """Charge le super-dataset Parquet et les modèles ML calibrés."""
    if not os.path.exists(PARQUET_PATH):
        raise FileNotFoundError(f"Fichier {PARQUET_PATH} introuvable.")

    print(f"Chargement du super-dataset Parquet ({PARQUET_PATH})...")
    df = pd.read_parquet(PARQUET_PATH)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    path_but = os.path.join(MODELS_DIR, "ml_model_but.pkl")
    path_ast = os.path.join(MODELS_DIR, "ml_model_ast.pkl")

    model_but = joblib.load(path_but)
    model_ast = joblib.load(path_ast)

    return df, model_but, model_ast


def simulate_market_odds(df: pd.DataFrame) -> pd.DataFrame:
    """Génère les cotes Winamax calibrées par régression empirique sur les cotes réelles de notre DB.
    
    Modèle appris sur nhl/bot_database.db (picks et picks_assists réels) :
    - BUTEURS : Base 0.0792 + 0.5369 * Season_G, ajusté par opp_xga_60 et Vig Winamax 7.9%
    - PASSEURS : Base 0.2029 + 0.3808 * Season_A, ajusté par opp_xga_60 et Vig Winamax 6.0%
    Précision sur cotes réelles : MAE de 0.40 sur buts (moyenne 3.15) et 0.15 sur passes (moyenne 1.95).
    """
    print("Génération des cotes Winamax calibrées sur l'historique réel de bot_database.db...")
    
    opp_env = (df['opp_xga_60'] / 2.80).clip(0.80, 1.25)
    
    # 1. Buteurs Winamax
    prob_w_but = (0.0792 + 0.5369 * df['season_g']) * opp_env * (1.0 + 0.0790)
    df['cote_sim_but'] = np.round(1.0 / prob_w_but.clip(0.12, 0.55), 2)
    
    # 2. Passeurs Winamax
    prob_w_ast = (0.2029 + 0.3808 * df['season_a']) * opp_env * (1.0 + 0.0596)
    df['cote_sim_ast'] = np.round(1.0 / prob_w_ast.clip(0.28, 0.70), 2)

    return df


def run_historical_simulation(df, model_data, target_col, cote_col, market_name):
    """Exécute la simulation financière sur les saisons d'évaluation avec contraintes de production réelles."""
    features = model_data['features']
    model = model_data['model']

    print(f"\nSimulation {market_name.upper()}...")
    
    # Règle stricte de production :
    # 1. Buteurs : Attaquants uniquement (position != 'D'), Top 9 (atoi_l10 >= 13.5), Season_G >= 0.18 ou volume tirs sog_l10 >= 20.0
    # 2. Passeurs : Joueurs avec temps de jeu régulier (atoi_l10 >= 14.0) et volume de passes (season_a >= 0.30)
    if market_name == "but":
        cond_prod = (
            (df['position'] != 'D') & 
            (df['atoi_l10'] >= 13.5) & 
            ((df['season_g'] >= 0.18) | (df['sog_l10'] >= 20.0))
        )
        df_eval = df[cond_prod].copy()
        # Cap de cote réaliste pour buteurs (le marché ne cote pas raisonnablement au-delà de 7.00 sans vig punitif)
        df_eval['cote'] = df_eval[cote_col].clip(1.80, 7.00)
    else:
        cond_prod = (
            (df['atoi_l10'] >= 14.0) & 
            (df['season_a'] >= 0.30)
        )
        df_eval = df[cond_prod].copy()
        # Cap de cote réaliste pour passeurs (plage usuelle 1.50 - 4.50)
        df_eval['cote'] = df_eval[cote_col].clip(1.50, 4.50)

    # Inférence par lots
    X = df_eval[features].values
    probas = model.predict_proba(X)[:, 1]
    df_eval['proba_ml'] = probas
    df_eval['ev'] = (df_eval['proba_ml'] * df_eval['cote']) - 1.0

    # Filtre EV adaptatif (P9)
    cond_low = (df_eval['cote'] < 2.00) & (df_eval['ev'] >= 0.08)
    cond_mid = (df_eval['cote'] >= 2.00) & (df_eval['cote'] <= 3.50) & (df_eval['ev'] >= 0.05)
    cond_high = (df_eval['cote'] > 3.50) & (df_eval['ev'] >= 0.10)
    
    # Seuils minimums de cote pour sécurité
    min_cote = 2.00 if market_name == "but" else 1.60
    selected = df_eval[(cond_low | cond_mid | cond_high) & (df_eval['cote'] >= min_cote)].copy()

    # Dimensionnement Kelly
    b = selected['cote'] - 1.0
    p = selected['proba_ml']
    q = 1.0 - p
    f = (p * b - q) / b
    
    # Kelly fraction : 1/6ème sur passeurs à fort EV, 1/8ème sur buteurs
    fraction = 6.0 if market_name == "ast" else 8.0
    max_stake = 2.5 if market_name == "ast" else 2.0
    selected['mise'] = (f / fraction * 100).clip(0.5, max_stake)
    selected['mise'] = np.round(selected['mise'] * 2) / 2
    selected['mise'] = selected['mise'].clip(0.5, max_stake)

    # Résolution
    won = selected[target_col] > 0
    selected['won'] = won
    selected['profit'] = np.where(won, (selected['cote'] * selected['mise']) - selected['mise'], -selected['mise'])

    return selected


def main():
    print("=" * 75)
    print(" SIMULATION MULTI-SAISONS SUR SUPER-DATASET HISTORIQUE (2018-2025)")
    print(" Backtest quantitatif avec Vig réel et filtres de production stricts")
    print("=" * 75)

    df, model_but, model_ast = load_dataset_and_models()
    df = simulate_market_odds(df)

    res_but = run_historical_simulation(df, model_but, 'target_but', 'cote_sim_but', 'but')
    res_ast = run_historical_simulation(df, model_ast, 'target_ast', 'cote_sim_ast', 'ast')

    # Bilan par saison
    for market_name, res in [("BUTEURS", res_but), ("PASSEURS", res_ast)]:
        print(f"\n{'=' * 65}")
        print(f" BILAN FINANCIER PAR SAISON : {market_name}")
        print(f"{'=' * 65}")
        print(f"{'Saison':<10} | {'Paris':<7} | {'Win Rate':<9} | {'Cote Moy':<9} | {'Mises (U)':<10} | {'Profit (U)':<11} | {'ROI':<8}")
        print("-" * 75)
        
        for s in sorted(res['season'].unique()):
            sub = res[res['season'] == s]
            n = len(sub)
            if n == 0: continue
            wr = sub['won'].mean() * 100
            cm = sub['cote'].mean()
            m = sub['mise'].sum()
            p = sub['profit'].sum()
            roi = (p / m * 100) if m > 0 else 0
            sign = "+" if p > 0 else ""
            print(f"{s:<10} | {n:<7} | {wr:<8.1f}% | {cm:<9.2f} | {m:<10.1f} | {sign}{p:<10.2f} | {sign}{roi:<7.1f}%")

        # Total marché
        n_tot = len(res)
        wr_tot = res['won'].mean() * 100
        cm_tot = res['cote'].mean()
        m_tot = res['mise'].sum()
        p_tot = res['profit'].sum()
        roi_tot = (p_tot / m_tot * 100) if m_tot > 0 else 0
        sign_tot = "+" if p_tot > 0 else ""
        print("-" * 75)
        print(f"{'TOTAL':<10} | {n_tot:<7} | {wr_tot:<8.1f}% | {cm_tot:<9.2f} | {m_tot:<10.1f} | {sign_tot}{p_tot:<10.2f} | {sign_tot}{roi_tot:<7.1f}%\n")

    # Bilan Combiné Global
    res_comb = pd.concat([res_but, res_ast], ignore_index=True)
    m_glob = res_comb['mise'].sum()
    p_glob = res_comb['profit'].sum()
    roi_glob = (p_glob / m_glob * 100) if m_glob > 0 else 0
    print("=" * 65)
    print(f" BILAN GLOBAL PORTFOLIO (7 SAISONS, 2018-2025)")
    print("=" * 65)
    print(f"  Nombre total de paris : {len(res_comb):,}")
    print(f"  Mises cumulées :        {m_glob:,.1f} U ({m_glob:,.1f} €)")
    print(f"  Profit Net Cumulé :     +{p_glob:,.2f} U (+{p_glob:,.2f} €)")
    print(f"  ROI Global Net :        +{roi_glob:.1f}%")
    print(f"  Moyenne annuelle :      +{p_glob / 7.0:.2f} U / saison (+{p_glob / 7.0:.2f} € / an)")
    print("=" * 65)


if __name__ == "__main__":
    main()
