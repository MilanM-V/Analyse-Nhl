"""
Analyse exhaustive des combinés synergiques (Même équipe):
- Buteur + Passeur (Même équipe)
- Passeur + Passeur (Même équipe)
- Buteur + Buteur (Même équipe)
"""
import sqlite3
import pandas as pd
import numpy as np
import os
import joblib
from itertools import combinations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "bot_database.db")
MODELS_DIR = os.path.join(ROOT, "models")


def load_ev_picks():
    """Charge les picks EV+ avec vraies cotes, classés par date."""
    conn = sqlite3.connect(DB_PATH)
    models = {}
    for cat in ['but', 'ast']:
        path = os.path.join(MODELS_DIR, f'ml_model_{cat}.pkl')
        if os.path.exists(path):
            models[cat] = joblib.load(path)

    all_picks = []
    for table, cat, target_col in [("picks", "but", "but"), ("picks_assists", "ast", "assist")]:
        q = f"""
            SELECT p.date, p.joueur, p.equipe, p.adversaire, p.cote, p.{target_col} as result,
                   pl.ixg, pl.hdcf, pl.sog, pl.atoi, pl.season_g, pl.season_a, pl.season_pts,
                   pl.ga_g, pl.hdca_g, pl.pp1, pl.is_home, pl.b2b, pl.opp_b2b, pl.consec_goals
            FROM {table} p
            JOIN players pl ON p.date = pl.date AND p.joueur = pl.joueur
            WHERE p.cote IS NOT NULL AND p.cote > 1.05
        """
        try:
            df = pd.read_sql(q, conn)
        except Exception:
            continue

        if df.empty or cat not in models:
            continue

        m_data = models[cat]
        if 'features_list' in m_data:
            feats = m_data['features_list']
            # We must map df_f correctly based on features_list
            # But wait, in historical mode we might not have all features.
            # I will use the exact logic from market_filter.py for historical data
            pass
        else:
            feats = m_data['features']

        df_f = pd.DataFrame()
        for col in ['ixg', 'hdcf', 'sog', 'atoi']:
            df_f[f'{col}_l10'] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            df_f[col] = pd.to_numeric(df[col], errors='coerce').fillna(0) # Also raw
        for col in ['season_g', 'season_a', 'season_pts', 'ga_g', 'hdca_g', 'pk_pct', 'cf_pct', 'pdo']:
            if col in df.columns:
                df_f[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            else:
                df_f[col] = 0.0
        for col in ['pp1', 'is_home']:
            df_f[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
        df_f['is_b2b'] = pd.to_numeric(df['b2b'], errors='coerce').fillna(0).astype(int)
        df_f['opp_is_b2b'] = pd.to_numeric(df.get('opp_b2b', 0), errors='coerce').fillna(0).astype(int)
        df_f['consec_goals'] = pd.to_numeric(df.get('consec_goals', 0), errors='coerce').fillna(0)
        df_f['ixg_x_hdcf'] = df_f['ixg'] * df_f['hdcf']
        df_f['sog_x_atoi'] = df_f['sog'] * df_f['atoi']
        df_f['ixg_x_ga'] = df_f['ixg'] * df_f['ga_g']

        # Ensure all required features are present
        for f in feats:
            if f not in df_f.columns:
                df_f[f] = 0

        X = df_f[feats].values
        
        if 'scaler' in m_data:
            X = m_data['scaler'].transform(X)
            
        probas = m_data['model'].predict_proba(X)[:, 1]
        evs = (probas * df['cote'].values) - 1.0

        for i, (_, row) in enumerate(df.iterrows()):
            if evs[i] > 0.05:
                match_key = f"{row['equipe']}-{row['adversaire']}"
                all_picks.append({
                    'date': row['date'], 'joueur': row['joueur'], 'cat': cat,
                    'equipe': row['equipe'], 'adversaire': row['adversaire'],
                    'match': match_key,
                    'cote': float(row['cote']),
                    'won': float(pd.to_numeric(row['result'], errors='coerce') or 0) > 0,
                    'ev': float(evs[i]),
                })

    conn.close()
    return pd.DataFrame(all_picks)


def simulate_combos(df):
    """Simule toutes les familles de combinés possibles."""
    results = {}

    for date, day_group in df.groupby('date'):
        day = day_group.to_dict('records')
        buts = [p for p in day if p['cat'] == 'but']
        asts = [p for p in day if p['cat'] == 'ast']

        # Synergistic Buteur + Passeur (Même équipe, joueurs différents)
        for b in buts:
            for a in asts:
                if b['equipe'] == a['equipe'] and b['joueur'] != a['joueur']:
                    _add_combo(results, "SYNERGIE Buteur + Passeur", b, a)

        # Synergistic Passeur + Passeur (Même équipe)
        for a1, a2 in combinations(asts, 2):
            if a1['equipe'] == a2['equipe']:
                _add_combo(results, "SYNERGIE Passeur + Passeur", a1, a2)
                
        # Synergistic Buteur + Buteur (Même équipe)
        for b1, b2 in combinations(buts, 2):
            if b1['equipe'] == b2['equipe']:
                _add_combo(results, "SYNERGIE Buteur + Buteur", b1, b2)

    return results


def _add_combo(results, label, p1, p2):
    """Ajoute un combo au dictionnaire de résultats."""
    if label not in results:
        results[label] = []
    cote_tot = p1['cote'] * p2['cote']
    won = p1['won'] and p2['won']
    gain = (cote_tot - 1.0) if won else -1.0
    results[label].append({'cote': cote_tot, 'won': won, 'gain': gain})


def main():
    print("=" * 65)
    print(" ANALYSE EXHAUSTIVE DES COMBINES (Passeurs/Pointeurs)")
    print("=" * 65)

    df = load_ev_picks()
    print(f"-> {len(df)} picks EV+ charges (AST: {len(df[df['cat']=='ast'])}, PTS: {len(df[df['cat']=='pts'])})")

    combos = simulate_combos(df)

    # Affichage
    print(f"\n{'TYPE DE COMBINE'.ljust(45)} | {'VOL':>4} | {'WR':>6} | {'PROFIT':>9} | {'ROI':>7}")
    print("-" * 85)

    ranked = []
    for label, tickets in combos.items():
        vol = len(tickets)
        if vol < 5:
            continue
        wins = sum(1 for t in tickets if t['won'])
        wr = (wins / vol) * 100
        profit = sum(t['gain'] for t in tickets)
        roi = (profit / vol) * 100
        ranked.append((label, vol, wr, profit, roi))

    ranked.sort(key=lambda x: -x[4])  # Tri par ROI

    for label, vol, wr, profit, roi in ranked:
        indicator = "+++" if roi > 15 else "++" if roi > 5 else "+" if roi > 0 else "---"
        print(f" {indicator} {label.ljust(42)} | {vol:>4} | {wr:5.1f}% | {profit:+8.2f} U | {roi:+6.1f}%")

    print("\n" + "=" * 65)
    print(" VERDICT")
    print("=" * 65)

    best = ranked[0] if ranked else None
    worst = ranked[-1] if ranked else None

    if best:
        print(f" MEILLEUR COMBINE : {best[0]}")
        print(f"   -> ROI {best[4]:+.1f}% sur {best[1]} tickets (WR: {best[2]:.1f}%)")
    if worst:
        print(f" PIRE COMBINE    : {worst[0]}")
        print(f"   -> ROI {worst[4]:+.1f}% sur {worst[1]} tickets (WR: {worst[2]:.1f}%)")


if __name__ == "__main__":
    main()
