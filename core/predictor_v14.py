import pandas as pd
import re
from datetime import datetime, timedelta
import math
import os
import threading
import logging
import joblib
import numpy as np
import xgboost as xgb
from typing import Dict, List, Any, Optional, Set, Tuple

# Ajout du dossier racine au sys.path pour permettre l'exécution standalone
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import loaders
from core.loaders import (
    TEAM_MAPPING, REVERSE_TEAM_MAPPING, TEAM_CLEANER, 
    clean_team_name, get_b2b_teams, load_goalie_stats, 
    load_v5_base_stats, load_recent_form, load_matchup_data_mp, 
    load_powerplay_stats, load_on_ice_stats, load_pk_stats
)

logger = logging.getLogger("NHL_Bot")

SUPERSTARS_PLAYMAKERS = [
    "Connor McDavid", "Nathan MacKinnon", "Nikita Kucherov", "Auston Matthews", 
    "Leon Draisaitl", "Aleksander Barkov", "Sidney Crosby", "Jack Hughes", 
    "Jack Eichel", "Artemi Panarin", "David Pastrnak", "Mikko Rantanen", 
    "Kirill Kaprizov", "Mitch Marner", "Elias Pettersson", "J.T. Miller", 
    "Brayden Point", "Matthew Tkachuk", "Sebastian Aho", "Jason Robertson"
]

def get_auto_pp1_players(form_data: Dict[str, Dict[str, Any]], pp_stats: Dict[str, float], teams_playing: List[str]) -> List[str]:
    """
    Identifies potential PP1 players for a list of teams based on their average PP TOI.

    Args:
        form_data: Dictionary of player recent form stats.
        pp_stats: Dictionary of player PP TOI stats.
        teams_playing: List of team abbreviations playing in the current session.

    Returns:
        A list of player names identified as top 5 PP TOI for their teams.
    """
    pp1_list = []
    for team in teams_playing:
        team_players = []
        for player, stats in form_data.items():
            if stats['Team'] == team:
                team_players.append((player, pp_stats.get(player, 0.0)))
        team_players.sort(key=lambda x: x[1], reverse=True)
        top_5 = [p[0] for p in team_players[:5] if p[1] > 0]
        pp1_list.extend(top_5)
    return pp1_list

def check_if_backup_goalie(goalie_name: str, goalie_stats: Dict[str, Dict[str, Any]]) -> bool:
    """
    Determines if a goalie is a backup based on games played ratio within their team.

    Args:
        goalie_name: Name of the goalie to check.
        goalie_stats: Dictionary of all goalie stats.

    Returns:
        True if the goalie is considered a backup, False otherwise.
    """
    g = goalie_stats.get(goalie_name)
    if not g or g['GP'] == 0:
        return False
    team = g.get('Team', '')
    if not team:
        return False
    team_gps = [v['GP'] for v in goalie_stats.values()
                if v.get('Team') == team and v['GP'] > 0]
    if not team_gps:
        return False
    ratio = g['GP'] / max(team_gps)
    return ratio < 0.25

def parse_flashscore_file(filepath: str, known_players: List[str], form_data: Optional[Dict[str, Dict[str, Any]]] = None) -> Tuple[List[Tuple[str, str]], List[str], Dict[str, str]]:
    """
    Parses a Flashscore scraped file to extract matches, lineups, and starting goalies.

    Args:
        filepath: Path to the flashscore output file.
        known_players: List of all player names known by the API.
        form_data: Optional player form data for better team-based matching.

    Returns:
        A tuple containing:
        - List of matches as (home_team, away_team)
        - List of all players identified in lineups
        - Dictionary of starting goalies per team
    """
    matches = []
    compos_by_team = {}  
    goalies = {}

    def get_real_name(scraped_name: str, team_context: Optional[str] = None) -> str:
        """Resolves a scraped name to its full API name using fuzzy matching and team context."""
        s_name = scraped_name.strip()
        if not s_name: return ""

        s_clean = re.sub(r'\s+(II|III|IV|Jr|Sr)\.?$', '', s_name, flags=re.IGNORECASE).strip()
        parts = s_clean.split(' ')
        if len(parts) < 2: return s_name

        last_name = " ".join(parts[:-1]).replace(',', '').strip().lower()
        first_init = parts[-1][0].lower()

        candidates = []
        for k_name in known_players:
            k_parts = k_name.split(' ')
            k_first = k_parts[0].lower()
            k_last = " ".join(k_parts[1:]).lower()

            if last_name in k_last and k_first.startswith(first_init):
                exact = (last_name == k_last)

                team_match = 0
                if team_context and form_data:
                    p_team = form_data.get(k_name, {}).get('Team', '')
                    team_match = 2 if p_team == team_context else 0

                score = (2 if exact else 1) + team_match
                candidates.append((k_name, score))

        if not candidates: return s_name
        candidates.sort(key=lambda x: x[1], reverse=True)

        best_name, best_score = candidates[0]
        if len(candidates) > 1:
            k_last_best = " ".join(best_name.split()[1:]).lower()
            if last_name != k_last_best:
                return s_name  

        return best_name

    current_dom = ""
    current_ext = ""

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith("Match :"):
                    m = re.search(r"Match :\s*(.*?)\s*-\s*(.*?)\s*\(", line)
                    if m:
                        current_dom = TEAM_MAPPING.get(m.group(1).strip(), m.group(1).strip())
                        current_ext = TEAM_MAPPING.get(m.group(2).strip(), m.group(2).strip())
                        matches.append((current_dom, current_ext))
                        compos_by_team.setdefault(current_dom, set())
                        compos_by_team.setdefault(current_ext, set())
                elif line.startswith("goal dom:"):
                    g_name = line.replace("goal dom:", "").strip()
                    goalies[current_dom] = get_real_name(g_name, current_dom)
                elif line.startswith("goal ext:"):
                    g_name = line.replace("goal ext:", "").strip()
                    goalies[current_ext] = get_real_name(g_name, current_ext)
                elif line.startswith("f1 dom") or line.startswith("f2 dom"):
                    players_str = line.split(":", 1)[1]
                    for p in players_str.split(','):
                        real_p = get_real_name(p.strip(), current_dom)
                        if real_p: compos_by_team[current_dom].add(real_p)
                elif line.startswith("f1 ext") or line.startswith("f2 ext"):
                    players_str = line.split(":", 1)[1]
                    for p in players_str.split(','):
                        real_p = get_real_name(p.strip(), current_ext)
                        if real_p: compos_by_team[current_ext].add(real_p)
                elif line.startswith("f1") or line.startswith("f2"):
                    players_str = line.split(":", 1)[1]
                    for p in players_str.split(','):
                        real_p = get_real_name(p.strip())
                        if real_p:
                            compos_by_team.setdefault(current_dom, set()).add(real_p)
    except Exception as e:
        logger.warning(f"parse_flashscore_file error: {e}")

    all_compos = set()
    for players in compos_by_team.values():
        all_compos.update(players)

    return matches, list(all_compos), goalies

def calculate_base_qs(v5_stats: Dict[str, Any], p_form: Dict[str, Any], opp_stats: Dict[str, float], 
                      is_pp1: bool, is_home: bool, has_star_linemate: bool, 
                      is_backup: bool = False, is_b2b: bool = False) -> float:
    """
    Calculates a Quality Score (QS) for a player based on stats and context.
    
    QS v14.1 — Master Edition (XGBoost logic converted to heuristic for transparency).
    """
    g_gp = v5_stats.get('G_GP', 0.0) or 0.0
    pos  = str(v5_stats.get('Position', '')).strip()
    if g_gp < 0.18 and pos not in ('D', 'LD', 'RD'): 
        return -99.0

    qs = 3.5

    oish     = v5_stats.get('oiSH', 10.0)
    pdo      = v5_stats.get('PDO', 100.0)
    season_g = v5_stats.get('G_GP', 0.0)
    gp       = v5_stats.get('GP', 0)

    ixg    = p_form.get('L10_ixG_G',   p_form.get('I_F_xGoals', 0.0))
    hdcf   = p_form.get('L10_iHDCF_G', p_form.get('I_F_highDangerShots', 0.0))
    sog    = p_form.get('L10_SOG_G',   p_form.get('I_F_shotsOnGoal', 0.0))
    atoi   = p_form.get('ATOI',        p_form.get('icetime', 0.0) / 60.0)
    consec = p_form.get('ConsecGoals', 0)

    _opp   = opp_stats or {}
    pk_pct = _opp.get('PK%',    80.0)
    ga_g   = _opp.get('GA_G',    2.7)
    hdca_g = _opp.get('HDCA_G',  8.0)

    if gp >= 20:
        if oish > 16.0:   qs -= 2.0
        elif oish > 14.0: qs -= 1.0
    elif gp >= 10:
        if oish > 16.0:   qs -= 1.0
        elif oish > 14.0: qs -= 0.5
    if is_b2b: qs -= 1.5

    g1 = 0.0
    ixg_score = (4.0 if ixg >= 0.55 else
                 3.0 if ixg >= 0.45 else
                 2.5 if ixg >= 0.38 else
                 1.5 if ixg >= 0.30 else
                 0.5 if ixg >= 0.22 else
                -1.0)
    g1 += ixg_score

    if hdcf >= 3.0:   g1 += 2.5
    elif hdcf >= 2.5: g1 += 1.5
    elif hdcf >= 2.0: g1 += 0.75
    elif hdcf >= 1.5: g1 += 0.5
    else:             g1 -= 0.5

    if sog >= 3.5:   g1 += 1.0
    elif sog >= 2.5: g1 += 0.5

    qs += min(g1, 5.0)

    g2 = 0.0
    if ga_g >= 3.00:   g2 += 2.5
    elif ga_g >= 2.80: g2 += 1.5
    elif ga_g >= 2.50: g2 += 0.5
    elif ga_g < 2.30:  g2 -= 0.5

    if pk_pct < 77.0:   g2 += 1.0
    elif pk_pct < 80.0: g2 += 0.5
    elif pk_pct > 85.0: g2 -= 0.5

    if hdca_g >= 12.0:   g2 += 0.75
    elif hdca_g >= 10.0: g2 += 0.375
    elif hdca_g <= 5.0:  g2 -= 0.5

    qs += min(g2, 3.5)

    g3 = 0.0
    if atoi >= 20.0:   g3 += 1.5
    elif atoi >= 18.0: g3 += 0.75

    if pdo < 96.0:    g3 += 2.0
    elif pdo < 98.0:  g3 += 1.0
    elif pdo > 103.0: g3 -= 1.0
    elif pdo > 100.0: g3 -= 0.5

    if season_g >= 0.35:   g3 += 0.5                        
    elif season_g >= 0.25: g3 += 0.25

    qs += min(g3, 3.0)

    if is_pp1:
        if pk_pct < 77.0:   qs += 2.5
        elif pk_pct > 83.0: qs += 0.5
        else:               qs += 1.75

    if is_backup and ga_g >= 2.8:
        qs += 2.0
    elif is_backup:
        qs += 0.75

    qs_normalized = 2 + 10 * (1 / (1 + math.exp(-0.45 * (qs - 6.5))))

    if consec >= 3:
        qs_normalized += 0.5
    elif consec == 2:
        qs_normalized += 0.3

    return qs_normalized

def calculate_assist_qs(v5_stats: Dict[str, Any], p_form: Dict[str, Any], opp_stats: Dict[str, float], 
                        is_pp1: bool, is_home: bool, has_star_linemate: bool, 
                        is_backup: bool = False, is_b2b: bool = False) -> float:
    """
    Calculates a Quality Score (QS) for a player to get an assist.
    Focuses on playmaking abilities, linemates, and Power Play time.
    """
    a_gp = v5_stats.get('A_GP', 0.0) or 0.0
    if a_gp < 0.35: # Base threshold for playmakers
        return -99.0

    qs = 4.0

    oish     = v5_stats.get('oiSH', 10.0)
    pdo      = v5_stats.get('PDO', 100.0)
    gp       = v5_stats.get('GP', 0)
    
    l10_a    = p_form.get('L10_A_G', 0.0)
    atoi     = p_form.get('ATOI', 0.0)
    
    _opp     = opp_stats or {}
    ga_g     = _opp.get('GA_G', 2.7)

    # Assists depend on teammates scoring
    if has_star_linemate:
        qs *= 1.2 # Multiplier as per plan

    # Recent form
    if l10_a >= 0.8:   qs += 3.0
    elif l10_a >= 0.6: qs += 2.0
    elif l10_a >= 0.4: qs += 1.0

    # Opportunity
    if atoi >= 20.0:   qs += 2.0
    elif atoi >= 18.0: qs += 1.0
    
    if is_pp1:
        qs += 2.5 # Critical for assists

    # Matchup
    if ga_g >= 3.2:   qs += 1.5
    elif ga_g >= 2.8: qs += 0.75

    # Regression / Luck
    if pdo < 98.0: qs += 1.0
    elif pdo > 103.0: qs -= 1.0

    # Normalize (Sigmoid)
    qs_normalized = 2 + 10 * (1 / (1 + math.exp(-0.4 * (qs - 7.0))))
    return qs_normalized

def calculate_points_qs(v5_stats: Dict[str, Any], p_form: Dict[str, Any], opp_stats: Dict[str, float], 
                        is_pp1: bool, is_home: bool, has_star_linemate: bool, 
                        is_backup: bool = False, is_b2b: bool = False) -> float:
    """
    Calculates a Quality Score (QS) for a player to get at least 1 point (Goal or Assist).
    Hybrid score favoring consistency.
    """
    pts_gp = v5_stats.get('Pts_GP', 0.0) or 0.0
    if pts_gp < 0.55: # Base threshold for point producers
        return -99.0

    qs_but = calculate_base_qs(v5_stats, p_form, opp_stats, is_pp1, is_home, has_star_linemate, is_backup, is_b2b)
    qs_ast = calculate_assist_qs(v5_stats, p_form, opp_stats, is_pp1, is_home, has_star_linemate, is_backup, is_b2b)
    
    # Combined score
    qs = (qs_but * 0.4) + (qs_ast * 0.6)
    
    # Bonus for consistency
    l10_pts = p_form.get('L10_Pts_G', 0.0)
    if l10_pts >= 1.0: qs += 0.5
    
    return qs

_xgb_lock = threading.Lock()
_xgb_prod_model = None

def get_xgb_prod_model() -> Optional[Dict[str, Any]]:
    """Lazy loads the production XGBoost model for goal prediction (thread-safe)."""
    global _xgb_prod_model
    if _xgb_prod_model is None:
        with _xgb_lock:
            if _xgb_prod_model is None:
                try:
                    model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'models', 'prod_model_v5.pkl')
                    if os.path.exists(model_path):
                        _xgb_prod_model = joblib.load(model_path)
                    else:
                        logger.error(f"XGBoost model file not found at {model_path}")
                except Exception as e:
                    logger.error(f"Error loading XGBoost model: {e}")
                    return None
    return _xgb_prod_model

def evaluate_xgb_proba(v5_stats: Dict[str, Any], p_form: Dict[str, Any], opp_stats: Dict[str, float], 
                       is_home: bool, is_b2b: bool, opp_is_b2b: bool, is_pp1: bool, qs_v10: float) -> float:
    """Predicts goal probability using the production XGBoost model."""
    model_data = get_xgb_prod_model()
    if not model_data or 'model' not in model_data:
        return 0.50 

    ixg    = p_form.get('L10_ixG_G', 0.0)
    hdcf   = p_form.get('L10_iHDCF_G', 0.0)
    sog    = p_form.get('L10_SOG_G', 0.0)
    atoi   = p_form.get('ATOI', 0.0)
    season_g = v5_stats.get('G_GP', 0.0)
    consec = p_form.get('ConsecGoals', 0)
    goals_10 = p_form.get('L10_G_G', 0.0) * p_form.get('L10_GP', 1)

    _opp   = opp_stats or {}
    ga_g   = _opp.get('GA_G', 2.7)
    hdca_g = _opp.get('HDCA_G', 8.0)

    ixg_unnorm = ixg * p_form.get('L10_GP', 1)
    luck_factor = goals_10 / max(ixg_unnorm, 0.01) if ixg_unnorm > 0 else 1.0
    ixg_x_hdcf = ixg * hdcf
    sog_x_atoi = sog * atoi
    ixg_x_ga = ixg * ga_g
    streak_x_ixg = consec * ixg

    X = np.array([[
        ixg, hdcf, sog, atoi, season_g,
        ga_g, hdca_g, int(is_pp1), int(is_home), int(is_b2b), int(opp_is_b2b),
        consec, qs_v10,
        luck_factor, ixg_x_hdcf, sog_x_atoi, ixg_x_ga, streak_x_ixg
    ]])

    m = model_data['model']
    proba = m.predict_proba(X)[0][1]
    return float(proba)

def calculate_sog_score(p_form: Dict[str, Any], opp_stats: Dict[str, float], is_pp1: bool, is_home: bool) -> float:
    """Calculates a heuristic score for SOG >= 3 prediction."""
    sog  = p_form.get('L10_SOG_G', 0.0)
    atoi = p_form.get('ATOI', 0.0)
    ixg  = p_form.get('L10_ixG_G', 0.0)
    hdcf = p_form.get('L10_iHDCF_G', 0.0)

    _opp = opp_stats or {}
    sa_g = _opp.get('SA_G', 30.0)

    score = 0.0
    if sog >= 4.0:   score += 4.0
    elif sog >= 3.5: score += 3.0
    elif sog >= 3.0: score += 2.0
    elif sog >= 2.5: score += 1.0
    elif sog >= 2.0: score += 0.5
    else:            score -= 1.0

    if atoi >= 20.0:   score += 2.0
    elif atoi >= 18.0: score += 1.0
    elif atoi >= 16.0: score += 0.5

    if ixg >= 0.50:   score += 1.5
    elif ixg >= 0.35: score += 1.0
    elif ixg >= 0.25: score += 0.5

    if hdcf >= 2.5: score += 1.0
    elif hdcf >= 2.0: score += 0.5

    if is_pp1: score += 1.5
    if is_home: score += 0.25

    if sa_g >= 32.0:   score += 1.0
    elif sa_g >= 30.0: score += 0.5

    return score

_sog_lock = threading.Lock()
_sog_model = None

def get_sog_model() -> Optional[Dict[str, Any]]:
    """Lazy loads the SOG prediction XGBoost model (thread-safe)."""
    global _sog_model
    if _sog_model is None:
        with _sog_lock:
            if _sog_model is None:
                try:
                    model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'models', 'sog_model_v1.pkl')
                    if os.path.exists(model_path):
                        _sog_model = joblib.load(model_path)
                    else:
                        logger.error(f"SOG model file not found at {model_path}")
                except Exception as e:
                    logger.error(f"Error loading SOG model: {e}")
                    return None
    return _sog_model

def evaluate_sog_proba(p_form: Dict[str, Any], opp_stats: Dict[str, float], is_pp1: bool, is_home: bool, sog_score: float) -> float:
    """Predicts SOG >= 3 probability using the SOG XGBoost model."""
    model_data = get_sog_model()
    if not model_data or 'model' not in model_data:
        return 0.50

    sog  = p_form.get('L10_SOG_G', 0.0)
    atoi = p_form.get('ATOI', 0.0)
    ixg  = p_form.get('L10_ixG_G', 0.0)
    hdcf = p_form.get('L10_iHDCF_G', 0.0)
    season_g = p_form.get('L10_G_G', 0.0)

    _opp = opp_stats or {}
    sa_g = _opp.get('SA_G', 30.0)

    X = np.array([[
        sog, atoi, ixg, hdcf, season_g,
        sa_g, int(is_pp1), int(is_home),
        sog * atoi,
        sog_score,
    ]])

    m = model_data['model']
    proba = m.predict_proba(X)[0][1]
    return float(proba)
