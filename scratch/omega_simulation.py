"""
OMEGA ANALYSIS V3 — v19.7 vs v19.16 (CORRECT)
Meme architecture core/, configs differentes.
"""
import sqlite3, json, math, os, sys

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot_database.db")
OUTPUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "omega_results.json")

# ================================================================
# CONFIGS EXACTES extraites de git show
# ================================================================

CFG_V197 = {
    'buteurs': {'season_g_min': 0.40, 'l10_sog_min': 3.0, 'l10_hdcf_min': 2.5,
                'home_only': True, 'opp_ga_min': 2.8, 'cote_min': 3.00},
    'passeurs': {'season_a_min': 0.50, 'l10_a_min': 0.80, 'home_only': True,
                 'atoi_min': 18.0, 'opp_ga_min': 2.8, 'cote_min': 2.20},
    'pointeurs': {'season_pts_min': 0.90, 'l10_pts_min': 0.80, 'home_only': True,
                  'atoi_min': 16.0, 'opp_ga_min': 2.8, 'cote_min': 0.0},
    'kelly': {'buteur_cap': 3.0, 'passeur_cap': 2.0, 'pointeur_cap': 2.0},
    'kelly_fraction': 0.25,  # Quarter Kelly (f/4)
    'probas': {'buteurs': 0.35, 'passeurs': 0.50, 'pointeurs': 0.65},
    'tactical': None,  # Pas de bonus tactiques en v19.7
    'away_penalty': False,
}

CFG_V1916 = {
    'buteurs': {'season_g_min': 0.50, 'l10_sog_min': 3.0, 'l10_hdcf_min': 2.5,
                'home_only': True, 'opp_ga_min': 2.8, 'cote_min': 0.0},
    'passeurs': {'season_a_min': 0.35, 'l10_a_min': 0.30, 'home_only': False,
                 'atoi_min': 16.0, 'opp_ga_min': 2.8, 'cote_min': 0.0},
    'pointeurs': {'season_pts_min': 0.55, 'l10_pts_min': 0.30, 'home_only': False,
                  'atoi_min': 15.0, 'opp_ga_min': 2.8, 'cote_min': 0.0},
    'kelly': {'buteur_cap': 0.0, 'passeur_cap': 4.0, 'pointeur_cap': 5.0},
    'kelly_fraction': 1.0,  # Full Kelly
    'probas': {'buteurs': 0.35, 'passeurs': 0.41, 'pointeurs': 0.57},
    'tactical': {'pp1_bonus': 0.05, 'opp_b2b_bonus': 0.05},
    'away_penalty': True,  # +0.10 sur season_a_min et season_pts_min si away
}

# ================================================================
# DATA
# ================================================================

def load_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    players = conn.execute("""
        SELECT * FROM players 
        WHERE but IS NOT NULL AND but != ''
        AND l10_a IS NOT NULL AND season_a IS NOT NULL
    """).fetchall()
    
    cotes = {}
    for table, cat in [('picks','buteur'),('picks_assists','passeur'),('picks_points','pointeur')]:
        cotes[cat] = {}
        for r in conn.execute(f"SELECT date, joueur, cote FROM {table} WHERE cote IS NOT NULL AND cote > 0"):
            cotes[cat][(r['date'], r['joueur'])] = r['cote']
    
    avg_cotes = {}
    for table, cat in [('picks','buteur'),('picks_assists','passeur'),('picks_points','pointeur')]:
        row = conn.execute(f"SELECT AVG(cote) FROM {table} WHERE cote IS NOT NULL AND cote > 0").fetchone()
        avg_cotes[cat] = round(row[0], 2) if row[0] else 2.50
    conn.close()
    
    # Dedup
    seen = set(); unique = []
    for p in players:
        k = (p['date'], p['joueur'])
        if k not in seen: seen.add(k); unique.append(p)
    
    print(f"[DATA] {len(unique)} joueurs uniques / {len(players)} total")
    print(f"[DATA] Cotes moyennes: BUT={avg_cotes['buteur']}, AST={avg_cotes['passeur']}, PTS={avg_cotes['pointeur']}")
    return unique, cotes, avg_cotes

# ================================================================
# MOTEUR GENERIQUE (parametre par config)
# ================================================================

def evaluate(row, cfg):
    """Evalue un joueur avec les seuils d'une config donnee."""
    season_g = float(row['season_g'] or 0)
    sog = float(row['sog'] or 0)
    hdcf = float(row['hdcf'] or 0)
    season_a = float(row['season_a'] or 0)
    season_pts = float(row['season_pts'] or 0)
    l10_a = float(row['l10_a'] or 0)
    l10_pts = float(row['l10_pts'] or 0)
    atoi = float(row['atoi'] or 0)
    ga_g = float(row['ga_g'] or 0)
    is_home = bool(row['is_home'])
    is_pp1 = bool(row['pp1'])
    opp_b2b = bool(row['opp_b2b'])
    
    # Bonus tactiques (v19.16 only)
    bonus = 0.0
    if cfg['tactical']:
        if is_pp1: bonus += cfg['tactical']['pp1_bonus']
        if opp_b2b: bonus += cfg['tactical']['opp_b2b_bonus']
    
    # Away penalty (v19.16: +0.10 sur season thresholds si away)
    away_pen = 0.10 if (cfg['away_penalty'] and not is_home) else 0.0
    
    # Mode playoff -> ignore home_only
    is_playoff = True  # On est en mode playoff dans la DB
    
    # BUTEUR
    t = cfg['buteurs']
    cat_but = None
    if (is_home or is_playoff or not t['home_only']) and \
       season_g >= (t['season_g_min'] - bonus) and \
       sog >= t['l10_sog_min'] and hdcf >= t['l10_hdcf_min'] and ga_g >= t['opp_ga_min']:
        cat_but = "BUTEUR"
    
    # PASSEUR
    t = cfg['passeurs']
    cat_ast = None
    if (is_home or is_playoff or not t['home_only']) and \
       season_a >= (t['season_a_min'] + away_pen - bonus) and \
       l10_a >= t['l10_a_min'] and atoi >= t['atoi_min'] and ga_g >= t['opp_ga_min']:
        cat_ast = "PASSEUR"
    
    # POINTEUR
    t = cfg['pointeurs']
    cat_pts = None
    if (is_home or is_playoff or not t['home_only']) and \
       season_pts >= (t['season_pts_min'] + away_pen - bonus) and \
       l10_pts >= t['l10_pts_min'] and atoi >= t['atoi_min'] and ga_g >= t['opp_ga_min']:
        cat_pts = "POINTEUR"
    
    return cat_but, cat_ast, cat_pts


def kelly(proba, cote, cat, cfg):
    """Calcul Kelly parametre par la config."""
    if not cote or cote <= 1.05: return 0.0
    b = cote - 1.0
    f = (proba * b - (1 - proba)) / b
    cap = cfg['kelly'].get(f"{cat.lower()}_cap", 2.0)
    if f > 0 and cap > 0:
        sized_f = f * cfg['kelly_fraction']
        units = round(sized_f * 100 * 2) / 2
        return max(0.5, min(units, cap))
    return 0.0


def simulate(players, cotes, avg_cotes, cfg, label):
    """Simulation complete avec une config donnee."""
    results = []
    
    for p in players:
        cat_but, cat_ast, cat_pts = evaluate(p, cfg)
        key = (p['date'], p['joueur'])
        
        for cat, cdict, pkey, rcol, defcote in [
            (cat_but, cotes['buteur'], 'buteurs', 'but', avg_cotes['buteur']),
            (cat_ast, cotes['passeur'], 'passeurs', 'assist', avg_cotes['passeur']),
            (cat_pts, cotes['pointeur'], 'pointeurs', 'point', avg_cotes['pointeur']),
        ]:
            if not cat: continue
            cote = cdict.get(key, defcote)
            
            # Filtre cote minimum (V19.7 a des cote_min strictes)
            cote_min_cfg = cfg[pkey.rstrip('s') + 's' if not pkey.endswith('s') else pkey]
            # On accede au bon champ
            if pkey == 'buteurs': cote_min = cfg['buteurs']['cote_min']
            elif pkey == 'passeurs': cote_min = cfg['passeurs']['cote_min']
            else: cote_min = cfg['pointeurs']['cote_min']
            
            if cote_min > 0 and cote < cote_min:
                continue
            
            proba = cfg['probas'][pkey]
            edge = (proba * cote) - 1.0
            if edge <= 0: continue
            
            mise = kelly(proba, cote, cat, cfg)
            if mise <= 0: continue
            
            won = int(p[rcol] or 0) > 0
            has_real_odds = key in cdict
            gain = (cote * mise - mise) if won else -mise
            
            results.append({
                'date': p['date'], 'joueur': p['joueur'], 'equipe': p['equipe'],
                'adversaire': p['adversaire'], 'categorie': cat,
                'cote': round(cote, 2), 'mise': mise, 'gain': round(gain, 2),
                'won': won, 'edge': round(edge*100, 1),
                'game_mode': p['game_mode'] or 'regular',
                'has_real_odds': has_real_odds
            })
    
    # Combines DUO
    by_date = {}
    for r in results: by_date.setdefault(r['date'], []).append(r)
    parlays = []
    for d, dp in by_date.items():
        pts = sorted([x for x in dp if x['categorie']=='POINTEUR'], key=lambda x: -x['edge'])
        diverse = []; seen = set()
        for x in pts:
            mid = f"{x['equipe']}-{x['adversaire']}"
            if mid not in seen: diverse.append(x); seen.add(mid)
        if len(diverse) >= 2:
            p1, p2 = diverse[0], diverse[1]
            c_tot = p1['cote'] * p2['cote']
            won = p1['won'] and p2['won']
            gain = (c_tot - 1.0) if won else -1.0
            parlays.append({
                'date': d, 'joueur': f"DUO: {p1['joueur']} + {p2['joueur']}",
                'equipe': '-', 'adversaire': f"{p1['adversaire']} & {p2['adversaire']}",
                'categorie': 'COMBINE', 'cote': round(c_tot, 2), 'mise': 1.0,
                'gain': round(gain, 2), 'won': won, 'edge': 0,
                'game_mode': 'combined', 'has_real_odds': False
            })
    results.extend(parlays)
    return results


def metrics(results, label):
    if not results:
        return {'label': label, 'total_picks': 0, 'profit_u': 0, 'roi_pct': 0,
                'winrate': 0, 'categories': {}, 'daily': {}, 'mode_split': {},
                'num_days': 0, 'total_mise': 0, 'total_won': 0, 'avg_cote': 0,
                'max_drawdown': 0, 'real_odds_pct': 0}
    
    tp = len(results); tw = sum(1 for r in results if r['won'])
    tm = sum(r['mise'] for r in results); tg = sum(r['gain'] for r in results)
    wr = (tw/tp)*100; roi = (tg/tm)*100 if tm else 0
    real_pct = sum(1 for r in results if r.get('has_real_odds')) / tp * 100
    
    cats = {}
    for r in results:
        c = r['categorie']
        cats.setdefault(c, {'picks':0,'won':0,'mise':0,'gain':0,'cotes':[]})
        cats[c]['picks'] += 1
        if r['won']: cats[c]['won'] += 1
        cats[c]['mise'] += r['mise']; cats[c]['gain'] += r['gain']; cats[c]['cotes'].append(r['cote'])
    cat_m = {}
    for c, d in cats.items():
        cat_m[c] = {'picks':d['picks'], 'won':d['won'],
                     'winrate':round((d['won']/d['picks'])*100,1) if d['picks'] else 0,
                     'mise':round(d['mise'],1), 'gain':round(d['gain'],1),
                     'roi':round((d['gain']/d['mise'])*100,1) if d['mise'] else 0,
                     'avg_cote':round(sum(d['cotes'])/len(d['cotes']),2)}
    
    daily = {}
    for r in results:
        daily.setdefault(r['date'], {'picks':0,'won':0,'mise':0,'gain':0})
        daily[r['date']]['picks'] += 1
        if r['won']: daily[r['date']]['won'] += 1
        daily[r['date']]['mise'] += r['mise']; daily[r['date']]['gain'] += r['gain']
    dm = {}; cumul = 0; peak = 0; max_dd = 0
    for d in sorted(daily.keys()):
        cumul += daily[d]['gain']
        peak = max(peak, cumul)
        max_dd = max(max_dd, peak - cumul)
        dm[d] = {'picks':daily[d]['picks'],'won':daily[d]['won'],
                 'mise':round(daily[d]['mise'],1),
                 'gain':round(daily[d]['gain'],1),'cumul':round(cumul,1)}
    
    modes = {}
    for r in results:
        m = r.get('game_mode','regular')
        modes.setdefault(m, {'picks':0,'won':0,'mise':0,'gain':0})
        modes[m]['picks'] += 1
        if r['won']: modes[m]['won'] += 1
        modes[m]['mise'] += r['mise']; modes[m]['gain'] += r['gain']
    for m in modes:
        d = modes[m]
        d['roi'] = round((d['gain']/d['mise'])*100,1) if d['mise'] else 0
        d['winrate'] = round((d['won']/d['picks'])*100,1) if d['picks'] else 0
        d['gain'] = round(d['gain'],1); d['mise'] = round(d['mise'],1)
    
    return {'label':label,'total_picks':tp,'total_won':tw,'total_mise':round(tm,1),
            'profit_u':round(tg,1),'roi_pct':round(roi,1),'winrate':round(wr,1),
            'avg_cote':round(sum(r['cote'] for r in results)/len(results),2),
            'max_drawdown':round(max_dd,1),'categories':cat_m,'daily':dm,
            'mode_split':modes,'num_days':len(daily),'real_odds_pct':round(real_pct,1)}


if __name__ == "__main__":
    print("=" * 70)
    print("  OMEGA ANALYSIS V3 - v19.7 vs v19.16")
    print("=" * 70)
    
    players, cotes, avg_cotes = load_data()
    
    print("\n[SIM] v19.7 (Quarter Kelly, seuils stricts, home_only, cote_min)...")
    r197 = simulate(players, cotes, avg_cotes, CFG_V197, "v19.7")
    m197 = metrics(r197, "v19.7")
    print(f"  {m197['total_picks']} picks | {m197['profit_u']:+.1f} U | ROI {m197['roi_pct']:+.1f}% | WR {m197['winrate']:.1f}% | Odds reelles: {m197['real_odds_pct']:.0f}%")
    
    print("\n[SIM] v19.16 (Full Kelly, seuils ouverts, away ok, tactique)...")
    r1916 = simulate(players, cotes, avg_cotes, CFG_V1916, "v19.16")
    m1916 = metrics(r1916, "v19.16")
    print(f"  {m1916['total_picks']} picks | {m1916['profit_u']:+.1f} U | ROI {m1916['roi_pct']:+.1f}% | WR {m1916['winrate']:.1f}% | Odds reelles: {m1916['real_odds_pct']:.0f}%")
    
    output = {
        'v197': m197, 'v1916': m1916,
        'v197_results': r197, 'v1916_results': r1916,
        'avg_cotes': avg_cotes,
        'period': {'start': min(p['date'] for p in players), 'end': max(p['date'] for p in players), 'total_eval': len(players)},
        'config_diff': {
            'v197': CFG_V197, 'v1916': CFG_V1916
        }
    }
    
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    
    diff = m1916['profit_u'] - m197['profit_u']
    winner = "v19.16" if diff > 0 else "v19.7"
    print(f"\n{'='*70}")
    print(f"  VERDICT: {winner} gagne ({diff:+.1f} U de difference)")
    print(f"{'='*70}")
    
    # Detail categories
    print("\n--- v19.7 Categories ---")
    for c, m in m197['categories'].items():
        print(f"  {c}: {m['picks']} picks, WR {m['winrate']}%, {m['gain']:+.1f} U, ROI {m['roi']:+.1f}%, cote moy {m['avg_cote']}")
    print("\n--- v19.16 Categories ---")
    for c, m in m1916['categories'].items():
        print(f"  {c}: {m['picks']} picks, WR {m['winrate']}%, {m['gain']:+.1f} U, ROI {m['roi']:+.1f}%, cote moy {m['avg_cote']}")
