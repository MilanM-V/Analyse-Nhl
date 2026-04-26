"""
OMEGA DASHBOARD V3 — v19.7 vs v19.16
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import json, os, sys

st.set_page_config(page_title="OMEGA | v19.7 vs v19.16", page_icon="🔬", layout="wide")

st.markdown("""
<style>
    .stApp { background: #0a0e1a; }
    .omega-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 30px; border-radius: 16px; text-align: center;
        border: 1px solid rgba(100, 200, 255, 0.15);
        box-shadow: 0 8px 32px rgba(0,0,0,0.4); margin-bottom: 20px;
    }
    .omega-header h1 { color: #e2e8f0; font-size: 2.2rem; margin: 0; font-weight: 800; }
    .omega-header p { color: #94a3b8; font-size: 1rem; margin: 5px 0 0 0; }
    .card {
        background: linear-gradient(145deg, #1e2130 0%, #171923 100%);
        padding: 20px; border-radius: 14px;
        border: 1px solid #2d3748; text-align: center;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    }
    .card-label { color: #94a3b8; font-size: 0.85rem; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }
    .card-value { font-size: 1.8rem; font-weight: 800; margin: 8px 0 0 0; }
    .green { color: #4ade80; } .red { color: #f87171; }
    .blue { color: #60a5fa; } .amber { color: #fbbf24; }
    .winner-banner {
        background: linear-gradient(135deg, #064e3b 0%, #065f46 100%);
        padding: 20px; border-radius: 12px; text-align: center;
        border: 2px solid #10b981; margin: 15px 0;
    }
    .loser-banner {
        background: linear-gradient(135deg, #450a0a 0%, #7f1d1d 100%);
        padding: 20px; border-radius: 12px; text-align: center;
        border: 2px solid #ef4444; margin: 15px 0;
    }
    .stitle { color: #e2e8f0; font-size: 1.3rem; font-weight: 700;
        border-bottom: 2px solid #3b82f6; padding-bottom: 8px; margin: 30px 0 15px 0; }
</style>
""", unsafe_allow_html=True)

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch", "omega_results.json")

@st.cache_data
def load_data():
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

data = load_data()
v197 = data['v197']; v1916 = data['v1916']; period = data['period']

# HEADER
st.markdown(f"""
<div class="omega-header">
    <h1>🔬 OMEGA ANALYSIS — v19.7 vs v19.16</h1>
    <p>{period['total_eval']} joueurs | {period['start']} - {period['end']} | Simulation sur donnees reelles DB</p>
</div>""", unsafe_allow_html=True)

# VERDICT
col_w, col_l = st.columns(2)
with col_w:
    st.markdown(f"""<div class="winner-banner">
        <div style="color: #6ee7b7; font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 2px;">🏆 GAGNANT</div>
        <div style="color: #ecfdf5; font-size: 1.8rem; font-weight: 800; margin: 8px 0;">v19.7 (Quarter Kelly, Stricts)</div>
        <div style="color: #a7f3d0; font-size: 1.4rem;">{v197['profit_u']:+.1f} U | ROI {v197['roi_pct']:+.1f}%</div>
    </div>""", unsafe_allow_html=True)
with col_l:
    st.markdown(f"""<div class="loser-banner">
        <div style="color: #fca5a5; font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 2px;">⚠️ PERDANT</div>
        <div style="color: #fef2f2; font-size: 1.8rem; font-weight: 800; margin: 8px 0;">v19.16 (Full Kelly, Ouverts)</div>
        <div style="color: #fca5a5; font-size: 1.4rem;">{v1916['profit_u']:+.1f} U | ROI {v1916['roi_pct']:+.1f}%</div>
    </div>""", unsafe_allow_html=True)

# KPI
st.markdown('<div class="stitle">📊 KPIs Comparatifs</div>', unsafe_allow_html=True)

def kpi(label, v1, v2, fmt="+.1f", suf="", higher_better=True):
    c1 = "green" if (v1>v2 if higher_better else v1<v2) else "red"
    c2 = "green" if (v2>v1 if higher_better else v2<v1) else "red"
    return f"""<div class="card"><div class="card-label">{label}</div>
    <div style="display:flex;justify-content:space-around;margin-top:10px;">
    <div><div style="color:#64748b;font-size:0.7rem;">v19.7</div><div class="card-value {c1}">{v1:{fmt}}{suf}</div></div>
    <div style="border-left:1px solid #334155;"></div>
    <div><div style="color:#64748b;font-size:0.7rem;">v19.16</div><div class="card-value {c2}">{v2:{fmt}}{suf}</div></div>
    </div></div>"""

c1,c2,c3,c4,c5 = st.columns(5)
with c1: st.markdown(kpi("Profit Net", v197['profit_u'], v1916['profit_u'], suf=" U"), unsafe_allow_html=True)
with c2: st.markdown(kpi("ROI", v197['roi_pct'], v1916['roi_pct'], suf="%"), unsafe_allow_html=True)
with c3: st.markdown(kpi("Winrate", v197['winrate'], v1916['winrate'], suf="%"), unsafe_allow_html=True)
with c4: st.markdown(kpi("Volume", v197['total_picks'], v1916['total_picks'], fmt="d", suf=" picks"), unsafe_allow_html=True)
with c5: st.markdown(kpi("Max DD", v197['max_drawdown'], v1916['max_drawdown'], suf=" U", higher_better=False), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
c6,c7,c8,c9,c10 = st.columns(5)
with c6: st.markdown(kpi("Mise Totale", v197['total_mise'], v1916['total_mise'], suf=" U"), unsafe_allow_html=True)
with c7: st.markdown(kpi("Cote Moy", v197['avg_cote'], v1916['avg_cote'], fmt=".2f"), unsafe_allow_html=True)
with c8: st.markdown(kpi("Picks Won", v197['total_won'], v1916['total_won'], fmt="d"), unsafe_allow_html=True)
with c9: st.markdown(kpi("Odds Reelles", v197.get('real_odds_pct',0), v1916.get('real_odds_pct',0), suf="%"), unsafe_allow_html=True)
with c10:
    v1d = v197['profit_u']/max(1,v197['num_days']); v2d = v1916['profit_u']/max(1,v1916['num_days'])
    st.markdown(kpi("U/Jour", v1d, v2d), unsafe_allow_html=True)

# EQUITY CURVES
st.markdown('<div class="stitle">📈 Courbes de Profit Cumulees</div>', unsafe_allow_html=True)
fig = go.Figure()
d7 = sorted(v197['daily'].keys()); c7 = [v197['daily'][d]['cumul'] for d in d7]
d16 = sorted(v1916['daily'].keys()); c16 = [v1916['daily'][d]['cumul'] for d in d16]
fig.add_trace(go.Scatter(x=d7, y=c7, mode='lines+markers', name='v19.7',
    line=dict(color='#10b981', width=3), marker=dict(size=5), fill='tozeroy', fillcolor='rgba(16,185,129,0.1)'))
fig.add_trace(go.Scatter(x=d16, y=c16, mode='lines+markers', name='v19.16',
    line=dict(color='#ef4444', width=3), marker=dict(size=5), fill='tozeroy', fillcolor='rgba(239,68,68,0.1)'))
fig.add_hline(y=0, line_dash="dash", line_color="#475569")
fig.update_layout(template="plotly_dark", height=450, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
    xaxis_title="Date", yaxis_title="Profit (U)", hovermode="x unified", margin=dict(l=0,r=0,t=30,b=0),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
st.plotly_chart(fig, use_container_width=True)

# DAILY BAR
st.markdown('<div class="stitle">📊 Gain Journalier</div>', unsafe_allow_html=True)
all_d = sorted(set(list(v197['daily'].keys()) + list(v1916['daily'].keys())))
fig_bar = go.Figure()
fig_bar.add_trace(go.Bar(x=all_d, y=[v197['daily'].get(d,{}).get('gain',0) for d in all_d], name='v19.7', marker_color='#10b981', opacity=0.8))
fig_bar.add_trace(go.Bar(x=all_d, y=[v1916['daily'].get(d,{}).get('gain',0) for d in all_d], name='v19.16', marker_color='#ef4444', opacity=0.8))
fig_bar.add_hline(y=0, line_dash="dash", line_color="#475569")
fig_bar.update_layout(template="plotly_dark", height=350, barmode='group', paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=0,r=0,t=10,b=0), yaxis_title="Gain (U)")
st.plotly_chart(fig_bar, use_container_width=True)

# CATEGORIES
st.markdown('<div class="stitle">🎯 Performance par Categorie</div>', unsafe_allow_html=True)
col1, col2 = st.columns(2)
with col1:
    st.markdown("#### v19.7 (Quarter Kelly)")
    rows = [{'Cat': c, **{k:v for k,v in m.items()}} for c, m in v197['categories'].items()]
    if rows: st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
with col2:
    st.markdown("#### v19.16 (Full Kelly)")
    rows = [{'Cat': c, **{k:v for k,v in m.items()}} for c, m in v1916['categories'].items()]
    if rows: st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# CONFIG DIFF
st.markdown('<div class="stitle">⚙️ Differences de Configuration</div>', unsafe_allow_html=True)
diff_data = [
    {"Parametre": "Buteur season_g_min", "v19.7": "0.40", "v19.16": "0.50", "Impact": "V19.7 plus permissif"},
    {"Parametre": "Buteur cote_min", "v19.7": "3.00", "v19.16": "0.00", "Impact": "V19.7 filtre les cotes faibles"},
    {"Parametre": "Buteur kelly_cap", "v19.7": "3.0 U", "v19.16": "0.0 U (OFF)", "Impact": "V19.16 DESACTIVE les buteurs"},
    {"Parametre": "Passeur season_a_min", "v19.7": "0.50", "v19.16": "0.35", "Impact": "V19.16 plus permissif"},
    {"Parametre": "Passeur l10_a_min", "v19.7": "0.80", "v19.16": "0.30", "Impact": "V19.16 beaucoup plus permissif"},
    {"Parametre": "Passeur home_only", "v19.7": "true", "v19.16": "false", "Impact": "V19.16 accepte l'exterieur"},
    {"Parametre": "Passeur atoi_min", "v19.7": "18.0", "v19.16": "16.0", "Impact": "V19.16 plus permissif"},
    {"Parametre": "Passeur cote_min", "v19.7": "2.20", "v19.16": "0.00", "Impact": "V19.7 filtre les cotes faibles"},
    {"Parametre": "Pointeur season_pts_min", "v19.7": "0.90", "v19.16": "0.55", "Impact": "V19.16 beaucoup plus permissif"},
    {"Parametre": "Pointeur l10_pts_min", "v19.7": "0.80", "v19.16": "0.30", "Impact": "V19.16 beaucoup plus permissif"},
    {"Parametre": "Pointeur home_only", "v19.7": "true", "v19.16": "false", "Impact": "V19.16 accepte l'exterieur"},
    {"Parametre": "Kelly Fraction", "v19.7": "Quarter (f/4)", "v19.16": "Full (f*1)", "Impact": "V19.16 mise 4x plus"},
    {"Parametre": "Pointeur kelly_cap", "v19.7": "2.0 U", "v19.16": "5.0 U", "Impact": "V19.16 expose 2.5x plus"},
    {"Parametre": "Proba Passeurs", "v19.7": "0.50", "v19.16": "0.41", "Impact": "V19.7 plus optimiste"},
    {"Parametre": "Proba Pointeurs", "v19.7": "0.65", "v19.16": "0.57", "Impact": "V19.7 plus optimiste"},
    {"Parametre": "Bonus PP1/B2B", "v19.7": "Non", "v19.16": "Oui (+0.05)", "Impact": "V19.16 plus adaptatif"},
    {"Parametre": "Away Penalty", "v19.7": "Non", "v19.16": "Oui (+0.10)", "Impact": "V19.16 penalise l'exterieur"},
]
st.dataframe(pd.DataFrame(diff_data), use_container_width=True, hide_index=True)

# PICKS TABLES
st.markdown('<div class="stitle">📋 Historique Picks</div>', unsafe_allow_html=True)
tab1, tab2 = st.tabs(["v19.7", "v19.16"])
with tab1:
    df = pd.DataFrame(data['v197_results'])
    if not df.empty:
        df = df.sort_values('date', ascending=False)
        st.dataframe(df[['date','joueur','adversaire','categorie','cote','mise','gain','won','edge']], use_container_width=True, hide_index=True)
with tab2:
    df = pd.DataFrame(data['v1916_results'])
    if not df.empty:
        df = df.sort_values('date', ascending=False)
        st.dataframe(df[['date','joueur','adversaire','categorie','cote','mise','gain','won','edge']], use_container_width=True, hide_index=True)

# IMPUTATION
st.markdown('<div class="stitle">🔍 Transparence Cotes</div>', unsafe_allow_html=True)
ac = data['avg_cotes']
st.markdown(f"""<div class="card" style="text-align:left;">
<div class="card-label">Imputation des cotes manquantes</div>
<p style="color:#94a3b8;margin-top:10px;">
<b>v19.7</b>: {v197.get('real_odds_pct',0)}% de cotes reelles — {100-v197.get('real_odds_pct',0):.0f}% imputees<br>
<b>v19.16</b>: {v1916.get('real_odds_pct',0)}% de cotes reelles — {100-v1916.get('real_odds_pct',0):.0f}% imputees<br><br>
Cotes moyennes utilisees: BUT={ac['buteur']}, AST={ac['passeur']}, PTS={ac['pointeur']}<br><br>
<span style="color:#fbbf24;">⚠️ v19.7 a 94% de cotes imputees car les filtres selectionnent des joueurs qui n'avaient souvent pas de cote dans les tables picks.</span>
</p></div>""", unsafe_allow_html=True)

st.markdown(f"""<div style="text-align:center;padding:30px;color:#475569;font-size:0.8rem;margin-top:40px;border-top:1px solid #1e293b;">
OMEGA Analysis V3 | {period['total_eval']} joueurs | {period['start']} - {period['end']}
</div>""", unsafe_allow_html=True)
