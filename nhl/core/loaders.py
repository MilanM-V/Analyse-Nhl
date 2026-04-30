import pandas as pd
import re
import logging
import os
import sys

# Ajout du dossier racine au sys.path pour permettre l'exécution standalone
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set, Tuple

logger = logging.getLogger("NHL.Loaders")

# Imports centralisés depuis la source unique (config/constants.py)
from config.constants import (
    TEAM_FULL_TO_ABBR as TEAM_MAPPING,
    TEAM_ABBR_TO_FULL as REVERSE_TEAM_MAPPING,
    TEAM_CLEANER,
)

def clean_team_name(team_str: str) -> str:
    """
    Cleans a team name string to its standard abbreviation.

    Args:
        team_str: The team name or abbreviation string.

    Returns:
        The cleaned team abbreviation.
    """
    t = team_str.split(',')[0].strip()
    cleaned = TEAM_CLEANER.get(t, t)
    return TEAM_MAPPING.get(cleaned, cleaned)

def load_goalie_stats(filepath: str) -> Dict[str, Dict[str, Any]]:
    """
    Loads goalie statistics from a CSV file.

    Args:
        filepath: Path to the goalies CSV file.

    Returns:
        A dictionary mapping player names to their stats.
    """
    try:
        df = pd.read_csv(filepath)
        g_dict = {}
        for _, row in df.iterrows():
            player = str(row.get('Player', '')).strip()
            if not player or player.lower() == 'nan':
                continue
            team = clean_team_name(str(row.get('Team', '')).strip())
            g_dict[player] = {
                'GP':   int(row.get('GP', 0)),
                'Team': team,
            }
        return g_dict
    except Exception as e:
        logger.warning(f"load_goalie_stats error: {e}")
        return {}

def load_on_ice_stats(filepath: str) -> Dict[str, Dict[str, float]]:
    """
    Loads on-ice statistics (PDO, oiSH%) from a CSV file.

    Args:
        filepath: Path to the on_ice CSV file.

    Returns:
        A dictionary mapping player names to their on-ice stats.
    """
    try:
        df = pd.read_csv(filepath)
        oi_dict = {}
        for _, row in df.iterrows():
            player = str(row.get('Player', '')).strip()
            if not player or player.lower() == 'nan':
                continue
            def safe_float(val, default):
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return default

            pdo_raw = safe_float(row.get('PDO', 1.0), 1.0)
            pdo = pdo_raw * 100 if pdo_raw < 2.0 else pdo_raw
            oish_raw = safe_float(row.get('On-Ice SH%', 10.0), 10.0)
            oish = oish_raw * 100 if oish_raw < 1.0 else oish_raw
            oi_dict[player] = {
                'oiSH': oish,
                'PDO':  pdo,
            }
        return oi_dict
    except Exception as e:
        logger.warning(f"load_on_ice_stats error: {e}")
        return {}

def load_v5_base_stats(filepath: str, oi_stats: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, Any]]:
    """
    Loads season base statistics for players.

    Args:
        filepath: Path to the Player Season Totals CSV file.
        oi_stats: Dictionary of on-ice stats to merge.

    Returns:
        A dictionary mapping player names to their season stats.
    """
    try:
        v5_dict = {}
        if filepath.endswith('.csv'):
            df = pd.read_csv(filepath)
            for _, row in df.iterrows():
                player = str(row.get('Player', '')).strip()
                gp = int(row.get('GP', 0))
                goals = int(row.get('Goals', 0))
                assists = int(row.get('Assists', 0))
                points = int(row.get('Points', 0))
                g_gp = goals / gp if gp > 0 else 0.0 
                a_gp = assists / gp if gp > 0 else 0.0
                pts_gp = points / gp if gp > 0 else 0.0
                pos = str(row.get('Position', '')).strip()
                v5_dict[player] = {
                    'oiSH': oi_stats.get(player, {}).get('oiSH', 10.0),
                    'PDO':  oi_stats.get(player, {}).get('PDO',  100.0),
                    'GP': gp,
                    'G_GP': g_gp,
                    'A_GP': a_gp,
                    'Pts_GP': pts_gp,
                    'Position': pos
                }
        return v5_dict
    except Exception as e:
        logger.warning(f"load_v5_base_stats error: {e}")
        return {}

def load_recent_form(filepath: str) -> Dict[str, Dict[str, Any]]:
    """
    Loads recent form (last 10 games) statistics for players.

    Args:
        filepath: Path to the last 10 games CSV file.

    Returns:
        A dictionary mapping player names to their recent form stats.
    """
    try:
        df = pd.read_csv(filepath)
        form_dict = {}
        for _, row in df.iterrows():
            player = str(row['Player']).strip()
            team = clean_team_name(str(row.get('Team', ''))) 
            gp = max(1, int(row.get('GP', 1)))
            toi = float(row.get('TOI', 0))
            consec_goals = int(row.get('ConsecGoals', 0))
            form_dict[player] = {
                'Team': team, 'L10_GP': gp,
                'L10_G_G': float(row.get('Goals', 0)) / gp,
                'L10_A_G': float(row.get('Assists', 0)) / gp,
                'L10_Pts_G': float(row.get('Points', 0)) / gp,
                'L10_SOG_G': float(row.get('Shots', 0)) / gp,
                'L10_TOI': toi,
                'L10_ixG_G': float(row.get('ixG', 0)) / gp,
                'L10_iSCF_G':  float(row.get('iSCF', 0)) / gp,
                'L10_iHDCF_G':    float(row.get('iHDCF', 0)) / gp,
                'L10_Rebounds_G': float(row.get('Rebounds', 0)) / gp,
                'L10_Rush_G':     float(row.get('RushShots', 0)) / gp,
                'ATOI': toi / gp,
                'ConsecGoals': consec_goals
            }
        return form_dict
    except Exception as e:
        logger.warning(f"load_recent_form error: {e}")
        return {}

def load_matchup_data_mp(filepath: str) -> Dict[str, Dict[str, float]]:
    """
    Loads team matchup data from MoneyPuck CSV.

    Args:
        filepath: Path to the team CSV file.

    Returns:
        A dictionary mapping team abbreviations to their defensive/possession stats.
    """
    try:
        df = pd.read_csv(filepath, encoding='utf-8-sig')
        matchup_dict = {}
        for _, row in df.iterrows():
            team_full = str(row.get('Team', '')).strip()
            team_abbr = clean_team_name(team_full)
            gp = max(1, int(row.get('GP', 1)))
            matchup_dict[team_abbr] = {
                'GA_G':     float(row.get('GA', 0)) / gp,
                'SA_G':     float(row.get('SA', 0)) / gp,
                'CA_G':     float(row.get('CA', 0)) / gp,
                'CF_pct':   float(row.get('CF%', 50.0)),
                'HDCA_G':   float(row.get('HDCA', 0)) / gp,
                'HDCF_pct': float(row.get('HDCF%', 50.0)),
                'PK%':      float(row.get('PK%', 80.0)),
            }
        if not matchup_dict:
            logger.warning(f"load_matchup_data_mp : no team parsed from {filepath}")
        return matchup_dict
    except Exception as e:
        logger.warning(f"load_matchup_data_mp error: {e}")
        return {}

def load_powerplay_stats(filepath: str) -> Dict[str, float]:
    """
    Loads average powerplay time on ice per game for players.

    Args:
        filepath: Path to the power play CSV file.

    Returns:
        A dictionary mapping player names to their average PP TOI.
    """
    try:
        df = pd.read_csv(filepath)
        pp_dict = {}
        for _, row in df.iterrows():
            player = str(row['Player']).strip()
            gp = max(1, int(row.get('GP', 1)))
            toi = float(row.get('TOI', 0))
            pp_dict[player] = toi / gp 
        return pp_dict
    except Exception as e:
        logger.warning(f"load_powerplay_stats error: {e}")
        return {}

def load_pk_stats(filepath: str) -> Dict[str, float]:
    """
    Loads Penalty Kill percentage for teams.

    Args:
        filepath: Path to the pk CSV file.

    Returns:
        A dictionary mapping team abbreviations to their PK%.
    """
    try:
        df = pd.read_csv(filepath)
        pk_dict = {}
        for _, row in df.iterrows():
            name = str(row.get('Team', '')).strip()
            team_abbr = clean_team_name(name)
            if team_abbr:
                val = float(row.get('PK%', 80.0))
                if val < 2.0: val *= 100
                pk_dict[team_abbr] = round(val, 1)
        return pk_dict
    except Exception as e:
        logger.warning(f"load_pk_stats error: {e}")
        return {}

def get_auto_pp1_players(form_data: Dict[str, Dict[str, Any]], pp_stats: Dict[str, float], teams_playing: List[str]) -> List[str]:
    """Identifies potential PP1 players for a list of teams based on their average PP TOI."""
    pp1_list = []
    for team in teams_playing:
        team_players = []
        for player, stats in form_data.items():
            if stats.get('Team') == team:
                team_players.append((player, pp_stats.get(player, 0.0)))
        team_players.sort(key=lambda x: x[1], reverse=True)
        top_5 = [p[0] for p in team_players[:5] if p[1] > 0]
        pp1_list.extend(top_5)
    return pp1_list

def check_if_backup_goalie(goalie_name: str, goalie_stats: Dict[str, Dict[str, Any]]) -> bool:
    """Determines if a goalie is a backup based on games played ratio within their team."""
    g = goalie_stats.get(goalie_name)
    if not g or g.get('GP', 0) == 0:
        return False
    team = g.get('Team', '')
    if not team:
        return False
    team_gps = [v.get('GP', 0) for v in goalie_stats.values()
                if v.get('Team') == team and v.get('GP', 0) > 0]
    if not team_gps:
        return False
    ratio = g['GP'] / max(team_gps)
    return ratio < 0.25



def get_b2b_teams(match_filepath: str, today_str: str) -> List[str]:
    """
    Identifies teams playing the second half of a back-to-back.

    Args:
        match_filepath: Path to the file containing match history/schedules.
        today_str: Current date string in YYYY-MM-DD format.

    Returns:
        A list of team abbreviations playing in B2B.
    """
    try:
        yesterday = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        team_names = '|'.join(re.escape(t) for t in TEAM_MAPPING)
        pattern = re.compile(
            rf'^(\d{4}-\d{2}-\d{2}) - .+ ({team_names}) (?:Limited|Full) Report'
        )

        b2b_teams = set()
        if os.path.exists(match_filepath):
            with open(match_filepath, encoding='utf-8-sig') as f:
                for line in f:
                    m = pattern.match(line.strip())
                    if m and m.group(1) == yesterday:
                        b2b_teams.add(TEAM_MAPPING[m.group(2)])
        return list(b2b_teams)
    except Exception as e:
        logger.warning(f"get_b2b_teams error: {e}")
        return []
