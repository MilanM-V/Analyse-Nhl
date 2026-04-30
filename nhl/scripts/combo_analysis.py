"""
Analyse exhaustive de toutes les combinaisons possibles de combinés:
- Duo Passeurs (intra-match et inter-match)
- Duo Pointeurs (intra-match et inter-match)
- Duo Mixte Passeur+Pointeur (intra-match et inter-match)
- Duo Mixte même joueur (Passeur ET Pointeur sur le même joueur)
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
    for cat in ['ast', 'pts']:
        path = os.path.join(MODELS_DIR, f'xg_model_{cat}.pkl')
        if os.path.exists(path):
            models[cat] = joblib.load(path)

    all_picks = []
    for table, cat, target_col in [("picks_assists", "ast", "assist"), ("picks_points", "pts", "point")]:
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
        feats = m_data['features']

        df_f = pd.DataFrame()
        for col in ['ixg', 'hdcf', 'sog', 'atoi']:
            df_f[f'{col}_l10'] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        for col in ['season_g', 'season_a', 'season_pts', 'ga_g', 'hdca_g']:
            df_f[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        for col in ['pp1', 'is_home']:
            df_f[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
        df_f['is_b2b'] = pd.to_numeric(df['b2b'], errors='coerce').fillna(0).astype(int)
        df_f['opp_is_b2b'] = pd.to_numeric(df.get('opp_b2b', 0), errors='coerce').fillna(0).astype(int)
        df_f['consec_goals'] = pd.to_numeric(df.get('consec_goals', 0), errors='coerce').fillna(0)
        df_f['ixg_x_hdcf'] = df_f['ixg_l10'] * df_f['hdcf_l10']
        df_f['sog_x_atoi'] = df_f['sog_l10'] * df_f['atoi_l10']
        df_f['ixg_x_ga'] = df_f['ixg_l10'] * df_f['ga_g']

        X = df_f[feats].values
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
        asts = [p for p in day if p['cat'] == 'ast']
        pts = [p for p in day if p['cat'] == 'pts']

        # --- INTRA-MATCH ---
        # Passeur + Pointeur MEME match (non contradictoire)
        for a in asts:
            for p in pts:
                if a['match'] == p['match'] and a['joueur'] != p['joueur']:
                    _add_combo(results, "INTRA Passeur+Pointeur (meme match)", a, p)

        # Passeur + Pointeur MEME JOUEUR (le joueur fait une passe OU un point - ce sont 2 paris séparés)
        for a in asts:
            for p in pts:
                if a['joueur'] == p['joueur']:
                    _add_combo(results, "MEME JOUEUR (Passe+Point)", a, p)

        # --- INTER-MATCH ---
        # Passeur + Passeur matchs différents
        for a1, a2 in combinations(asts, 2):
            if a1['match'] != a2['match']:
                _add_combo(results, "INTER Passeur+Passeur (matchs diff)", a1, a2)

        # Pointeur + Pointeur matchs différents
        for p1, p2 in combinations(pts, 2):
            if p1['match'] != p2['match']:
                _add_combo(results, "INTER Pointeur+Pointeur (matchs diff)", p1, p2)

        # Passeur + Pointeur matchs différents
        for a in asts:
            for p in pts:
                if a['match'] != p['match']:
                    _add_combo(results, "INTER Passeur+Pointeur (matchs diff)", a, p)

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
