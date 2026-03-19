import pandas as pd
import re
from datetime import datetime, timedelta
import math

TEAM_MAPPING = {
    'Anaheim Ducks': 'ANA', 'Boston Bruins': 'BOS', 'Buffalo Sabres': 'BUF', 'Calgary Flames': 'CGY',
    'Carolina Hurricanes': 'CAR', 'Chicago Blackhawks': 'CHI', 'Colorado Avalanche': 'COL',
    'Columbus Blue Jackets': 'CBJ', 'Dallas Stars': 'DAL', 'Detroit Red Wings': 'DET',
    'Edmonton Oilers': 'EDM', 'Florida Panthers': 'FLA', 'Los Angeles Kings': 'LAK',
    'Minnesota Wild': 'MIN', 'Montreal Canadiens': 'MTL', 'Nashville Predators': 'NSH',
    'New Jersey Devils': 'NJD', 'New York Islanders': 'NYI', 'New York Rangers': 'NYR',
    'Ottawa Senators': 'OTT', 'Philadelphia Flyers': 'PHI', 'Pittsburgh Penguins': 'PIT',
    'San Jose Sharks': 'SJS', 'Seattle Kraken': 'SEA', 'St Louis Blues': 'STL',
    'St. Louis Blues': 'STL', 'Tampa Bay Lightning': 'TBL', 'Toronto Maple Leafs': 'TOR', 
    'Vancouver Canucks': 'VAN', 'Vegas Golden Knights': 'VGK', 'Washington Capitals': 'WSH', 
    'Winnipeg Jets': 'WPG', 'Utah Mammoth': 'UTA', 'Utah Hockey Club': 'UTA'
}

REVERSE_TEAM_MAPPING = {v: k for k, v in TEAM_MAPPING.items()}

TEAM_CLEANER = {
    'L.A': 'LAK', 'N.J': 'NJD', 'S.J': 'SJS', 'T.B': 'TBL', 'L.A.': 'LAK', 'N.J.': 'NJD', 'S.J.': 'SJS', 'T.B.': 'TBL'
}

SUPERSTARS_PLAYMAKERS = [
    "Connor McDavid", "Nathan MacKinnon", "Nikita Kucherov", "Auston Matthews", 
    "Leon Draisaitl", "Aleksander Barkov", "Sidney Crosby", "Jack Hughes", 
    "Jack Eichel", "Artemi Panarin", "David Pastrnak", "Mikko Rantanen", 
    "Kirill Kaprizov", "Mitch Marner", "Elias Pettersson", "J.T. Miller", 
    "Brayden Point", "Matthew Tkachuk", "Sebastian Aho", "Jason Robertson"
]

def clean_team_name(team_str):
    t = team_str.split(',')[0].strip()
    return TEAM_CLEANER.get(t, t)


def get_b2b_teams(match_filepath, today_str):
    try:
        import re
        from datetime import datetime, timedelta
        yesterday = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

        team_names = '|'.join(re.escape(t) for t in TEAM_MAPPING)
        pattern = re.compile(
            rf'^(\d{{4}}-\d{{2}}-\d{{2}}) - .+ ({team_names}) (?:Limited|Full) Report'
        )

        b2b_teams = set()
        with open(match_filepath, encoding='utf-8-sig') as f:
            for line in f:
                m = pattern.match(line.strip())
                if m and m.group(1) == yesterday:
                    b2b_teams.add(TEAM_MAPPING[m.group(2)])

        return list(b2b_teams)

    except Exception as e:
        print(f"[WARN] get_b2b_teams : {e}")
        return []
    
def load_goalie_stats(filepath):
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
    except:
        return {}
    
def load_v5_base_stats(filepath,oi_stats):
    try:
        v5_dict = {}
        if filepath.endswith('.csv'):
            df = pd.read_csv(filepath)
            for _, row in df.iterrows():
                player = str(row.get('Player', '')).strip()
                gp = int(row.get('GP', 0))
                goals = int(row.get('Goals', 0))
                g_gp = goals / gp if gp > 0 else 0.0 
                pos = str(row.get('Position', '')).strip()
                v5_dict[player] = {
                    'oiSH': oi_stats.get(player, {}).get('oiSH', 10.0),
                    'PDO':  oi_stats.get(player, {}).get('PDO',  100.0),
                    'GP': gp,
                    'G_GP': g_gp,
                    'Position': pos
                }
        return v5_dict
    except: return {}

def load_recent_form(filepath):
    try:
        df = pd.read_csv(filepath)
        form_dict = {}
        for _, row in df.iterrows():
            player = str(row['Player']).strip()
            team = clean_team_name(str(row.get('Team', ''))) 
            gp = max(1, int(row.get('GP', 1)))
            toi = float(row.get('TOI', 0))
            form_dict[player] = {
                'Team': team, 'L10_GP': gp,
                'L10_G_G': float(row.get('Goals', 0)) / gp,
                'L10_SOG_G': float(row.get('Shots', 0)) / gp,
                'L10_TOI': toi,
                'L10_ixG_G': float(row.get('ixG', 0)) / gp,
                'L10_iSCF_G':  float(row.get('iSCF', 0)) / gp,
                'L10_iHDCF_G': float(row.get('iHDCF', 0)) / gp,
                'ATOI': toi / gp 
            }
        return form_dict
    except Exception as e:
        print(f"[WARN] load_recent_form : {e}")
        return {}

def load_matchup_data(filepath):
    try:
        with open(filepath, encoding='utf-8-sig') as f:
            content = f.read()

        idx = content.find('Team')
        if idx == -1:
            return {}
        lines = content[idx:].strip().split('\n')

        raw_headers = lines[0].split()
        headers = []
        i = 0
        while i < len(raw_headers):
            if raw_headers[i] == 'Point' and i + 1 < len(raw_headers) and raw_headers[i+1] == '%':
                headers.append('Point%')
                i += 2
            else:
                headers.append(raw_headers[i])
                i += 1
        NB_STATS = len(headers) - 1  

        matchup_dict = {}
        for line in lines[1:]:
            parts = line.split()
            if not parts or not parts[0].isdigit():
                continue

            team_name = None
            team_word_count = 0
            for name in TEAM_MAPPING:
                words = name.split()
                candidate = ' '.join(parts[1:1 + len(words)])
                if candidate == name:
                    team_name = name
                    team_word_count = len(words)
                    break
            if not team_name:
                continue

            stats_part = parts[1 + team_word_count:]
            if len(stats_part) < NB_STATS:
                continue

            row = dict(zip(headers[1:], stats_part[:NB_STATS]))
            team_abbr = TEAM_MAPPING[team_name]
            gp = max(1, int(row.get('GP', 1)))

            matchup_dict[team_abbr] = {
                'GA_G':     float(row.get('GA',    0))    / gp,
                'SA_G':     float(row.get('SA',    0))    / gp,
                'CA_G':     float(row.get('CA',    0))    / gp,
                'CF_pct':   float(row.get('CF%',   50.0)),
                'HDCA_G':   float(row.get('HDCA',  0))    / gp,
                'HDCF_pct': float(row.get('HDCF%', 50.0)),
                'PK%':      float(row.get('PK%',   80.0)),
            }
        return matchup_dict

    except Exception as e:
        print(f"[WARN] load_matchup_data : {e}")
        return {}

def load_powerplay_stats(filepath):
    try:
        df = pd.read_csv(filepath)
        pp_dict = {}
        for _, row in df.iterrows():
            player = str(row['Player']).strip()
            gp = max(1, int(row.get('GP', 1)))
            toi = float(row.get('TOI', 0))
            pp_dict[player] = toi / gp 
        return pp_dict
    except: return {}
def load_on_ice_stats(filepath):
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
        print(f"[WARN] load_on_ice_stats : {e}")
        return {}
def load_pk_stats(filepath):
    """
    Charge le PK% depuis le tableau 4v5 NST (sit=4v5).
    La colonne utile est SV% (= taux d'arrêt en infériorité = PK%).
    """
    try:
        with open(filepath, encoding='utf-8-sig') as f:
            content = f.read()
        idx = content.find('Team')
        if idx == -1:
            print("[WARN] load_pk_stats : header 'Team' introuvable")
            return {}
        lines = content[idx:].strip().split('\n')
        headers = lines[0].split()
        sv_from_end  = -2   
        pdo_from_end = -1   
        sv_idx = None  

        pk_dict = {}
        for line in lines[1:]:
            parts = line.split()
            if not parts or not parts[0].isdigit():
                continue
            team_name = None
            team_word_count = 0
            for name in TEAM_MAPPING:
                words = name.split()
                candidate = ' '.join(parts[1:1 + len(words)])
                if candidate == name:
                    team_name = name
                    team_word_count = len(words)
                    break
            if not team_name:
                continue
            stats_part = parts[1 + team_word_count:]
            if len(stats_part) < 2:
                continue
            try:
                sv_pct = float(stats_part[-2])   
                if sv_pct < 2.0:
                    sv_pct *= 100
                pk_dict[TEAM_MAPPING[team_name]] = round(sv_pct, 1)
            except ValueError:
                continue

        if pk_dict:
            print(f"[OK] load_pk_stats : {len(pk_dict)} équipes chargées")
        else:
            print("[WARN] load_pk_stats : aucune équipe parsée")
        return pk_dict

    except Exception as e:
        print(f"[WARN] load_pk_stats : {e}")
        return {}


def get_auto_pp1_players(form_data, pp_stats, teams_playing):
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

def check_if_backup_goalie(goalie_name, goalie_stats):
    """
    Backup si GP du gardien < 25% des GP du titulaire de son équipe.
    Ex: Woll 29 GP, Murray 37 GP → Woll = 78% → titulaire
    Ex: backup 8 GP, Woll 29 GP  → backup = 28% → backup
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

def parse_flashscore_file(filepath, known_players, form_data=None):
    """
    form_data optionnel : si fourni, filtre les joueurs dont l'équipe NST
    ne correspond à aucune équipe du match (évite les faux positifs de matching).
    """
    matches = []
    compos_by_team = {}  
    goalies = {}
    
    def get_real_name(scraped_name, team_context=None):
        """
        Résout un nom Flashscore ('Kreider C.') vers le nom complet NST ('Chris Kreider').
        team_context : abbr de l'équipe du match (DOM ou EXT) pour filtrer les candidats.
        """
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
        print(f"[WARN] parse_flashscore_file : {e}")

    all_compos = set()
    for players in compos_by_team.values():
        all_compos.update(players)
        
    return matches, list(all_compos), goalies


def calculate_base_qs(v5_stats, p_form, opp_stats, is_pp1, is_home, has_star_linemate, is_backup=False, is_b2b=False):
    g_gp = v5_stats.get('G_GP', 0.0) or 0.0
    pos  = str(v5_stats.get('Position', '')).strip()
    if g_gp < 0.18: return -99.0
    if pos in ('D', 'LD', 'RD'): return -99.0

    qs = 3.5

    oish     = v5_stats.get('oiSH', 10.0)
    pdo      = v5_stats.get('PDO', 100.0)
    hdcf     = p_form.get('L10_iHDCF_G', 0.0)
    scf      = p_form.get('L10_iSCF_G', 0.0)
    l10_g    = p_form.get('L10_G_G', 0.0)
    season_g = v5_stats.get('G_GP', 0.0)
    ixg      = p_form.get('L10_ixG_G', 0.0)
    atoi     = p_form.get('ATOI', 0.0)
    
    _opp   = opp_stats or {}
    cf_pct = _opp.get('CF_pct', 50.0)
    pk_pct = _opp.get('PK%',    80.0)
    ga_g   = _opp.get('GA_G',    2.7)
    sa_g   = _opp.get('SA_G',   28.0)
    hdca_g   = _opp.get('HDCA_G', 8.0)
    hdcf_pct = _opp.get('HDCF_pct', 50.0)
    
    sog = p_form.get('L10_SOG_G', 0.0)

    if oish > 16.0: qs -= 2.0
    elif oish > 14.0: qs -= 1.0
    if is_b2b: qs -= 1.5

    g1 = 0.0
    ixg_bonus = (3.0 if ixg >= 0.55 else
                 2.0 if ixg >= 0.40 else
                 1.0 if ixg >= 0.28 else
                -1.5 if ixg <= 0.12 else 0.0)
    goals_bonus = min(1.0, l10_g * 2.5)
    g1 += max(ixg_bonus, goals_bonus)
    if sog >= 3.0: g1 += 1.0
    if hdcf >= 1.5: g1 += 1.5
    elif hdcf >= 1.0: g1 += 0.75
    if scf >= 4.0: g1 += 0.5
    qs += min(g1, 4.0)

    g2 = 0.0
    if ga_g >= 3.00:   g2 += 2.0
    elif ga_g >= 2.80: g2 += 1.0
    elif ga_g < 2.50:  g2 -= 0.25  
    if cf_pct >= 54.0:   g2 -= 0.75  
    elif cf_pct >= 52.0: g2 -= 0.25  
    elif cf_pct <= 46.0: g2 += 1.5
    elif cf_pct <= 48.0: g2 += 0.5
    if hdca_g >= 12.0:   g2 += 1.5
    elif hdca_g >= 10.0: g2 += 0.75
    elif hdca_g <= 6.0:  g2 -= 0.75
    if hdcf_pct <= 46.0: g2 += 0.5
    if sa_g >= 30.0 and sog >= 2.5: g2 += 0.75
    qs += min(g2, 4.0)

    g3 = 0.0
    if atoi >= 20.0: g3 += 2.0
    elif atoi >= 17.0: g3 += 1.0  
    if pdo < 96.0: g3 += 1.5
    elif pdo < 98.0: g3 += 0.75
    if season_g > 0:
        ratio = l10_g / season_g
        if ratio >= 2.0:   g3 += 1.5
        elif ratio >= 1.5: g3 += 1.0
        elif ratio <= 0.3: g3 -= 2.0
        elif ratio <= 0.5: g3 -= 1.0
    if is_home: g3 += 0.5
    if has_star_linemate: g3 += 0.5
    qs += min(g3, 4.0)

    if is_pp1:
        if pk_pct < 77.0: qs += 2.5
        elif pk_pct > 83.0: qs += 1.0
        else: qs += 1.75

    if is_backup: qs += 2.0


    qs_normalized = 2 + 10 * (1 / (1 + math.exp(-0.45 * (qs - 9.5))))

    return qs_normalized