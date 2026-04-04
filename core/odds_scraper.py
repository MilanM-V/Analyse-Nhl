import aiohttp
import asyncio
import json
from bs4 import BeautifulSoup
import unicodedata
import logging

logger = logging.getLogger("NHL_Bot")

def normalize_name_for_url(name: str) -> str:
    """
    Slugifier pour convertir 'M. Bunting' ou 'Tim Stützle'
    en 'm-bunting', 'tim-stutzle' pour les URLs BettingPros.
    """
    if not name: return ""
    # Décompose les caractères accentués
    normalized = unicodedata.normalize('NFD', name)
    str_no_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    
    # Remplacements divers
    str_no_accents = str_no_accents.lower().replace(".", "").replace("'", "")
    str_slug = str_no_accents.strip().replace(" ", "-")
    return str_slug

def american_to_decimal(cote):
    """Convertit une cote américaine en décimale."""
    try:
        cote = int(cote)
        if cote > 0:
            return round((cote / 100) + 1, 2)
        else:
            return round((100 / abs(cote)) + 1, 2)
    except:
        return 1.85 # Par défaut arbitraire si erreur absolue

async def fetch_player_odds(session, player_name: str) -> dict:
    """
    Récupère la cote BettingPros "Consensus" Over 0.5 pour un joueur.
    Retourne un dict avec 'Buts', 'Assists', 'Points'.
    """
    slug = normalize_name_for_url(player_name)
    url = f"https://www.bettingpros.com/nhl/odds/player-props/{slug}/"
    
    # Valeur par défaut
    odds_data = {
        'player': player_name,
        'BUTS': None,
        'ASSISTS': None,
        'POINTS': None
    }
    
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0'
    ]
    
    html = None
    for attempt in range(3):
        headers = {'User-Agent': user_agents[attempt % len(user_agents)]}
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    html = await response.text()
                    break
                elif response.status in (403, 429):
                    logger.debug(f"[Odds] {player_name} ({slug}) : Anti-bot bloquant (HTTP {response.status}). Essai {attempt+1}/3...")
                else:
                    logger.debug(f"[Odds] {player_name} : Erreur HTTP {response.status}")
                    
        except Exception as e:
            logger.debug(f"[Odds] {player_name} : Timeout ou erreur de connexion ({e}). Essai {attempt+1}/3...")

        if attempt < 2:
            await asyncio.sleep((attempt + 1) * 2)  # Backoff: 2s, 4s

    if not html:
        return odds_data

    soup = BeautifulSoup(html, 'html.parser')
    scripts = soup.find_all('script', type='application/json')
    
    data = None
    # Pour s'assurer de décoder sans crasher
    for script in scripts:
        if script.string and '"markets"' in script.string and '"offers"' in script.string:
            try:
                temp_data = json.loads(script.string)
                if temp_data.get('offers') and temp_data.get('books'):
                    data = temp_data
                    break
            except json.JSONDecodeError:
                continue

    if not data:
        return odds_data

    # Map les marchés et bookmakers
    market_map = {m.get('id'): (m.get('meta', {}).get('label') or m.get('name')) for m in data.get('markets', [])}
    book_map = {b.get('id'): b.get('name') for b in data.get('books', [])}

    for offer in data.get('offers', []):
        nom_marche = market_map.get(offer.get('market_id'), "").lower()
        
        # Identifier la catégorie du marché
        cat_key = None
        if "goalie" not in nom_marche:
            if "goal" in nom_marche:
                cat_key = "BUTS"
            elif "assist" in nom_marche:
                cat_key = "ASSISTS"
            elif "point" in nom_marche:
                cat_key = "POINTS"
        
        if cat_key:
            for selection in offer.get('selections', []):
                if selection.get('label') == "Over":
                    for b_data in selection.get('books', []):
                        if book_map.get(b_data.get('id')) == "BettingPros Consensus":
                            for line_info in b_data.get('lines', []):
                                if line_info.get('line') == 0.5:
                                    cote_fr = american_to_decimal(line_info.get('cost'))
                                    # Garder la meilleure cote s'il y a des doublons de marché
                                    if odds_data[cat_key] is None or cote_fr > odds_data[cat_key]:
                                        odds_data[cat_key] = cote_fr
                                    break
    return odds_data

async def fetch_multiple_odds(player_names: list) -> dict:
    """
    Point d'entrée pour récupérer en parallèle les cotes de plusieurs joueurs.
    Retourne { "Nom Joueur": {"BUTS": 2.10, "ASSISTS": 2.50, ...} }
    """
    if not player_names:
        return {}
        
    async with aiohttp.ClientSession() as session:
        # Lancement parallèle
        tasks = [fetch_player_odds(session, name) for name in player_names]
        results = await asyncio.gather(*tasks)
        
    # Mapping
    odds_map = {}
    for res in results:
        # S'il a au moins une cote
        if res['BUTS'] or res['ASSISTS'] or res['POINTS']:
            odds_map[res['player']] = res
            
    return odds_map
