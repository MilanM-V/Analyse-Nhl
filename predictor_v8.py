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
            'L10_ixG_G': float(row.get('ixG', 0)) / gp,
            'L10_iSCF_G':  float(row.get('iSCF', 0)) / gp,
            'L10_iHDCF_G': float(row.get('iHDCF', 0)) / gp,
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
                'CA_G':  float(row.get('CA', 0)) / gp,   
                'CF_pct': float(row.get('CF%', 50.0)),
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
    if season_gp == 0: return False
    games_pct = l10_gp / min(season_gp, 10)  # Part des 10 derniers matchs joués
    return games_pct < 0.3 and season_gp < 40

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

    # --- Stats joueur ---
    oish     = v5_stats.get('oiSH', 10.0)
    pdo      = v5_stats.get('PDO', 100.0)
    g_gp     = v5_stats.get('G_GP', 0.20)
    hdcf     = p_form.get('L10_iHDCF_G', 0.0)
    scf      = p_form.get('L10_iSCF_G', 0.0)
    l10_g    = p_form.get('L10_G_G', 0.0)
    season_g = v5_stats.get('G_GP', 0.0)
    ixg      = p_form.get('L10_ixG_G', 0.0)
    atoi     = p_form.get('ATOI', 0.0)

    # --- Stats adversaire : extraites UNE SEULE FOIS avec valeurs par défaut
    # opp_stats peut être None si l'équipe est absente de team.csv (ex: Utah)
    _opp   = opp_stats or {}
    cf_pct = _opp.get('CF_pct', 50.0)
    pk_pct = _opp.get('PK%',    80.0)
    ga_g   = _opp.get('GA_G',    2.7)
    sa_g   = _opp.get('SA_G',   28.0)

    # --- Filtres éliminatoires ---
    if g_gp < 0.18: return -99.0
    pos = str(v5_stats.get('Position', '')).strip()
    if pos in ('D', 'LD', 'RD'): return -99.0

    # --- oiSH% : pénalité progressive ---
    if oish > 16.0: qs -= 2.0
    elif oish > 14.0: qs -= 1.0

    # --- Qualité des tirs (iHDCF, iSCF) ---
    if hdcf >= 1.5:  qs += 2.0
    elif hdcf >= 1.0: qs += 1.0
    if scf >= 4.0: qs += 1.0

    # --- Matchup défensif (CF% adverse) ---
    if cf_pct >= 54.0:   qs -= 1.5
    elif cf_pct >= 52.0: qs -= 0.5
    elif cf_pct <= 46.0: qs += 1.5
    elif cf_pct <= 48.0: qs += 0.5

    # --- PDO (chance en cours de saison) ---
    if pdo < 96.0: qs += 2.0
    elif pdo < 98.0: qs += 1.0

    # --- Contexte ---
    if is_home: qs += 0.5
    if has_star_linemate: qs += 0.5

    # --- PP1 dynamique ---
    if is_pp1:
        if pk_pct < 77.0: qs += 3.0
        elif pk_pct > 83.0: qs += 1.0
        else: qs += 2.0

    # --- Streak : ratio L10 / saison ---
    if season_g > 0:
        ratio = l10_g / season_g
        if ratio >= 2.0:   qs += 2.5
        elif ratio >= 1.5: qs += 1.5
        elif ratio <= 0.3: qs -= 2.0
        elif ratio <= 0.5: qs -= 1.0

    # --- Ice time ---
    if atoi >= 18.5: qs += 3.0
    elif atoi >= 17.0: qs += 1.0

    # --- ixG (qualité des chances créées) ---
    if ixg >= 0.55:   qs += 3.0
    elif ixg >= 0.40: qs += 2.0
    elif ixg >= 0.28: qs += 1.0
    elif ixg <= 0.12: qs -= 1.5
    ixg_bonus = 3.0 if ixg >= 0.55 else (2.0 if ixg >= 0.40 else (1.0 if ixg >= 0.28 else (-1.5 if ixg <= 0.12 else 0)))
    goals_bonus = min(1.0, l10_g * 2.5)  # Bonus continu au lieu de paliers brusques
    qs += max(ixg_bonus, goals_bonus)
    # --- Volume de tirs & buts récents ---
    if p_form.get('L10_SOG_G', 0.0) >= 3.0: qs += 1.5
    if l10_g >= 0.4:   qs += 1.0
    elif l10_g <= 0.05: qs -= 0.5

    # --- Défense adverse (GA/G, volume de tirs) ---
    if ga_g >= 3.00:   qs += 2.5
    elif ga_g >= 2.80: qs += 1.0
    elif ga_g < 2.50:  qs -= 0.5

    if sa_g >= 30.0 and p_form.get('L10_SOG_G', 0.0) >= 2.5:
        qs += 1.0

    return qs
