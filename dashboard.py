import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import plotly.graph_objects as go
import os
import sys

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
def load_and_simulate(unit_value_euro: float):
    if not os.path.exists(DB_PATH) or not os.path.exists(SETTINGS_PATH):
        return pd.DataFrame(), {}

    # Charger les configurations V18 actuelles
    with open(SETTINGS_PATH, "rb") as f:
        cfg = tomllib.load(f)
    try:
        import json
        with open(PROBAS_PATH, "r") as f:
            probas = json.load(f)
    except:
        probas = {"buteurs": 0.23, "passeurs": 0.35, "pointeurs": 0.50}

    # Connexion DB : On charge TOUS les joueurs évalués
    conn = sqlite3.connect(DB_PATH)
    # On limite aux joueurs ayant un resultat connu
    query = "SELECT * FROM players WHERE but IS NOT NULL AND but != ''"
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
    cotes_but_dict = cotes_df_but.set_index(['date', 'joueur'])['cote'].to_dict()
    cotes_ast_dict = cotes_df_ast.set_index(['date', 'joueur'])['cote'].to_dict()
    cotes_pts_dict = cotes_df_pts.set_index(['date', 'joueur'])['cote'].to_dict()

    results = []

    # Moteur V18 manuel (Backtesting)
    for idx, row in df.iterrows():
        p_date = row['date'].strftime("%Y-%m-%d")
        joueur = row['joueur']
        key = (p_date, joueur)
        
        # Stats
        hdcf = float(row['hdcf']) if pd.notna(row['hdcf']) else 0
        sog = float(row['sog']) if pd.notna(row['sog']) else 0
        atoi = float(row['atoi']) if pd.notna(row['atoi']) else 0
        opp_ga = float(row['ga_g']) if pd.notna(row['ga_g']) else 0
        season_g = float(row['season_g']) if pd.notna(row['season_g']) else 0
        season_a = float(row['season_a']) if pd.notna(row['season_a']) else 0
        season_pts = float(row['season_pts']) if pd.notna(row['season_pts']) else 0
        is_home = bool(row['is_home'])
        
        # Logs de Resultats réels
        res_but = int(row['but']) > 0
        res_ast = int(row['assist']) > 0
        res_pts = int(row['point']) > 0

        # Simulation BUTEUR
        bf = cfg["thresholds"].get("buteurs", {})
        if (hdcf >= bf.get("l10_hdcf_min", 0) and 
            atoi >= bf.get("atoi_min", cfg["thresholds"]["general"].get("atoi_min", 0)) and 
            opp_ga >= bf.get("opp_ga_min", 0) and 
            season_g >= bf.get("season_g_min", 0)):
            
            cote = cotes_but_dict.get(key)
            if not cote: cote = 3.20 # Cote médiane buteur estimée
            
            if cote >= bf.get("cote_min", 2.50):
                p_val = probas.get("buteurs", {})
                b_prob = p_val.get("proba", 0.23) if isinstance(p_val, dict) else p_val
                edge = (b_prob * cote) - 1.0
                if edge > 0:
                    quarter_f = (edge / (cote - 1)) * 0.25
                    mise = round(quarter_f * 100 * 2) / 2
                    mise = min(max(mise, 0.5), cfg["kelly"].get("buteur_cap", 3.0))
                    
                    gain_u = (cote * mise - mise) if res_but else -mise
                    results.append({"date": row['date'], "joueur": joueur, "categorie": "BUTEUR",
                                   "cote": cote, "mise_u": mise, "edge_pct": edge*100, 
                                   "gain_u": gain_u, "gain_euro": gain_u * unit_value_euro,
                                   "won": res_but, "equipe": row['equipe'], "adv": row['adversaire']})

        # Simulation PASSEUR
        af = cfg["thresholds"].get("passeurs", {})
        if (atoi >= af.get("atoi_min", 0) and 
            opp_ga >= af.get("opp_ga_min", 0) and 
            season_a >= af.get("season_a_min", 0)):
            
            cote = cotes_ast_dict.get(key)
            if not cote: cote = 2.40
            
            if cote >= af.get("cote_min", 2.00):
                p_val = probas.get("passeurs", {})
                a_prob = p_val.get("proba", 0.35) if isinstance(p_val, dict) else p_val
                edge = (a_prob * cote) - 1.0
                if edge > 0:
                    quarter_f = (edge / (cote - 1)) * 0.25
                    mise = round(quarter_f * 100 * 2) / 2
                    mise = min(max(mise, 0.5), cfg["kelly"].get("passeur_cap", 2.0))
                    
                    gain_u = (cote * mise - mise) if res_ast else -mise
                    results.append({"date": row['date'], "joueur": joueur, "categorie": "PASSEUR",
                                   "cote": cote, "mise_u": mise, "edge_pct": edge*100, 
                                   "gain_u": gain_u, "gain_euro": gain_u * unit_value_euro,
                                   "won": res_ast, "equipe": row['equipe'], "adv": row['adversaire']})

        # Simulation POINTEUR
        pf = cfg["thresholds"].get("pointeurs", {})
        if (atoi >= pf.get("atoi_min", 0) and 
            opp_ga >= pf.get("opp_ga_min", 0) and 
            season_pts >= pf.get("season_pts_min", 0)):
            
            cote = cotes_pts_dict.get(key)
            if not cote: cote = 1.90
            
            if cote >= pf.get("cote_min", 1.50):
                p_val = probas.get("pointeurs", {})
                p_prob = p_val.get("proba", 0.50) if isinstance(p_val, dict) else p_val
                edge = (p_prob * cote) - 1.0
                if edge > 0:
                    quarter_f = (edge / (cote - 1)) * 0.25
                    mise = round(quarter_f * 100 * 2) / 2
                    mise = min(max(mise, 0.5), cfg["kelly"].get("pointeur_cap", 2.0))
                    
                    gain_u = (cote * mise - mise) if res_pts else -mise
                    results.append({"date": row['date'], "joueur": joueur, "categorie": "POINTEUR",
                                   "cote": cote, "mise_u": mise, "edge_pct": edge*100, 
                                   "gain_u": gain_u, "gain_euro": gain_u * unit_value_euro,
                                   "won": res_pts, "equipe": row['equipe'], "adv": row['adversaire']})

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
            
        # Double Points
        if len(best_pts) >= 2:
            add_combo(best_pts[0], best_pts[1], "COMBO DOUBLE PTS", 0.5)
            
        # Duo Booster
        booster = find_cross_duo(best_ast, best_pts)
        if booster: add_combo(booster[0], booster[1], "COMBO DUO BOOSTER", 0.5)
            
        # Duo Offensif
        offensif = find_cross_duo(best_but, best_pts)
        if offensif: add_combo(offensif[0], offensif[1], "COMBO DUO OFFENSIF", 0.5)
            
        # Double Buteur
        dbut = find_cross_duo(best_but, best_but)
        if dbut: add_combo(dbut[0], dbut[1], "COMBO DOUBLE BUTEUR", 0.3)
        
    results.extend(parlay_results)

    sim_df = pd.DataFrame(results)
    if not sim_df.empty:
        sim_df = sim_df.sort_values('date')
        sim_df['cumul_u'] = sim_df['gain_u'].cumsum()
        sim_df['cumul_euro'] = sim_df['gain_euro'].cumsum()

    return sim_df, probas

# ----- INTERFACE -----
st.sidebar.image("https://upload.wikimedia.org/wikipedia/en/thumb/3/3a/05_NHL_Shield.svg/1200px-05_NHL_Shield.svg.png", width=80)
st.sidebar.title("Simulateur Quant V18.3")

unit_euro = st.sidebar.number_input("💵 Valeur d'1 Unité (en €)", min_value=1.0, max_value=500.0, value=10.0, step=5.0)

st.sidebar.markdown("---")
st.sidebar.info("📌 Ce dashboard 'rejoue' l'intégralité de tes données historiques à travers le **Moteur V18.3 actuel** (Singles & Combinés)")

st.title(f"🚀 Dashboard Simulateur V18.3")
st.markdown(f"Si l'algorithme V18.3 actuel avait tourné depuis le début de la récolte de Data, avec **1 Unité = {unit_euro} €** :")

df_sim, probas_actuelles = load_and_simulate(unit_euro)

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
    st.markdown(f'<div class="metric-container"><div class="metric-label">Picks Sélectionnés (V18)</div><div class="metric-value">{total_picks}</div></div>', unsafe_allow_html=True)
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
st.subheader("📋 Derniers Paris V18 Simulés")
st.dataframe(df_sim.sort_values(by='date', ascending=False).head(50), use_container_width=True)
