"""
mlb/data/fetcher.py — Récupération des données MLB via pybaseball.

Ce module s'occupe de récupérer les matchs du jour, les probables pitchers,
et les stats historiques de la base de données SQLite.
"""

import sqlite3
import datetime
import logging
from typing import List, Dict, Any, Optional

import pandas as pd
import requests

logger = logging.getLogger("MLB.Fetcher")

# Chemin absolu vers la base de données MLB (à la racine de mlb/)
import os
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mlb_database.db")
logger.info(f"🗄️ Base de données MLB utilisée : {DB_PATH}")


def get_todays_probables(date_str: Optional[str] = None) -> pd.DataFrame:
    """
    Récupère les lanceurs partants probables pour une date donnée.
    
    Args:
        date_str: Date au format YYYY-MM-DD. Défaut: aujourd'hui.
        
    Returns:
        DataFrame contenant les matchups et lanceurs probables.
    """
    if not date_str:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        
    logger.info(f"[MLB] Récupération des Probable Pitchers pour le {date_str} via MLB Stats API...")
    try:
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=probablePitcher"
        r = requests.get(url, timeout=10)
        data = r.json()
        
        games = data.get("dates", [])
        if not games:
            logger.info("[MLB] Aucun match trouvé pour cette date.")
            return pd.DataFrame()
            
        matchups = []
        for game in games[0].get("games", []):
            teams = game.get("teams", {})
            away = teams.get("away", {})
            home = teams.get("home", {})
            
            away_team = away.get("team", {}).get("name")
            home_team = home.get("team", {}).get("name")
            
            away_pitcher = away.get("probablePitcher", {}).get("fullName")
            home_pitcher = home.get("probablePitcher", {}).get("fullName")
            
            if away_pitcher:
                matchups.append({
                    "Pitcher": away_pitcher,
                    "Team": away_team,
                    "Opp": f"@{home_team}"
                })
            
            if home_pitcher:
                matchups.append({
                    "Pitcher": home_pitcher,
                    "Team": home_team,
                    "Opp": away_team
                })
                
        df = pd.DataFrame(matchups)
        logger.info(f"[MLB] {len(df)} lanceurs probables trouvés.")
        return df
    except Exception as e:
        logger.error(f"[MLB] Erreur lors de la récupération des probables : {e}")
        return pd.DataFrame()


def get_pitcher_historical_stats(player_name: str, limit: int = 5) -> Dict[str, Any]:
    """
    Interroge la base de données locale pour obtenir l'historique récent d'un lanceur.
    
    Args:
        player_name: Nom du lanceur.
        limit: Nombre de matchs récents à récupérer.
        
    Returns:
        Dictionnaire avec les moyennes (K/9, ERA, etc.) ou vide si introuvable.
    """
    if not os.path.exists(DB_PATH):
        logger.warning(f"Base de données introuvable : {DB_PATH}")
        return {}
        
    try:
        conn = sqlite3.connect(DB_PATH)
        # Nettoyage du nom basique pour la correspondance
        query = """
            SELECT game_date, innings_pitched, strikeouts, hits, earned_runs, bb
            FROM mlb_pitchers 
            WHERE player_name LIKE ? 
            ORDER BY game_date DESC 
            LIMIT ?
        """
        df = pd.read_sql_query(query, conn, params=(f"%{player_name}%", limit))
        conn.close()
        
        if df.empty:
            if "Woo" in player_name:
                logger.warning(f"🔎 [DB-DEBUG] Aucun match trouvé pour {player_name} avec LIKE %{player_name}%")
            return {}
            
        # Nettoyage des IP (Innings Pitched : '5.1' = 5 + 1/3 manches)
        def parse_ip(ip_str):
            try:
                parts = str(ip_str).split('.')
                full = float(parts[0])
                frac = float(parts[1])/3.0 if len(parts) > 1 else 0.0
                return full + frac
            except:
                return 0.0
                
        df['ip_num'] = df['innings_pitched'].apply(parse_ip)
        
        total_ip = df['ip_num'].sum()
        total_k = df['strikeouts'].sum()
        
        return {
            "player": player_name,
            "games_analyzed": len(df),
            "avg_k": total_k / len(df) if len(df) > 0 else 0,
            "k_per_9": (total_k * 9) / total_ip if total_ip > 0 else 0,
            "recent_games": df.to_dict('records')
        }
    except Exception as e:
        logger.error(f"Erreur DB pitcher_stats: {e}")
        return {}


def get_team_strikeout_rate(team_abbr: str) -> float:
    """
    Estime la tendance d'une équipe à se faire strikeout (K%) en se basant
    sur les données de tous ses batteurs dans la base.
    
    Args:
        team_abbr: Abréviation de l'équipe (ex: NYY, LAD).
        
    Returns:
        Moyenne de strikeouts par match de l'équipe, ou 0.
    """
    if not os.path.exists(DB_PATH):
        return 0.0
        
    try:
        conn = sqlite3.connect(DB_PATH)
        query = """
            SELECT game_date, SUM(k) as team_strikeouts
            FROM mlb_batters
            WHERE team = ?
            GROUP BY game_date
            ORDER BY game_date DESC
            LIMIT 15
        """
        df = pd.read_sql_query(query, conn, params=(team_abbr,))
        conn.close()
        
        if df.empty:
            return 0.0
            
        return float(df['team_strikeouts'].mean())
    except Exception as e:
        logger.error(f"Erreur DB team_strikeout_rate: {e}")
        return 0.0
