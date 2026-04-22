"""
config/constants.py — Source unique de vérité pour le mapping d'équipes NHL.

Toutes les autres modules doivent importer depuis ici.
Ne JAMAIS dupliquer ces mappings ailleurs dans le projet.
"""

from typing import Dict, Set

# ─── Mapping principal : Nom complet → Abréviation ───────────────────────────
TEAM_FULL_TO_ABBR: Dict[str, str] = {
    'Anaheim Ducks': 'ANA',
    'Boston Bruins': 'BOS',
    'Buffalo Sabres': 'BUF',
    'Calgary Flames': 'CGY',
    'Carolina Hurricanes': 'CAR',
    'Chicago Blackhawks': 'CHI',
    'Colorado Avalanche': 'COL',
    'Columbus Blue Jackets': 'CBJ',
    'Dallas Stars': 'DAL',
    'Detroit Red Wings': 'DET',
    'Edmonton Oilers': 'EDM',
    'Florida Panthers': 'FLA',
    'Los Angeles Kings': 'LAK',
    'Minnesota Wild': 'MIN',
    'Montreal Canadiens': 'MTL',
    'Nashville Predators': 'NSH',
    'New Jersey Devils': 'NJD',
    'New York Islanders': 'NYI',
    'New York Rangers': 'NYR',
    'Ottawa Senators': 'OTT',
    'Philadelphia Flyers': 'PHI',
    'Pittsburgh Penguins': 'PIT',
    'San Jose Sharks': 'SJS',
    'Seattle Kraken': 'SEA',
    'St. Louis Blues': 'STL',
    'St Louis Blues': 'STL',
    'Tampa Bay Lightning': 'TBL',
    'Toronto Maple Leafs': 'TOR',
    'Vancouver Canucks': 'VAN',
    'Vegas Golden Knights': 'VGK',
    'Washington Capitals': 'WSH',
    'Winnipeg Jets': 'WPG',
    'Utah Hockey Club': 'UTA',
    'Utah Mammoth': 'UTA',
}

# ─── Vues dérivées (calculées automatiquement) ───────────────────────────────

# Abréviation → Nom complet (exclut les alias comme "St Louis Blues", "Utah Mammoth")
_ALIAS_FULL_NAMES = {'St Louis Blues', 'Utah Mammoth'}
TEAM_ABBR_TO_FULL: Dict[str, str] = {
    v: k for k, v in TEAM_FULL_TO_ABBR.items()
    if k not in _ALIAS_FULL_NAMES
}

# Ensemble de toutes les abréviations valides
ALL_ABBRS: Set[str] = set(TEAM_FULL_TO_ABBR.values())

# ─── Nettoyage des abréviations courtes (Flashscore / CSV) ──────────────────
TEAM_CLEANER: Dict[str, str] = {
    'L.A': 'LAK', 'N.J': 'NJD', 'S.J': 'SJS', 'T.B': 'TBL',
    'L.A.': 'LAK', 'N.J.': 'NJD', 'S.J.': 'SJS', 'T.B.': 'TBL',
}
