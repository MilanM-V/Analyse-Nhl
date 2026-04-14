import re
import math
import logging
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger("NHL_Bot")

SUPERSTARS_PLAYMAKERS = [
    "Connor McDavid", "Nathan MacKinnon", "Nikita Kucherov", "Auston Matthews", 
    "Leon Draisaitl", "Aleksander Barkov", "Sidney Crosby", "Jack Hughes", 
    "Jack Eichel", "Artemi Panarin", "David Pastrnak", "Mikko Rantanen", 
    "Kirill Kaprizov", "Mitch Marner", "Elias Pettersson", "J.T. Miller", 
    "Brayden Point", "Matthew Tkachuk", "Sebastian Aho", "Jason Robertson"
]

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

def parse_flashscore_file(filepath: str, known_players: List[str], form_data: Optional[Dict[str, Dict[str, Any]]] = None) -> Tuple[List[Tuple[str, str]], List[str], Dict[str, str]]:
    """Parses a Flashscore scraped file to extract matches, lineups, and starting goalies."""
    from core.loaders import TEAM_MAPPING
    matches = []
    compos_by_team = {}  
    goalies = {}

    def get_real_name(scraped_name: str, team_context: Optional[str] = None) -> str:
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


# ==============================================================================
# ARCHITECTURE ORIENTÉE OBJET (OOP) DES SCORERS - v17.1
# ==============================================================================

class BaseMarketScorer:
    """Classe abstraite centralisant l'extraction et la préparation des données pour les scorers."""
    
    def __init__(self, v5_stats: Dict[str, Any], p_form: Dict[str, Any], opp_stats: Dict[str, float], 
                 is_pp1: bool, is_home: bool, has_star_linemate: bool, 
                 is_backup: bool = False, is_b2b: bool = False):
        self.v5_stats = v5_stats or {}
        self.p_form = p_form or {}
        self.opp_stats = opp_stats or {}
        
        self.is_pp1 = is_pp1
        self.is_home = is_home
        self.has_star_linemate = has_star_linemate
        self.is_backup = is_backup
        self.is_b2b = is_b2b

        # Extraction des métriques communes du joueur
        self.oish = self.v5_stats.get('oiSH', 10.0)
        self.pdo = self.v5_stats.get('PDO', 100.0)
        self.gp = self.v5_stats.get('GP', 0)
        self.pos = str(self.v5_stats.get('Position', '')).strip()

        # Forme récente
        self.ixg = self.p_form.get('L10_ixG_G', self.p_form.get('I_F_xGoals', 0.0))
        self.hdcf = self.p_form.get('L10_iHDCF_G', self.p_form.get('I_F_highDangerShots', 0.0))
        self.sog = self.p_form.get('L10_SOG_G', self.p_form.get('I_F_shotsOnGoal', 0.0))
        self.atoi = self.p_form.get('ATOI', self.p_form.get('icetime', 0.0) / 60.0)
        
        # Statistiques de l'adversaire
        self.pk_pct = self.opp_stats.get('PK%', 80.0)
        self.ga_g = self.opp_stats.get('GA_G', 2.7)
        self.hdca_g = self.opp_stats.get('HDCA_G', 8.0)
        self.sa_g = self.opp_stats.get('SA_G', 30.0)

    def calculate_qs(self) -> float:
        raise NotImplementedError("Subclasses must implement calculate_qs()")


class GoalScorer(BaseMarketScorer):
    """Scorer dédié au marché des Buteurs."""
    
    def calculate_qs(self) -> float:
        season_g = self.v5_stats.get('G_GP', 0.0) or 0.0
        consec = self.p_form.get('ConsecGoals', 0)

        if season_g < 0.18 and self.pos not in ('D', 'LD', 'RD'): 
            return -99.0

        qs = 3.5

        # Pénalités PDO/OI_SH (Régression probable)
        if self.gp >= 20:
            if self.oish > 16.0:   qs -= 2.0
            elif self.oish > 14.0: qs -= 1.0
        elif self.gp >= 10:
            if self.oish > 16.0:   qs -= 1.0
            elif self.oish > 14.0: qs -= 0.5
        
        if self.is_b2b: 
            qs -= 1.5

        # Bloc 1 : Métriques offensives du joueur
        g1 = 0.0
        ixg_score = (4.0 if self.ixg >= 0.55 else
                     3.0 if self.ixg >= 0.45 else
                     2.5 if self.ixg >= 0.38 else
                     1.5 if self.ixg >= 0.30 else
                     0.5 if self.ixg >= 0.22 else
                    -1.0)
        g1 += ixg_score

        if self.hdcf >= 3.0:   g1 += 2.5
        elif self.hdcf >= 2.5: g1 += 1.5
        elif self.hdcf >= 2.0: g1 += 0.75
        elif self.hdcf >= 1.5: g1 += 0.5
        else:                  g1 -= 0.5

        if self.sog >= 3.5:   g1 += 1.0
        elif self.sog >= 2.5: g1 += 0.5

        qs += min(g1, 5.0)

        # Bloc 2 : Vulnérabilités de l'adversaire
        g2 = 0.0
        if self.ga_g >= 3.00:   g2 += 2.5
        elif self.ga_g >= 2.80: g2 += 1.5
        elif self.ga_g >= 2.50: g2 += 0.5
        elif self.ga_g < 2.30:  g2 -= 0.5

        if self.pk_pct < 77.0:   g2 += 1.0
        elif self.pk_pct < 80.0: g2 += 0.5
        elif self.pk_pct > 85.0: g2 -= 0.5

        if self.hdca_g >= 12.0:   g2 += 0.75
        elif self.hdca_g >= 10.0: g2 += 0.375
        elif self.hdca_g <= 5.0:  g2 -= 0.5

        qs += min(g2, 3.5)

        # Bloc 3 : Opportunités et temps de glace
        g3 = 0.0
        if self.atoi >= 20.0:   g3 += 1.5
        elif self.atoi >= 18.0: g3 += 0.75

        # Bonus de progression (Chance en notre faveur)
        if self.pdo < 96.0:    g3 += 2.0
        elif self.pdo < 98.0:  g3 += 1.0
        elif self.pdo > 103.0: g3 -= 1.0
        elif self.pdo > 100.0: g3 -= 0.5

        if season_g >= 0.35:   g3 += 0.5                        
        elif season_g >= 0.25: g3 += 0.25

        qs += min(g3, 3.0)

        # Avantages contextuels
        if self.is_pp1:
            if self.pk_pct < 77.0:   qs += 2.5
            elif self.pk_pct > 83.0: qs += 0.5
            else:                    qs += 1.75

        if self.is_backup and self.ga_g >= 2.8:
            qs += 2.0
        elif self.is_backup:
            qs += 0.75

        # Normalisation Sigmoid
        qs_normalized = 2 + 10 * (1 / (1 + math.exp(-0.45 * (qs - 6.5))))

        if consec >= 3:
            qs_normalized += 0.5
        elif consec == 2:
            qs_normalized += 0.3

        return qs_normalized


class AssistScorer(BaseMarketScorer):
    """Scorer dédié au marché des Passeurs."""
    
    def calculate_qs(self) -> float:
        a_gp = self.v5_stats.get('A_GP', 0.0) or 0.0
        if a_gp < 0.35: 
            return -99.0

        qs = 4.0
        l10_a = self.p_form.get('L10_A_G', 0.0)

        if self.has_star_linemate:
            qs *= 1.2

        if l10_a >= 0.8:   qs += 3.0
        elif l10_a >= 0.6: qs += 2.0
        elif l10_a >= 0.4: qs += 1.0

        if self.atoi >= 20.0:   qs += 2.0
        elif self.atoi >= 18.0: qs += 1.0
        
        if self.is_pp1:
            qs += 2.5 

        if self.ga_g >= 3.2:   qs += 1.5
        elif self.ga_g >= 2.8: qs += 0.75

        if self.pdo < 98.0: qs += 1.0
        elif self.pdo > 103.0: qs -= 1.0

        qs_normalized = 2 + 10 * (1 / (1 + math.exp(-0.4 * (qs - 7.0))))
        return qs_normalized


class PointScorer(BaseMarketScorer):
    """Scorer dédié au marché des Pointeurs (Hybride)."""
    
    def calculate_qs(self) -> float:
        pts_gp = self.v5_stats.get('Pts_GP', 0.0) or 0.0
        if pts_gp < 0.55: 
            return -99.0

        qs_but = GoalScorer(self.v5_stats, self.p_form, self.opp_stats, self.is_pp1, self.is_home, self.has_star_linemate, self.is_backup, self.is_b2b).calculate_qs()
        qs_ast = AssistScorer(self.v5_stats, self.p_form, self.opp_stats, self.is_pp1, self.is_home, self.has_star_linemate, self.is_backup, self.is_b2b).calculate_qs()
        
        qs = (qs_but * 0.4) + (qs_ast * 0.6)
        
        l10_pts = self.p_form.get('L10_Pts_G', 0.0)
        if l10_pts >= 1.0: 
            qs += 0.5
        
        return qs


class SogScorer(BaseMarketScorer):
    """Scorer dédié au marché des Tirs (SOG)."""
    
    def calculate_qs(self) -> float:
        score = 0.0
        
        if self.sog >= 4.0:   score += 4.0
        elif self.sog >= 3.5: score += 3.0
        elif self.sog >= 3.0: score += 2.0
        elif self.sog >= 2.5: score += 1.0
        elif self.sog >= 2.0: score += 0.5
        else:                 score -= 1.0

        if self.atoi >= 20.0:   score += 2.0
        elif self.atoi >= 18.0: score += 1.0
        elif self.atoi >= 16.0: score += 0.5

        if self.ixg >= 0.50:   score += 1.5
        elif self.ixg >= 0.35: score += 1.0
        elif self.ixg >= 0.25: score += 0.5

        if self.hdcf >= 2.5: score += 1.0
        elif self.hdcf >= 2.0: score += 0.5

        if self.is_pp1: score += 1.5
        if self.is_home: score += 0.25

        if self.sa_g >= 32.0:   score += 1.0
        elif self.sa_g >= 30.0: score += 0.5

        return score


# ==============================================================================
# FAÇADES POUR LA COMPATIBILITÉ RÉTROACTIVE AVEC bot_logic.py
# ==============================================================================

def calculate_base_qs(v5_stats: Dict[str, Any], p_form: Dict[str, Any], opp_stats: Dict[str, float], 
                      is_pp1: bool, is_home: bool, has_star_linemate: bool, 
                      is_backup: bool = False, is_b2b: bool = False) -> float:
    scorer = GoalScorer(v5_stats, p_form, opp_stats, is_pp1, is_home, has_star_linemate, is_backup, is_b2b)
    return scorer.calculate_qs()

def calculate_assist_qs(v5_stats: Dict[str, Any], p_form: Dict[str, Any], opp_stats: Dict[str, float], 
                        is_pp1: bool, is_home: bool, has_star_linemate: bool, 
                        is_backup: bool = False, is_b2b: bool = False) -> float:
    scorer = AssistScorer(v5_stats, p_form, opp_stats, is_pp1, is_home, has_star_linemate, is_backup, is_b2b)
    return scorer.calculate_qs()

def calculate_points_qs(v5_stats: Dict[str, Any], p_form: Dict[str, Any], opp_stats: Dict[str, float], 
                        is_pp1: bool, is_home: bool, has_star_linemate: bool, 
                        is_backup: bool = False, is_b2b: bool = False) -> float:
    scorer = PointScorer(v5_stats, p_form, opp_stats, is_pp1, is_home, has_star_linemate, is_backup, is_b2b)
    return scorer.calculate_qs()

def calculate_sog_score(p_form: Dict[str, Any], opp_stats: Dict[str, float], is_pp1: bool, is_home: bool) -> float:
    scorer = SogScorer({}, p_form, opp_stats, is_pp1, is_home, False, False, False)
    return scorer.calculate_qs()
