import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import plotly.graph_objects as go
import os

st.set_page_config(
    page_title="NHL Betting Bot | Dashboard V14",
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
    }
    h1, h2, h3 {
        color: #E2E8F0;
    }
    .st-emotion-cache-1wivap2 {
        color: #38bdf8;
    }
</style>
""", unsafe_allow_html=True)

DB_PATH = "bot_database.db"

@st.cache_data(ttl=300)
def load_data():
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query("SELECT * FROM picks WHERE but IS NOT NULL AND but != ''", conn)
        conn.close()
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df['but'] = pd.to_numeric(df['but'], errors='coerce').fillna(0).astype(int)
            df['unit'] = df['but'].apply(lambda x: 1 if x > 0 else -1)
            df['cumulative_units'] = df['unit'].cumsum()
        return df
    except Exception as e:
        st.error(f"Erreur de lecture de la base de données : {e}")
        return pd.DataFrame()

# Sidebar
st.sidebar.image("https://upload.wikimedia.org/wikipedia/en/thumb/3/3a/05_NHL_Shield.svg/1200px-05_NHL_Shield.svg.png", width=100)
st.sidebar.title("NHL Bot Manager")
st.sidebar.markdown("---")
st.sidebar.info("Dashboard connecté en temps réel à SQLite `bot_database.db`.")

df = load_data()

st.title("📊 NHL Betting Bot — Dashboard (V14)")

if df.empty:
    st.warning("⚠️ La base de données est vide ou aucun pari n'a encore été validé avec le résultat (but=0/1).")
    st.stop()

# ----- ROW 1: KPIs -----
total_played = len(df)
total_won = df['but'].sum()
global_units = total_won - (total_played - total_won)
global_roi = (total_won / total_played * 100) if total_played > 0 else 0

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown('<div class="metric-container">', unsafe_allow_html=True)
    st.metric("Total Unités", f"{global_units:+} U", delta_color="normal")
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="metric-container">', unsafe_allow_html=True)
    st.metric("Picks Résolus", total_played)
    st.markdown('</div>', unsafe_allow_html=True)

with col3:
    st.markdown('<div class="metric-container">', unsafe_allow_html=True)
    st.metric("WinRate Global", f"{global_roi:.1f}%")
    st.markdown('</div>', unsafe_allow_html=True)

with col4:
    safe_elite = df[df['verdict'].isin(['ELITE', 'SAFE', 'TIREUR', 'DÉFENSEUR'])]
    top_cat = safe_elite.groupby('verdict')['unit'].sum().idxmax() if not safe_elite.empty else "N/A"
    st.markdown('<div class="metric-container">', unsafe_allow_html=True)
    st.metric("Catégorie la + Rentable", top_cat)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("---")

# ----- ROW 2: Bankroll Chart -----
st.subheader("📈 Évolution du Bankroll (Unités cumulées)")
fig_bankroll = px.line(df, x=df.index, y='cumulative_units', 
                       labels={'index': 'Chronologie des Paris', 'cumulative_units': 'Profit ($ / U)'},
                       template='plotly_dark',
                       title="Croissance de la Bankroll au fil des Vagues")
fig_bankroll.add_hline(y=0, line_dash="dash", line_color="red")
fig_bankroll.update_traces(line_color="#38bdf8", line_width=3)
st.plotly_chart(fig_bankroll, use_container_width=True)

# ----- ROW 3: Distributions -----
colA, colB = st.columns(2)

with colA:
    st.subheader("🎯 ROI par Catégorie")
    cat_df = df.groupby('verdict').agg(
        Played=('unit', 'count'),
        Won=('but', 'sum')
    ).reset_index()
    cat_df['WinRate'] = cat_df['Won'] / cat_df['Played'] * 100
    cat_df['Units'] = cat_df['Won'] - (cat_df['Played'] - cat_df['Won'])
    
    fig_cat = px.bar(cat_df, x='verdict', y='WinRate', color='Units',
                     text=cat_df['WinRate'].apply(lambda x: f"{x:.1f}%"),
                     color_continuous_scale="RdBu",
                     labels={"verdict": "Catégorie", "WinRate": "Taux de Victoire (%)"},
                     template="plotly_dark")
    st.plotly_chart(fig_cat, use_container_width=True)

with colB:
    st.subheader("🛡️ Profitabilité par Équipe")
    st.markdown("Quelles sont les équipes les plus rentables lorsqu'on parie sur un de leurs joueurs ?")
    
    team_df = df.groupby('equipe').agg(
        Played=('unit', 'count'),
        Won=('but', 'sum')
    ).reset_index()
    team_df['Units'] = team_df['Won'] - (team_df['Played'] - team_df['Won'])
    team_df['WinRate'] = (team_df['Won'] / team_df['Played']) * 100
    
    # On filtre les équipes ayant au moins 3 paris
    team_df = team_df[team_df['Played'] >= 3].sort_values(by='Units', ascending=False)
    
    if len(team_df) > 0:
        fig_team = px.bar(team_df, x='equipe', y='Units',
                          color='WinRate', color_continuous_scale="RdYlGn",
                          text=team_df['Units'].apply(lambda x: f"{x:+} U"),
                          title="Bénéfice Net par Équipe (Min. 3 paris)",
                          labels={"equipe": "Équipe", "Units": "Bénéfice Net (U)"},
                          template="plotly_dark")
        st.plotly_chart(fig_team, use_container_width=True)
    else:
        st.info("Pas assez de données par équipe (minimum 3 paris requis).")

st.markdown("---")

# ----- ROW 3.5: Best & Worst Players -----
st.subheader("⭐ Top & Flop Performers (Joueurs)")
player_df = df.groupby('joueur').agg(
    Played=('unit', 'count'),
    Won=('but', 'sum')
).reset_index()
player_df['Units'] = player_df['Won'] - (player_df['Played'] - player_df['Won'])
player_df['WinRate'] = (player_df['Won'] / player_df['Played']) * 100

col_p1, col_p2 = st.columns(2)

with col_p1:
    top_players = player_df[player_df['Units'] > 0].sort_values(by='Units', ascending=True).tail(10)
    if not top_players.empty:
        fig_top = px.bar(top_players, y='joueur', x='Units', orientation='h',
                         color='WinRate', color_continuous_scale="Greens",
                         text=top_players['Units'].apply(lambda x: f"+{x} U"),
                         title="🔥 Les plus Profitables", template="plotly_dark")
        st.plotly_chart(fig_top, use_container_width=True)
    else:
        st.info("Aucun joueur en profit.")

with col_p2:
    worst_players = player_df[player_df['Units'] < 0].sort_values(by='Units', ascending=False).tail(10)
    if not worst_players.empty:
        fig_worst = px.bar(worst_players, y='joueur', x='Units', orientation='h',
                         color='WinRate', color_continuous_scale="Reds",
                         text=worst_players['Units'].apply(lambda x: f"{x} U"),
                         title="🥶 Les moins Profitables", template="plotly_dark")
        st.plotly_chart(fig_worst, use_container_width=True)
    else:
        st.info("Aucun joueur en déficit.")

st.markdown("---")

# ----- ROW 4: Table Data -----
st.subheader("🗂️ Journal Historique des Paris")
display_cols = ['date', 'vague', 'joueur', 'equipe', 'adversaire', 'verdict', 'score', 'but']
st.dataframe(df[display_cols].sort_values(by='date', ascending=False))

st.caption("Dashboard auto-rafraîchi toutes les 5 minutes 🔄 | Propulsé par Streamlit & Antigravity V14.")
