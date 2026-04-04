import aiohttp
import asyncio
import json
from bs4 import BeautifulSoup
import unicodedata
import logging

logger = logging.getLogger("NHL_Bot")

# Compteur de cassure pour détection proactive
_consecutive_failures = 0
_FAILURE_ALERT_THRESHOLD = 5

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

def _parse_html_odds(html: str) -> dict | None:
    """
    Parse les cotes depuis le HTML de BettingPros (méthode actuelle éprouvée).
    Retourne le dict JSON structuré ou None si la structure a changé.

    Args:
        html: Le contenu HTML de la page BettingPros.

    Returns:
        Le dictionnaire JSON contenant les données de cotes, ou None.
    """
    soup = BeautifulSoup(html, 'html.parser')
    scripts = soup.find_all('script', type='application/json')
    
    for script in scripts:
        if script.string and '"markets"' in script.string and '"offers"' in script.string:
            try:
                temp_data = json.loads(script.string)
                if temp_data.get('offers') and temp_data.get('books'):
                    return temp_data
            except json.JSONDecodeError:
                continue
    return None

def _parse_api_json(html: str) -> dict | None:
    """
    Tente d'extraire les données depuis le __NEXT_DATA__ JSON embarqué.
    C'est la méthode la plus stable car elle utilise le store Next.js natif.

    Args:
        html: Le contenu HTML de la page BettingPros.

    Returns:
        Le dictionnaire JSON contenant les données de cotes, ou None.
    """
    soup = BeautifulSoup(html, 'html.parser')
    
    # Méthode 1 : __NEXT_DATA__ (Next.js server-side props)
    next_data_script = soup.find('script', id='__NEXT_DATA__')
    if next_data_script and next_data_script.string:
        try:
            next_data = json.loads(next_data_script.string)
            page_props = next_data.get('props', {}).get('pageProps', {})
            if page_props.get('offers') and page_props.get('books'):
                return page_props
        except (json.JSONDecodeError, AttributeError):
            pass
    
    # Méthode 2 : Tout script JSON contenant la structure attendue
    for script in soup.find_all('script'):
        if not script.string:
            continue
        text = script.string.strip()
        # Chercher des JSON embarqués dans des variables JS
        for pattern in ['"offers":', '"markets":']:
            if pattern in text:
                # Extraire le JSON le plus large possible
                for start_char in ['{', '[']:
                    idx = text.find(start_char)
                    if idx >= 0:
                        try:
                            candidate = json.loads(text[idx:])
                            if isinstance(candidate, dict) and candidate.get('offers'):
                                return candidate
                        except json.JSONDecodeError:
                            continue
    return None

def _extract_odds_from_data(data: dict) -> dict:
    """
    Extrait les cotes Buts/Assists/Points à partir du JSON structuré.
    Code commun aux deux méthodes de parsing.

    Args:
        data: Dictionnaire JSON contenant 'markets', 'offers', et 'books'.

    Returns:
        Dict avec les clés 'BUTS', 'ASSISTS', 'POINTS' (valeurs ou None).
    """
    result = {'BUTS': None, 'ASSISTS': None, 'POINTS': None}
    
    market_map = {m.get('id'): (m.get('meta', {}).get('label') or m.get('name')) for m in data.get('markets', [])}
    book_map = {b.get('id'): b.get('name') for b in data.get('books', [])}

    for offer in data.get('offers', []):
        nom_marche = market_map.get(offer.get('market_id'), "").lower()
        
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
                                    if result[cat_key] is None or cote_fr > result[cat_key]:
                                        result[cat_key] = cote_fr
                                    break
    return result

async def fetch_player_odds(session, player_name: str) -> dict:
    """
    Récupère la cote BettingPros "Consensus" Over 0.5 pour un joueur.
    Stratégie en cascade : API JSON d'abord, puis HTML parsing en fallback.

    Args:
        session: La session aiohttp partagée.
        player_name: Le nom complet du joueur.

    Returns:
        Dict avec 'player', 'BUTS', 'ASSISTS', 'POINTS'.
    """
    global _consecutive_failures
    
    slug = normalize_name_for_url(player_name)
    url = f"https://www.bettingpros.com/nhl/odds/player-props/{slug}/"
    
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
            await asyncio.sleep((attempt + 1) * 2)

    if not html:
        _consecutive_failures += 1
        return odds_data

    # Stratégie en cascade : API JSON → HTML parsing
    data = _parse_api_json(html) or _parse_html_odds(html)
    
    if not data:
        _consecutive_failures += 1
        if _consecutive_failures >= _FAILURE_ALERT_THRESHOLD:
            logger.warning(
                f"⚠️ [Odds] {_consecutive_failures} échecs consécutifs de parsing ! "
                f"La structure HTML de BettingPros a probablement changé. "
                f"Vérifier odds_scraper.py manuellement."
            )
        return odds_data

    # Reset du compteur de cassure si on réussit
    _consecutive_failures = 0
    
    extracted = _extract_odds_from_data(data)
    odds_data.update(extracted)
    return odds_data

async def fetch_multiple_odds(player_names: list) -> dict:
    """
    Point d'entrée pour récupérer en parallèle les cotes de plusieurs joueurs.
    Retourne { "Nom Joueur": {"BUTS": 2.10, "ASSISTS": 2.50, ...} }

    Args:
        player_names: Liste de noms de joueurs.

    Returns:
        Dictionnaire de cotes par joueur (seuls ceux avec au moins une cote).
    """
    global _consecutive_failures
    
    if not player_names:
        return {}
    
    # Reset du compteur au début de chaque vague
    _consecutive_failures = 0
        
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_player_odds(session, name) for name in player_names]
        results = await asyncio.gather(*tasks)
    
    # Alerte si trop de cassures dans la vague
    if _consecutive_failures >= _FAILURE_ALERT_THRESHOLD:
        logger.warning(
            f"🚨 [Odds] ALERTE CASSURE : {_consecutive_failures}/{len(player_names)} joueurs sans cote. "
            f"Le scraping BettingPros est probablement cassé."
        )
        
    # Mapping
    odds_map = {}
    for res in results:
        if res['BUTS'] or res['ASSISTS'] or res['POINTS']:
            odds_map[res['player']] = res
            
    return odds_map
