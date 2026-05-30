import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import plotly.graph_objects as go
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from nhl.config.settings import cfg
from nhl.core.market_filter import evaluate_player_markets, load_dynamic_probas
from nhl.core.kelly import calculate_quarter_kelly, CATEGORY_CAPS

# Compatibilité r/w TOML
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

st.set_page_config(
    page_title="NHL Quant Simulator | V18",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom minimal dark theme
st.markdown("""
<style>
    .reportview-container { background: #0E1117; }
    .metric-container {
        border-radius: 10px; background-color: #1E202B;
        padding: 20px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3); text-align: center;
    }
    .metric-label { color: #94A3B8; font-size: 0.9rem; margin-bottom: 5px; }
    .metric-value { color: #F8FAFC; font-size: 1.8rem; font-weight: bold; }
    .metric-value.green { color: #4ADE80; }
    .metric-value.red { color: #F87171; }
</style>
""", unsafe_allow_html=True)

DB_PATH = "bot_database.db"
SETTINGS_PATH = "config/settings.toml"
PROBAS_PATH = "config/probas.json"

@st.cache_data(ttl=60)
def load_and_simulate(unit_value_euro: float, mode_filter: str = "all"):
    if not os.path.exists(DB_PATH) or not os.path.exists(SETTINGS_PATH):
        return pd.DataFrame(), {}

    # La config est chargée globalement via 'from nhl.config.settings import cfg'
    # 'probas' est chargé dynamiquement via import. On peut s'en passer ici.

    # Connexion DB : On charge TOUS les joueurs évalués
    conn = sqlite3.connect(DB_PATH)
    # On limite aux joueurs ayant un resultat connu
    query = "SELECT * FROM players WHERE but IS NOT NULL AND but != ''"
    if mode_filter in ("regular", "playoff"):
        query += f" AND game_mode = '{mode_filter}'"
    df = pd.read_sql_query(query, conn)
    
    # On charge également les cotes réelles mémorisées dans les tables picks pour interpoler
    cotes_df_but = pd.read_sql_query("SELECT date, joueur, cote FROM picks WHERE cote IS NOT NULL", conn)
    cotes_df_ast = pd.read_sql_query("SELECT date, joueur, cote FROM picks_assists WHERE cote IS NOT NULL", conn)
    cotes_df_pts = pd.read_sql_query("SELECT date, joueur, cote FROM picks_points WHERE cote IS NOT NULL", conn)
    conn.close()

    if df.empty:
        return pd.DataFrame(), {}

    df['date'] = pd.to_datetime(df['date'])
    
    # Mapping des cotes pour les jointures (date + joueur)
    # cotes_but_dict = cotes_df_but.set_index(['date', 'joueur'])['cote'].to_dict()
    cotes_ast_dict = cotes_df_ast.set_index(['date', 'joueur'])['cote'].to_dict()
    cotes_pts_dict = cotes_df_pts.set_index(['date', 'joueur'])['cote'].to_dict()

    # Calcul des cotes par défaut dynamiques (Moyenne historique réelle)
    avg_but = float(cotes_df_but['cote'].mean()) if not cotes_df_but.empty else 3.20
    avg_ast = float(cotes_df_ast['cote'].mean()) if not cotes_df_ast.empty else 2.40
    avg_pts = float(cotes_df_pts['cote'].mean()) if not cotes_df_pts.empty else 1.90
    avg_but = round(avg_but, 2)
    avg_ast = round(avg_ast, 2)
    avg_pts = round(avg_pts, 2)

    results = []
    
    probas = load_dynamic_probas()

    # Moteur V18 manuel (Backtesting)
    for idx, row in df.iterrows():
        p_date = row['date'].strftime("%Y-%m-%d")
        joueur = row['joueur']
        key = (p_date, joueur)
        
        # Stats
        hdcf = float(row['hdcf']) if pd.notna(row['hdcf']) else 0

        atoi = float(row['atoi']) if pd.notna(row['atoi']) else 0
        opp_ga = float(row['ga_g']) if pd.notna(row['ga_g']) else 0
        season_g = float(row['season_g']) if pd.notna(row['season_g']) else 0
        season_a = float(row['season_a']) if pd.notna(row['season_a']) else 0
        season_pts = float(row['season_pts']) if pd.notna(row['season_pts']) else 0
        is_home = bool(row['is_home'])
        
        # Logs de Resultats réels
        # res_but = int(row['but']) > 0
        res_ast = int(row['assist']) > 0
        res_pts = int(row['point']) > 0

        p_form = {
            "L10_SOG_G": row.get('sog', 0) if pd.notna(row.get('sog', 0)) else 0,
            "L10_iHDCF_G": hdcf,
            "L10_A_G": row.get('l10_a', 0) if pd.notna(row.get('l10_a', 0)) else 0,
            "L10_Pts_G": row.get('l10_pts', 0) if pd.notna(row.get('l10_pts', 0)) else 0,
            "ATOI": atoi
        }
        v5_p = {
            "G_GP": season_g,
            "A_GP": season_a,
            "Pts_GP": season_pts,
            "Position": "F"  # Position is usually not fully available in player hist, assuming F
        }
        adv_stats = {"GA_G": opp_ga}
        
        cat_but, cat_ast, cat_pts = evaluate_player_markets(joueur, p_form, v5_p, adv_stats, is_home)

        # Helper pour générer un résultat
        def add_result(cat_name, cote_dict, cf_min, prob_key, res_won):
            cote_reel_scrap = cote_dict.get(key)
            
            # Filtrage Strict (Option 1) : On ignore si pas de vraie cote
            if not cote_reel_scrap:
                return
                
            cote = cote_reel_scrap
            
            thresh_group = getattr(cfg.thresholds, prob_key, None)
            cote_mini = getattr(thresh_group, "cote_min", cf_min) if thresh_group else cf_min
            
            if cote >= cote_mini:
                prob = probas.get(prob_key, 0.30)
                edge = (prob * cote) - 1.0
                if edge > 0.05: # Strict EV > 5%
                    mise_str = calculate_quarter_kelly(prob, cote, cat_name)
                    mise = float(mise_str.replace(" U", "")) if mise_str != "0 U" else 0.0
                    if mise > 0:
                        gain_u = (cote * mise - mise) if res_won else -mise
                        results.append({"date": row['date'], "joueur": joueur, "categorie": cat_name,
                                       "cote": cote, "mise_u": mise, "edge_pct": edge*100, 
                                       "gain_u": gain_u, "gain_euro": gain_u * unit_value_euro,
                                       "won": res_won, "equipe": row['equipe'], "adv": row['adversaire']})

        # Buteur (DESACTIVE CAR ROI NEGATIF)
        # if cat_but:
        #     add_result("BUTEUR", cotes_but_dict, 2.50, "buteurs", res_but)
            
        # Passeur
        if cat_ast:
            add_result("PASSEUR", cotes_ast_dict, 2.00, "passeurs", res_ast)
            
        # Pointeur
        if cat_pts:
            add_result("POINTEUR", cotes_pts_dict, 1.50, "pointeurs", res_pts)

    # ----- SIMULATION DES COMBINÉS V18.3 -----
    def get_best_per_match(picks_list):
        best = {}
        for p in picks_list:
            m_key = f"{p['equipe']}-{p['adv']}"
            if m_key not in best or (p['edge_pct']) > (best[m_key]['edge_pct']):
                best[m_key] = p
        return list(best.values())
        
    def find_cross_duo(list1, list2):
        for p1 in list1:
            g1 = set([p1['equipe'], p1['adv']])
            for p2 in list2:
                if p1['joueur'] == p2['joueur']: continue
                g2 = set([p2['equipe'], p2['adv']])
                if not g1.intersection(g2):
                    return (p1, p2)
        return None

    # Group by date
    by_date = {}
    for r in results:
        d = r['date']
        if d not in by_date: by_date[d] = []
        by_date[d].append(r)
        
    parlay_results = []
    
    for d, day_picks in by_date.items():
        buts = [p for p in day_picks if p['categorie'] == "BUTEUR"]
        asts = [p for p in day_picks if p['categorie'] == "PASSEUR"]
        pts = [p for p in day_picks if p['categorie'] == "POINTEUR"]
        
        best_pts = get_best_per_match(pts)
        best_ast = get_best_per_match(asts)
        best_but = get_best_per_match(buts)
        
        best_pts.sort(key=lambda x: -x['edge_pct'])
        best_ast.sort(key=lambda x: -x['edge_pct'])
        best_but.sort(key=lambda x: -x['edge_pct'])
        
        def add_combo(p1, p2, cat_name, mise_u):
            c_tot = p1['cote'] * p2['cote']
            won = p1['won'] and p2['won']
            gain_u = (c_tot * mise_u - mise_u) if won else -mise_u
            parlay_results.append({
                "date": d, "joueur": f"{p1['joueur']} + {p2['joueur']}", 
                "categorie": cat_name, "cote": c_tot, "mise_u": mise_u, "edge_pct": 0,
                "gain_u": gain_u, "gain_euro": gain_u * unit_value_euro,
                "won": won, "equipe": "COMBO", "adv": "COMBO"
            })
            
        # 1. INTRA-MATCH : Passeur + Pointeur même match (ROI +50%)
        for a in asts:
            for p in pts:
                if a['joueur'] != p['joueur'] and f"{a['equipe']}-{a['adv']}" == f"{p['equipe']}-{p['adv']}":
                    add_combo(a, p, "COMBO INTRA Passeur+Pointeur", 0.5)
                    break
            else:
                continue
            break
            
        # 2. INTER-MATCH : Passeur + Passeur matchs différents (ROI +23%)
        dast = find_cross_duo(best_ast, best_ast)
        if dast: add_combo(dast[0], dast[1], "COMBO INTER Double Passeurs", 0.5)
            
        # 3. INTER-MATCH : Passeur + Pointeur matchs différents (ROI +13%)
        booster = find_cross_duo(best_ast, best_pts)
        if booster: add_combo(booster[0], booster[1], "COMBO INTER Passeur+Pointeur", 0.5)
        
    results.extend(parlay_results)

    sim_df = pd.DataFrame(results)
    if not sim_df.empty:
        sim_df = sim_df.sort_values('date')
        sim_df['cumul_u'] = sim_df['gain_u'].cumsum()
        sim_df['cumul_euro'] = sim_df['gain_euro'].cumsum()

    return sim_df, probas

# ----- INTERFACE -----
st.sidebar.image("https://upload.wikimedia.org/wikipedia/en/thumb/3/3a/05_NHL_Shield.svg/1200px-05_NHL_Shield.svg.png", width=80)
st.sidebar.title("Simulateur Quant OMEGA")

unit_euro = st.sidebar.number_input("💵 Valeur d'1 Unité (en €)", min_value=0.1, max_value=500.0, value=10.0, step=5.0)

st.sidebar.markdown("---")
mode_options = {"Tous": "all", "Saison Régulière": "regular", "Playoff": "playoff"}
mode_choice = st.sidebar.radio("🏒 Mode NHL", list(mode_options.keys()), index=0, horizontal=True)
selected_mode = mode_options[mode_choice]
st.sidebar.info("📌 Ce dashboard simule le **Moteur V4** (Passeurs & Pointeurs uniquement, EV > 5%, cotes réelles)")

mode_label = f" ({mode_choice})" if selected_mode != "all" else ""
st.title(f"📊 Dashboard Simulateur V4{mode_label}")
st.markdown(f"Simulation honnête sur cotes réelles uniquement (Passeurs + Pointeurs + Combinés prouvés), avec **1 Unité = {unit_euro} €** :")

df_sim, probas_actuelles = load_and_simulate(unit_euro, selected_mode)

if df_sim.empty:
    st.warning("Aucune donnée de simulation générée. La BDD est peut-être vide.")
    st.stop()

# KPIs
total_picks = len(df_sim)
win_picks = len(df_sim[df_sim['gain_u'] > 0])
winrate = (win_picks / total_picks) * 100
total_u = df_sim['gain_u'].sum()
total_euro = df_sim['gain_euro'].sum()
roi = (total_u / df_sim['mise_u'].sum()) * 100

c1, c2, c3 = st.columns(3)
with c1:
    c_color = "green" if total_euro >= 0 else "red"
    st.markdown(f'<div class="metric-container"><div class="metric-label">Bénéfice Net Cash</div><div class="metric-value {c_color}">{total_euro:+.2f} €</div></div>', unsafe_allow_html=True)
with c2:
    st.markdown(f'<div class="metric-container"><div class="metric-label">Unités Générées</div><div class="metric-value {c_color}">{total_u:+.1f} U</div></div>', unsafe_allow_html=True)
with c3:
    st.markdown(f'<div class="metric-container"><div class="metric-label">ROI Global Pondéré</div><div class="metric-value {c_color}">{roi:+.1f}%</div></div>', unsafe_allow_html=True)

c4, c5, c6 = st.columns(3)
with c4:
    st.markdown(f'<div class="metric-container"><div class="metric-label">Picks Sélectionnés (OMEGA)</div><div class="metric-value">{total_picks}</div></div>', unsafe_allow_html=True)
with c5:
    st.markdown(f'<div class="metric-container"><div class="metric-label">Taux de Réussite (Winrate)</div><div class="metric-value">{winrate:.1f}%</div></div>', unsafe_allow_html=True)
with c6:
    st.markdown(f'<div class="metric-container"><div class="metric-label">Mise Engagée Totale</div><div class="metric-value">{df_sim["mise_u"].sum() * unit_euro:.0f} €</div></div>', unsafe_allow_html=True)

st.markdown("---")

# Chart Courbe de Richesse
st.subheader("📈 Croissance du Capital (en Euros)")

# Agréger par jour en cas de sélections multiples
daily_euro = df_sim.groupby(df_sim['date'].dt.date)['gain_euro'].sum().reset_index()
daily_euro = daily_euro.sort_values('date')
daily_euro['Cumul Cash (€)'] = daily_euro['gain_euro'].cumsum()

fig_cash = px.line(daily_euro, x='date', y='Cumul Cash (€)', 
                       labels={'date': 'Date', 'Cumul Cash (€)': 'Solde Cumulé (€)'},
                       template='plotly_dark')
fig_cash.add_hline(y=0, line_dash="dash", line_color="#F87171")
# Color in green and fill area
fig_cash.update_traces(line_color='#4ADE80', fill='tozeroy', fillcolor='rgba(74, 222, 128, 0.1)')
st.plotly_chart(fig_cash, use_container_width=True)

colA, colB = st.columns(2)
with colA:
    st.subheader("📊 Profit par Marché (€)")
    market_df = df_sim.groupby('categorie')['gain_euro'].sum().reset_index()
    fig_market = px.bar(market_df, x='categorie', y='gain_euro', color='gain_euro',
                        color_continuous_scale="RdYlGn", text_auto='.2s',
                        template="plotly_dark", title="Rentabilité Cash par Catégorie")
    st.plotly_chart(fig_market, use_container_width=True)

with colB:
    st.subheader("🎲 Winrate Probas Actuelles")
    st.json(probas_actuelles)
    st.caption("Le moteur de recommandation se base sur ces taux mis à jour hebdomadairement par le script Bayésien.")

st.markdown("---")
st.subheader("📋 Derniers Paris OMEGA Simulés")
st.dataframe(df_sim.sort_values(by='date', ascending=False).head(50), use_container_width=True)
