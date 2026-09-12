import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import plotly.graph_objects as go
import os
import sys

# Ajout du dossier racine au sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mlb.core.database import load_all_pitcher_stats

st.set_page_config(
    page_title="MLB Quant Simulator | V2",
    page_icon="⚾",
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

PORTFOLIO_DB_PATH = "portfolio.db"

@st.cache_data(ttl=60)
def load_portfolio_data():
    if not os.path.exists(PORTFOLIO_DB_PATH):
        return pd.DataFrame()
        
    conn = sqlite3.connect(PORTFOLIO_DB_PATH)
    # Récupérer uniquement les paris MLB
    query = "SELECT * FROM portfolio WHERE sport = 'mlb' ORDER BY timestamp ASC"
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
    return df

@st.cache_data(ttl=3600)
def load_mlb_stats():
    return load_all_pitcher_stats()

def main():
    st.title("⚾ MLB Strikeouts Quant | Dashboard V2")
    st.markdown("Suivi des performances du modèle XGBoost V2 (Statcast : Velo, Spin Rate, SwStr%)")
    
    tab1, tab2, tab3 = st.tabs(["💰 Portfolio & PnL", "📈 Analyse IA & Statcast", "📜 Historique Paris"])
    
    portfolio_df = load_portfolio_data()
    mlb_stats = load_mlb_stats()
    
    with tab1:
        st.header("Performance Financière (MLB)")
        
        if portfolio_df.empty:
            st.info("Aucun pari MLB enregistré dans le portfolio pour le moment.")
        else:
            resolved_df = portfolio_df[portfolio_df['resolved'] == 1].copy()
            
            # KPIs
            col1, col2, col3, col4 = st.columns(4)
            
            total_paris = len(resolved_df)
            if total_paris > 0:
                gains_totaux = resolved_df['gain'].sum()
                mises_totales = resolved_df['mise'].sum()
                roi = (gains_totaux / mises_totales * 100) if mises_totales > 0 else 0
                winrate = (len(resolved_df[resolved_df['gain'] > 0]) / total_paris * 100)
            else:
                gains_totaux, roi, winrate = 0, 0, 0
                
            col1.metric("Paris Résolus", total_paris)
            col2.metric("Profit Cumulé (U)", f"{gains_totaux:+.2f} U")
            col3.metric("ROI Global", f"{roi:+.1f} %")
            col4.metric("Winrate", f"{winrate:.1f} %")
            
            st.divider()
            
            # Evolution PnL
            if total_paris > 0:
                resolved_df['pnl_cumule'] = resolved_df['gain'].cumsum()
                
                fig = px.area(
                    resolved_df, 
                    x='timestamp', 
                    y='pnl_cumule',
                    title="Évolution du Profit (MLB)",
                    color_discrete_sequence=['#4ADE80' if gains_totaux >= 0 else '#F87171']
                )
                fig.update_layout(
                    plot_bgcolor='rgba(0,0,0,0)', 
                    paper_bgcolor='rgba(0,0,0,0)',
                    font_color='#F8FAFC',
                    xaxis_title="Date",
                    yaxis_title="Unités (U)"
                )
                st.plotly_chart(fig, use_container_width=True)
                
    with tab2:
        st.header("Analyse Base de Données & IA")
        
        if mlb_stats.empty:
            st.warning("Base de données SQLite MLB vide.")
        else:
            st.write(f"**Taille de l'historique :** {len(mlb_stats)} lancers analysés.")
            
            col_a, col_b = st.columns(2)
            
            with col_a:
                st.subheader("Distribution des Strikeouts")
                fig_k = px.histogram(
                    mlb_stats, 
                    x='strikeouts', 
                    nbins=20,
                    title="Nb de Strikeouts par lanceur partant"
                )
                fig_k.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig_k, use_container_width=True)
                
            with col_b:
                st.subheader("Vitesse vs Strikeouts")
                fig_velo = px.scatter(
                    mlb_stats,
                    x='avg_release_speed',
                    y='strikeouts',
                    title="Corrélation Vélocité / K",
                    opacity=0.3
                )
                fig_velo.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig_velo, use_container_width=True)
                
            st.subheader("Top 10 Arbitres pro-Strikeouts")
            k_par_umpire = mlb_stats.groupby('umpire')['strikeouts'].agg(['mean', 'count'])
            k_par_umpire = k_par_umpire[k_par_umpire['count'] >= 5]
            st.dataframe(k_par_umpire.sort_values('mean', ascending=False).head(10))

    with tab3:
        st.header("Journal des paris")
        
        if portfolio_df.empty:
            st.info("Aucun pari enregistré.")
        else:
            display_cols = ['timestamp', 'player', 'market', 'cote', 'mise', 'gain', 'resolved']
            st.dataframe(
                portfolio_df[display_cols].sort_values('timestamp', ascending=False),
                use_container_width=True,
                height=600
            )

if __name__ == "__main__":
    main()
