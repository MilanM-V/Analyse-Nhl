import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import plotly.graph_objects as go
import os
from datetime import datetime, timedelta
st.set_page_config(
    page_title="NHL Betting Bot | Dashboard V15.4",
    page_icon="🏒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom minimal dark theme injection
st.markdown("""
<style>
    .reportview-container {
        background: #0E1117;
    }
    .metric-container {
        border-radius: 10px;
        background-color: #1E202B;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        text-align: center;
    }
    .metric-label {
        color: #94A3B8;
        font-size: 0.9rem;
        margin-bottom: 5px;
    }
    .metric-value {
        color: #F8FAFC;
        font-size: 1.8rem;
        font-weight: bold;
    }
    h1, h2, h3 {
        color: #E2E8F0;
    }
</style>
""", unsafe_allow_html=True)

DB_PATH = "bot_database.db"

@st.cache_data(ttl=300)
def load_data(table_name="picks", target_col="but"):
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        query = f"SELECT * FROM {table_name} WHERE {target_col} IS NOT NULL AND {target_col} != ''"
        df = pd.read_sql_query(query, conn)
        conn.close()
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df['result'] = pd.to_numeric(df[target_col], errors='coerce').fillna(0).astype(int)
            # Calcul du profit avec la cote si disponible
            if 'cote' in df.columns:
                df['real_cote'] = pd.to_numeric(df['cote'], errors='coerce')
                
                mean_cote = round(df['real_cote'].mean(), 2)
                mean_cote = mean_cote if pd.notna(mean_cote) else 1.85
                
                df['cote'] = df['real_cote'].fillna(mean_cote)
                df['unit'] = df.apply(lambda row: (row['cote'] - 1) if row['result'] > 0 else -1, axis=1)
            else:
                df['unit'] = df['result'].apply(lambda x: 1 if x > 0 else -1)
                
            df = df.sort_values('date')
            df['market'] = table_name.replace('picks_', '').replace('picks', 'buts').upper()
        return df
    except Exception as e:
        st.error(f"Erreur de lecture ({table_name}) : {e}")
        return pd.DataFrame()

# Sidebar
st.sidebar.image("https://upload.wikimedia.org/wikipedia/en/thumb/3/3a/05_NHL_Shield.svg/1200px-05_NHL_Shield.svg.png", width=80)
st.sidebar.title("NHL Bot V15.4")
market_filter = st.sidebar.radio("Marché à analyser :", ["GLOBAL", "BUTEURS", "PASSEURS", "POINTEURS"])
time_filter = st.sidebar.selectbox("Période :", ["Tout (All Time)", "7 Derniers Jours", "30 Derniers Jours", "Saison Actuelle"])
st.sidebar.markdown("---")
st.sidebar.info("Connecté à `bot_database.db`")

# Load all data
df_buts = load_data("picks", "but")
df_asts = load_data("picks_assists", "assist")
df_pts = load_data("picks_points", "point")

def apply_time_filter(data_df, time_selection):
    if data_df.empty: return data_df
    now = pd.to_datetime('today')
    if time_selection == "7 Derniers Jours":
        return data_df[data_df['date'] >= now - pd.Timedelta(days=7)]
    elif time_selection == "30 Derniers Jours":
        return data_df[data_df['date'] >= now - pd.Timedelta(days=30)]
    elif time_selection == "Saison Actuelle":
        season_start_year = now.year if now.month >= 8 else now.year - 1
        return data_df[data_df['date'] >= pd.to_datetime(f'{season_start_year}-10-01')]
    return data_df

df_buts = apply_time_filter(df_buts, time_filter)
df_asts = apply_time_filter(df_asts, time_filter)
df_pts = apply_time_filter(df_pts, time_filter)

# Combine for global or filter
if market_filter == "GLOBAL":
    df = pd.concat([df_buts, df_asts, df_pts]).sort_values('date').reset_index(drop=True)
    title_suffix = "Global"
elif market_filter == "BUTEURS":
    df = df_buts.reset_index(drop=True)
    title_suffix = "Buteurs"
elif market_filter == "PASSEURS":
    df = df_asts.reset_index(drop=True)
    title_suffix = "Passeurs"
else:
    df = df_pts.reset_index(drop=True)
    title_suffix = "Pointeurs"

# ----- Filtre des Catégories -----
if not df.empty and 'verdict' in df.columns:
    available_cats = sorted(df['verdict'].dropna().unique().tolist())
    selected_cats = st.sidebar.multiselect("Filtrer par Catégorie :", available_cats, default=available_cats)
    if selected_cats:
        df = df[df['verdict'].isin(selected_cats)].reset_index(drop=True)

# Recalcul des unités cumulées pour la période filtrée
if not df.empty:
    df['cumulative_units'] = df['unit'].cumsum()

st.title(f"📊 NHL Betting Bot — {title_suffix}")

if df.empty:
    st.warning(f"⚠️ Aucune donnée disponible pour le marché {market_filter}.")
    st.stop()

# ----- ROW 1: KPIs (2 lignes de 3) -----
total_played = len(df)
total_won = df['result'].sum()
global_units = round(df['unit'].sum(), 1)
winrate = (total_won / total_played * 100) if total_played > 0 else 0
roi_pct = round((global_units / total_played) * 100, 1) if total_played > 0 else 0
if 'real_cote' in df.columns and pd.notna(df['real_cote'].mean()):
    avg_cote = round(df['real_cote'].mean(), 2)
else:
    avg_cote = "N/A"

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown(f'<div class="metric-container"><div class="metric-label">Profit Total</div><div class="metric-value" style="color:{"#4ADE80" if global_units >=0 else "#F87171"}">{global_units:+} U</div></div>', unsafe_allow_html=True)

with col2:
    st.markdown(f'<div class="metric-container"><div class="metric-label">Picks Résolus</div><div class="metric-value">{total_played}</div></div>', unsafe_allow_html=True)

with col3:
    st.markdown(f'<div class="metric-container"><div class="metric-label">Win Rate</div><div class="metric-value">{winrate:.1f}%</div></div>', unsafe_allow_html=True)

col4, col5, col6 = st.columns(3)

with col4:
    roi_color = "#4ADE80" if roi_pct >= 0 else "#F87171"
    st.markdown(f'<div class="metric-container"><div class="metric-label">ROI</div><div class="metric-value" style="color:{roi_color}">{roi_pct:+.1f}%</div></div>', unsafe_allow_html=True)

with col5:
    st.markdown(f'<div class="metric-container"><div class="metric-label">Cote Moyenne</div><div class="metric-value">{avg_cote}</div></div>', unsafe_allow_html=True)

with col6:
    best_market = df.groupby('market')['unit'].sum().idxmax() if market_filter == "GLOBAL" else market_filter
    st.markdown(f'<div class="metric-container"><div class="metric-label">Top Marché</div><div class="metric-value">{best_market}</div></div>', unsafe_allow_html=True)

st.markdown("---")

# ----- ROW 2: Charts -----
c1, c2 = st.columns([2, 1])

with c1:
    st.subheader("📈 Courbe de Profit")
    fig_bankroll = px.line(df, x=df.index, y='cumulative_units', 
                           labels={'index': 'Nombre de Paris', 'cumulative_units': 'Profit (Unités)'},
                           template='plotly_dark', color_discrete_sequence=['#38bdf8'])
    fig_bankroll.add_hline(y=0, line_dash="dash", line_color="#F87171")
    fig_bankroll.update_layout(hovermode="x unified")
    st.plotly_chart(fig_bankroll, use_container_width=True)

with c2:
    st.subheader("🎯 Performance par Marché")
    if market_filter == "GLOBAL":
        market_stats = df.groupby('market').agg(
            Units=('unit', 'sum'),
            WinRate=('result', lambda x: (x.sum() / len(x)) * 100)
        ).reset_index()
        fig_market = px.bar(market_stats, x='market', y='Units', color='WinRate',
                            color_continuous_scale="RdYlGn", text_auto='.1f',
                            template='plotly_dark')
        st.plotly_chart(fig_market, use_container_width=True)
    else:
        st.info("Sélectionnez 'GLOBAL' pour comparer les marchés.")

# ----- ROW 3: Profit par Jour -----
st.markdown("---")
st.subheader("📅 Profit par Jour")
daily_df = df.groupby(df['date'].dt.date).agg(
    Units=('unit', 'sum'),
    Picks=('unit', 'count')
).reset_index()
daily_df.columns = ['Date', 'Units', 'Picks']
daily_df['Units'] = daily_df['Units'].round(1)
daily_df['Color'] = daily_df['Units'].apply(lambda x: '#4ADE80' if x >= 0 else '#F87171')

fig_daily = go.Figure()
fig_daily.add_trace(go.Bar(
    x=daily_df['Date'], y=daily_df['Units'],
    marker_color=daily_df['Color'],
    text=daily_df['Units'].apply(lambda x: f"{x:+.1f}"),
    textposition='outside',
    hovertemplate='%{x}<br>Profit: %{y:.1f} U<br>Picks: %{customdata}<extra></extra>',
    customdata=daily_df['Picks']
))
fig_daily.update_layout(
    template='plotly_dark', showlegend=False, 
    yaxis_title='Profit (Unités)', xaxis_title='',
    height=350
)
fig_daily.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.2)")
st.plotly_chart(fig_daily, use_container_width=True)

# ----- ROW 4: Categories & Teams -----
st.markdown("---")
colA, colB = st.columns(2)

with colA:
    st.subheader("🏅 Performance par Catégorie")
    cat_df = df.groupby('verdict').agg(
        Played=('unit', 'count'),
        Won=('result', 'sum'),
        Units=('unit', 'sum')
    ).reset_index()
    cat_df['WinRate'] = (cat_df['Won'] / cat_df['Played'] * 100)
    
    fig_cat = px.bar(cat_df, x='verdict', y='Units', color='WinRate',
                     color_continuous_scale="Viridis", text_auto='.1f',
                     template="plotly_dark")
    st.plotly_chart(fig_cat, use_container_width=True)

with colB:
    st.subheader("🛡️ Profit par Équipe")
    team_df = df.groupby('equipe').agg(
        Played=('unit', 'count'),
        Units=('unit', 'sum')
    ).reset_index()
    team_df = team_df[team_df['Played'] >= 2].sort_values(by='Units', ascending=False).head(10)
    
    if not team_df.empty:
        fig_team = px.bar(team_df, x='equipe', y='Units', color='Units',
                          color_continuous_scale="RdYlGn", text_auto='.1f',
                          template="plotly_dark")
        st.plotly_chart(fig_team, use_container_width=True)
    else:
        st.info("Données insuffisantes par équipe.")

# ----- ROW 5: Top & Worst Players -----
st.markdown("---")
pA, pB = st.columns(2)

with pA:
    st.subheader("⭐ Top Performers")
    player_df = df.groupby('joueur').agg(
        Played=('unit', 'count'),
        Units=('unit', 'sum')
    ).reset_index()
    top_players = player_df[player_df['Units'] > 0].sort_values(by='Units', ascending=True).tail(10)

    if not top_players.empty:
        fig_top = px.bar(top_players, y='joueur', x='Units', orientation='h',
                         color='Units', color_continuous_scale="Greens",
                         text_auto='.1f', template="plotly_dark")
        st.plotly_chart(fig_top, use_container_width=True)
    else:
        st.info("Aucun joueur en profit pour le moment.")

with pB:
    st.subheader("💀 Worst Performers")
    worst_players = player_df[player_df['Units'] < 0].sort_values(by='Units', ascending=True).head(10)

    if not worst_players.empty:
        fig_worst = px.bar(worst_players, y='joueur', x='Units', orientation='h',
                           color='Units', color_continuous_scale="Reds_r",
                           text_auto='.1f', template="plotly_dark")
        st.plotly_chart(fig_worst, use_container_width=True)
    else:
        st.info("Aucun joueur en perte pour le moment.")

# ----- ROW 6: Data Table -----
st.markdown("---")
st.subheader("🗂️ Journal des Paris")
st.dataframe(df.drop(columns=['id', 'result', 'unit', 'cumulative_units'], errors='ignore').sort_values(by='date', ascending=False), use_container_width=True)
st.caption(f"Dashboard V15.4 | {datetime.now().strftime('%d/%m/%Y %H:%M')} | Antigravity Architecture")
