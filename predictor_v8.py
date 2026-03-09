"""
Live Predictor NHL V8.6 - Masterclass Edition
- Scrapping Flashscore & Traduction des noms
- Filtre Anti-Défenseurs Blindé (Position != 'D')
- NOUVEAU: Bonus Domicile (Home/Away Splits)
- NOUVEAU: PP1 Dynamique selon le Penalty Kill (PK%) adverse
- NOUVEAU: Synergie Linemates (Bonus si Star active)
- FIX: Nettoyage automatique des abréviations d'équipes bizarres (L.A, N.J, S.J)
"""
import pandas as pd
import re
from datetime import datetime, timedelta

# ==========================================
# 1. CONFIGURATION ET MAPPINGS
# ==========================================
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

# Dictionnaire de nettoyage pour les fichiers Natural Stat Trick
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
    """ Nettoie les noms d'équipes bizarres (ex: 'L.A' -> 'LAK') ou les trades ('L.A, CHI' -> 'LAK') """
    t = team_str.split(',')[0].strip()
    return TEAM_CLEANER.get(t, t)

# ==========================================
# 2. CHARGEMENT DES FICHIERS CSV
# ==========================================
def get_b2b_teams(match_filepath, today_str):
    try:
        df = pd.read_csv(match_filepath)
        df['Date'] = df['Game'].str.extract(r'(\d{4}-\d{2}-\d{2})')
        target_date = datetime.strptime(today_str, "%Y-%m-%d")
        yesterday_str = (target_date - timedelta(days=1)).strftime("%Y-%m-%d")
        b2b_teams = []
        for team in df[df['Date'] == yesterday_str]['Team']:
            team_full = team.strip()
            if team_full in TEAM_MAPPING: b2b_teams.append(TEAM_MAPPING[team_full])
        return list(set(b2b_teams))
    except: return []

def load_v5_base_stats(filepath):
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
                    'oiSH': float(row.get('On-Ice SH%', 10.0)),
                    'PDO': float(row.get('PDO', 100.0)),
                    'GP': gp,
                    'G_GP': g_gp,
                    'Position': pos
                }
        return v5_dict
    except: return {}

def load_recent_form(filepath):
    df = pd.read_csv(filepath)
    form_dict = {}
    for _, row in df.iterrows():
        player = str(row['Player']).strip()
        team = clean_team_name(str(row.get('Team', ''))) # 🛠️ UTILISATION DU CLEANER
        gp = max(1, int(row.get('GP', 1)))
        toi = float(row.get('TOI', 0))
        form_dict[player] = {
            'Team': team, 'L10_GP': gp,
            'L10_G_G': float(row.get('Goals', 0)) / gp,
            'L10_SOG_G': float(row.get('Shots', 0)) / gp,
            'L10_TOI': toi,
            'ATOI': toi / gp 
        }
    return form_dict

def load_matchup_data(filepath):
    df = pd.read_csv(filepath)
    matchup_dict = {}
    for _, row in df.iterrows():
        team_full = str(row.get('Team', '')).strip()
        if team_full in TEAM_MAPPING:
            team_abbr = TEAM_MAPPING[team_full]
            gp = max(1, int(row.get('GP', 1)))
            pk_pct = float(row.get('PK%', 80.0)) 
            
            matchup_dict[team_abbr] = {
                'GA_G': float(row.get('GA', 0)) / gp,
                'SA_G': float(row.get('SA', 0)) / gp,
                'PK%': pk_pct
            }
    return matchup_dict

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

def check_if_backup_goalie(goalie_name, v5_stats, form_dict):
    if not goalie_name: return False
    g_form, g_season = form_dict.get(goalie_name), v5_stats.get(goalie_name)
    if not g_form and not g_season: return False
    l10_gp = g_form.get('L10_GP', 0) if g_form else 0
    season_gp = g_season.get('GP', 0) if g_season else 0
    return l10_gp < 4 and season_gp < 35

def parse_flashscore_file(filepath, known_players):
    matches = []
    compos = set()
    goalies = {}
    
    def get_real_name(scraped_name):
        s_name = scraped_name.strip()
        if not s_name: return ""
        parts = s_name.split(' ')
        if len(parts) >= 2:
            last_name = " ".join(parts[:-1]).replace(',', '').strip()
            first_init = parts[-1][0].lower() 
            for k_name in known_players:
                k_parts = k_name.split(' ')
                k_first = k_parts[0]
                k_last = " ".join(k_parts[1:])
                if last_name.lower() in k_last.lower() and k_first.lower().startswith(first_init):
                    return k_name
        return s_name

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
                elif line.startswith("goal dom:"):
                    g_name = line.replace("goal dom:", "").strip()
                    goalies[current_dom] = get_real_name(g_name)
                elif line.startswith("goal ext:"):
                    g_name = line.replace("goal ext:", "").strip()
                    goalies[current_ext] = get_real_name(g_name)
                elif line.startswith("f1") or line.startswith("f2"):
                    players_str = line.split(":", 1)[1]
                    for p in players_str.split(','):
                        real_p = get_real_name(p.strip())
                        if real_p: compos.add(real_p)
    except:
        pass
        
    return matches, list(compos), goalies

# ==========================================
# 4. LE CERVEAU DE CALCUL MASTERCLASS
# ==========================================
def calculate_base_qs(v5_stats, p_form, opp_stats, is_pp1, is_home, has_star_linemate):
    qs = 3.5 
    
    oish = v5_stats.get('oiSH', 10.0)
    pdo = v5_stats.get('PDO', 100.0)
    g_gp = v5_stats.get('G_GP', 0.20) 
    
    if g_gp < 0.18: return -99.0 
    pos = str(v5_stats.get('Position', '')).strip()
    if pos == 'D' or 'D' in pos: return -99.0 
    if oish > 14.0: return -99.0 
    
    if pdo < 96.0: qs += 2.0  
    elif pdo < 98.0: qs += 1.0 
        
    if is_home: qs += 0.5
    if has_star_linemate: qs += 0.5

    if is_pp1:
        pk_pct = opp_stats.get('PK%', 80.0) if opp_stats else 80.0
        if pk_pct < 77.0: qs += 3.0 
        elif pk_pct > 83.0: qs += 1.0 
        else: qs += 2.0 
        
    atoi = p_form['ATOI']
    if atoi >= 18.5: qs += 3.0 
    elif atoi >= 17.0: qs += 1.0
    
    if p_form['L10_SOG_G'] >= 3.0: qs += 2
    if p_form['L10_G_G'] >= 0.4: qs += 2.5
    elif p_form['L10_G_G'] <= 0.05: qs -= 1.5
            
    if opp_stats:
        ga_g = opp_stats['GA_G']
        if ga_g >= 3.00: qs += 2.5 
        elif ga_g >= 2.80: qs += 1.0 
        elif ga_g < 2.50: qs -= 0.5 
            
        if opp_stats['SA_G'] >= 30.0 and p_form['L10_SOG_G'] >= 2.5: 
            qs += 1.0 

    return qs
