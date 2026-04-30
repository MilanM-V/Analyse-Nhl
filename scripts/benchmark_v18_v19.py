"""
Simulateur comparatif V18.3 vs Poisson V19
Utilise la MEME logique que dashboard.py :
  - Si cote en DB -> cote réelle
  - Sinon -> cote par défaut (3.20 But / 2.40 Pass / 1.90 Pts)
Tourne sur TOUTES les 3117 lignes de la table players.
"""
import sqlite3
import math
import sys

DB_PATH = r"c:\Users\2507m\Desktop\Milan\code\bet2\bot_database.db"
sys.path.insert(0, r"c:\Users\2507m\Desktop\Milan\code\bet2")
from config.settings import cfg
from core.market_filter import evaluate_player_markets

conn = sqlite3.connect(DB_PATH, timeout=10)
conn.row_factory = sqlite3.Row
players_raw = conn.execute("SELECT * FROM players ORDER BY date").fetchall()

def load_cotes(table):
    rows = conn.execute(f"SELECT date, joueur, cote FROM {table} WHERE cote IS NOT NULL").fetchall()
    return {(r["date"], r["joueur"]): float(r["cote"]) for r in rows}

cotes_but = load_cotes("picks")
cotes_ast = load_cotes("picks_assists")
cotes_pts = load_cotes("picks_points")

print(f"Donnees: {len(players_raw)} lignes joueurs")

players = [dict(r) for r in players_raw]

# ─── Probas statiques (probas.json actuel) ────────────────────────────────────
PROBAS_STATIQUES = {"buteurs": 0.2229, "passeurs": 0.4646, "pointeurs": 0.5884}
KELLY_CAPS       = {"BUTEUR": 3.0, "PASSEUR": 2.0, "POINTEUR": 2.0}
# Cotes par défaut (même que dashboard.py ligne 141-149)
COTE_DEF = {"BUTEUR": 3.20, "PASSEUR": 2.40, "POINTEUR": 1.90}
# Cotes mini (même que settings.toml)
COTE_MIN = {
    "buteurs":  getattr(cfg.thresholds.buteurs,   "cote_min", 3.00),
    "passeurs": getattr(cfg.thresholds.passeurs,  "cote_min", 2.20),
    "pointeurs":getattr(cfg.thresholds.pointeurs, "cote_min", 0.0),
}

LIGUE_AVG_GA = 3.10

def apply_kelly(prob, cote, cat):
    if not cote or cote <= 1.05: return 0.0
    b = cote - 1.0
    q = 1.0 - prob
    f = (prob * b - q) / b
    if f <= 0: return 0.0
    units = round((f / 4.0) * 100 * 2) / 2
    return max(0.5, min(units, KELLY_CAPS.get(cat, 2.0)))

def get_cote(cote_dict, key, cat_name):
    """Même logique que dashboard : cote réelle sinon cote par défaut."""
    c = cote_dict.get(key)
    return float(c) if c else COTE_DEF[cat_name]

results_v18 = []
results_v19  = []

thr_b = cfg.thresholds.buteurs
thr_a = cfg.thresholds.passeurs
thr_p = cfg.thresholds.pointeurs

for row in players:
    date      = row.get("date", "")
    joueur    = row.get("joueur", "")
    is_home   = bool(row.get("is_home", 1))
    equipe    = row.get("equipe", "")
    adv       = row.get("adversaire", "")
    res_but   = (row.get("but") or 0) > 0
    res_ast   = (row.get("assist") or 0) > 0
    res_pts   = (row.get("point") or 0) > 0

    season_g   = float(row.get("season_g") or 0)
    season_a   = float(row.get("season_a") or 0)
    season_pts = float(row.get("season_pts") or 0)
    opp_ga     = float(row.get("ga_g") or LIGUE_AVG_GA)
    atoi       = float(row.get("atoi") or 0)
    l10_sog    = float(row.get("sog") or 0)
    l10_hdcf   = float(row.get("hdcf") or 0)
    l10_a      = float(row.get("l10_a") or 0)
    l10_pts    = float(row.get("l10_pts") or 0)

    key = (date, joueur)

    # ────────────────────────────────────────────────────────────────────────
    # V18.3 : evaluate_player_markets (EXACTEMENT comme dashboard.py)
    # ────────────────────────────────────────────────────────────────────────
    p_form   = {"L10_SOG_G": l10_sog, "L10_iHDCF_G": l10_hdcf,
                "L10_A_G": l10_a, "L10_Pts_G": l10_pts, "ATOI": atoi}
    v5_p     = {"G_GP": season_g, "A_GP": season_a,
                "Pts_GP": season_pts, "Position": "F"}
    adv_stat = {"GA_G": opp_ga}

    cat_but, cat_ast, cat_pts = evaluate_player_markets(joueur, p_form, v5_p, adv_stat, is_home)

    def sim_v18(cat_name, prob_key, cat_flag, cote_dict, res_won):
        if not cat_flag: return
        cote = get_cote(cote_dict, key, cat_name)
        cote_mini = COTE_MIN[prob_key]
        if cote < cote_mini: return
        prob = PROBAS_STATIQUES[prob_key]
        if prob * cote - 1.0 <= 0: return
        mise = apply_kelly(prob, cote, cat_name)
        if mise <= 0: return
        gain = (cote * mise - mise) if res_won else -mise
        results_v18.append({"gain": gain, "mise": mise, "won": res_won})

    sim_v18("BUTEUR",   "buteurs",   cat_but, cotes_but, res_but)
    sim_v18("PASSEUR",  "passeurs",  cat_ast, cotes_ast, res_ast)
    sim_v18("POINTEUR", "pointeurs", cat_pts, cotes_pts, res_pts)

    # ────────────────────────────────────────────────────────────────────────
    # V19 : Poisson dynamique par joueur (même cotes que V18 – fair comparison)
    # ────────────────────────────────────────────────────────────────────────
    opp_factor = opp_ga / LIGUE_AVG_GA

    def sim_v19(cat_name, lmbda_raw, home_mult, away_mult, cote_dict, res_won, atoi_min=0):
        if atoi < atoi_min: return
        cote  = get_cote(cote_dict, key, cat_name)
        lmbda = lmbda_raw * opp_factor * (home_mult if is_home else away_mult)
        prob  = 1.0 - math.exp(-lmbda)
        edge  = prob * cote - 1.0
        if edge <= 0.02: return
        mise = apply_kelly(prob, cote, cat_name)
        if mise <= 0: return
        gain = (cote * mise - mise) if res_won else -mise
        results_v19.append({"gain": gain, "mise": mise, "won": res_won})

    # Buteur : filtre qualitatif minimal conservé (sog + hdcf)
    if l10_sog >= 2.0 and l10_hdcf >= 1.5 and season_g > 0:
        sim_v19("BUTEUR", season_g, 1.10, 0.95, cotes_but, res_but)

    # Passeur
    if season_a > 0:
        sim_v19("PASSEUR", season_a, 1.06, 0.96, cotes_ast, res_ast, atoi_min=14.0)

    # Pointeur
    if season_pts > 0:
        sim_v19("POINTEUR", season_pts, 1.08, 0.95, cotes_pts, res_pts, atoi_min=14.0)


# ─── Affichage ───────────────────────────────────────────────────────────────
def show(results, label):
    if not results:
        print(f"\n{label}: Aucun pari")
        return
    p = sum(r["gain"] for r in results)
    m = sum(r["mise"] for r in results)
    n = len(results)
    w = sum(1 for r in results if r["won"])
    roi = p / m * 100 if m else 0
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Picks          : {n}")
    print(f"  Winrate        : {w/n*100:.1f}%")
    print(f"  Mise Totale    : {m:.1f} U  ({m:.0f} EUR)")
    print(f"  Profit Net     : {p:+.2f} U  ({p:+.2f} EUR)")
    print(f"  ROI            : {roi:+.1f}%")

show(results_v18, "V18.3 — Thresholds + Probas Statiques (dashboard logic)")
show(results_v19,  "V19   — Poisson Dynamique par Joueur  (memes cotes)")
print()
