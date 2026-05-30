"""
shared/odds_api.py — Scraper centralisé pour The Odds API.

Gère les requêtes pour la NHL et la MLB de manière asynchrone, 
tout en surveillant le quota global mensuel (limite 500 requêtes).
"""

import os
import aiohttp
import asyncio
import logging
from typing import Dict, List, Any
from dotenv import load_dotenv

from shared.telegram_hub import send_telegram

load_dotenv()

logger = logging.getLogger("OddsAPI")

ODDS_API_KEY = os.getenv("api_odds")
BASE_URL = "https://api.the-odds-api.com/v4/sports"

class OddsAPIClient:
    """Client centralisé pour The Odds API avec gestion de quota."""
    
    _quota_alert_sent = False
    
    @classmethod
    def check_quota(cls, headers: dict) -> None:
        """Vérifie l'en-tête x-requests-remaining et alerte si le quota est faible."""
        remaining = headers.get("x-requests-remaining")
        if remaining is None:
            return
            
        try:
            remaining = int(remaining)
            logger.info(f"[OddsAPI] Crédits restants : {remaining}")
            
            # Alerte si on passe sous les 50 crédits (et qu'on ne l'a pas encore envoyée)
            if remaining < 50 and not cls._quota_alert_sent:
                logger.warning(f"⚠️ QUOTA THE ODDS API CRITIQUE : {remaining} restants !")
                send_telegram(f"⚠️ <b>ALERTE THE ODDS API</b>\n\nIl ne te reste que <b>{remaining} requêtes</b> pour ce mois-ci sur ton compte The Odds API ! Le bot risque de s'arrêter bientôt.")
                cls._quota_alert_sent = True
                
        except ValueError:
            pass

    @classmethod
    async def fetch_odds(cls, sport: str, market: str, players_map: Dict[str, str], bookmaker: str = "winamax") -> Dict[str, Dict[str, float]]:
        """
        Récupère les cotes pour une liste de joueurs sur un marché donné.
        
        Args:
            sport: Clé du sport (ex: 'icehockey_nhl', 'baseball_mlb').
            market: Le marché ciblé (ex: 'player_assists', 'pitcher_strikeouts').
            players_map: Dictionnaire {nom_joueur: equipe_du_joueur}.
            bookmaker: Le bookmaker principal ciblé (par défaut winamax).
            
        Returns:
            Dict { "Nom_Joueur": { "MARCHE_OVER": cote } }
        """
        if not ODDS_API_KEY or ODDS_API_KEY == "votre_cle_api_ici":
            logger.warning(f"Clé The Odds API manquante. Impossible de récupérer les cotes {sport}.")
            return {}

        results = {}
        
        async with aiohttp.ClientSession() as session:
            # 1. Récupérer la liste des matchs (events) du jour
            events_url = f"{BASE_URL}/{sport}/events"
            params = {"apiKey": ODDS_API_KEY}
            
            try:
                async with session.get(events_url, params=params) as resp:
                    cls.check_quota(resp.headers)
                    if resp.status != 200:
                        logger.error(f"Erreur Events API [{resp.status}]: {await resp.text()}")
                        return {}
                    events_data = await resp.json()
            except Exception as e:
                logger.error(f"Erreur connexion The Odds API (Events): {e}")
                return {}

            # Filtrer les events pour ne cibler que ceux où jouent nos joueurs
            # players_map contient {joueur: equipe}
            target_teams = set(players_map.values())
            target_events = []
            for ev in events_data:
                home = ev.get('home_team', '')
                away = ev.get('away_team', '')
                
                # Checking partial overlap to accommodate different team names
                is_target = False
                for team in target_teams:
                    if team.lower() in home.lower() or team.lower() in away.lower() or home.lower() in team.lower() or away.lower() in team.lower():
                        is_target = True
                        break
                        
                if is_target:
                    target_events.append(ev['id'])
                    
            if not target_events:
                logger.warning(f"Aucun match correspondant trouvé dans l'API The Odds pour {target_teams}")
                return {}

            # 2. Récupérer les cotes pour chaque event ciblé
            logger.info(f"Appel Odds API sur {len(target_events)} matchs ciblés pour {len(players_map)} joueurs.")
            
            # Line Shopping : on cherche la meilleure cote parmi ces bookmakers (ARJEL + Internationaux)
            target_bookmakers = {
                "winamax": "Winamax", 
                "unibet_fr": "Unibet", 
                "betclic": "Betclic", 
                "parions_sport": "ParionsSport",
                "pinnacle": "Pinnacle",
                "williamhill": "William Hill",
                "888sport": "888Sport",
                "betfair_ex_eu": "Betfair",
                "coolbet": "Coolbet",
                "bwin": "Bwin",
                "marathonbet": "MarathonBet",
                "draftkings": "DraftKings",
                "fanduel": "FanDuel",
                "betmgm": "BetMGM",
                "caesars": "Caesars",
                "betrivers": "BetRivers"
            }
            
            for event_id in target_events:
                odds_url = f"{BASE_URL}/{sport}/events/{event_id}/odds"
                odds_params = {
                    "apiKey": ODDS_API_KEY,
                    "regions": "eu,us",
                    "markets": market,
                    "oddsFormat": "decimal"
                }
                
                try:
                    async with session.get(odds_url, params=odds_params) as resp:
                        cls.check_quota(resp.headers)
                        if resp.status == 422:
                            # Marché non disponible pour cet event, on l'ignore
                            continue
                        elif resp.status != 200:
                            logger.error(f"Erreur Odds API event {event_id} [{resp.status}]")
                            continue
                            
                        event_odds = await resp.json()
                        bookmakers = event_odds.get('bookmakers', [])
                        
                        # Parsing des bookmakers
                        for bm in bookmakers:
                            bm_key = bm['key']
                            if bm_key not in target_bookmakers:
                                continue # On ignore les bookmakers exotiques/étrangers
                                
                            bm_name = target_bookmakers[bm_key]
                            
                            for mkt in bm.get('markets', []):
                                if mkt['key'] == market:
                                    for outcome in mkt.get('outcomes', []):
                                        player_api = outcome.get('description', outcome.get('name', ''))

                                        price = outcome.get('price', 0)
                                        
                                        # Seulement l'Over
                                        if outcome.get('name', '').lower() == 'over':
                                            # Faire correspondre le joueur
                                            for p_name in players_map.keys():
                                                # Logique de matching flexible
                                                if p_name.lower() in player_api.lower() or player_api.lower() in p_name.lower():
                                                    if p_name not in results:
                                                        results[p_name] = {}
                                                    
                                                    market_cap = market.upper().replace('PLAYER_', '').replace('PITCHER_', '')
                                                    
                                                    # Si pas encore de cote, ou si la nouvelle cote est MEILLEURE (Line Shopping)
                                                    existing_data = results[p_name].get(market_cap)
                                                    if not existing_data or price > existing_data['price']:
                                                        results[p_name][market_cap] = {
                                                            "price": price,
                                                            "bookmaker": bm_name
                                                        }
                except Exception as e:
                    logger.error(f"Erreur connexion Odds API pour event {event_id}: {e}")
                    
            return results

async def fetch_nhl_odds(players_map: Dict[str, str]) -> Dict[str, Dict[str, float]]:
    """
    Scrape les cotes NHL (Buteurs, Passeurs, Pointeurs).
    Args:
        players_map: Dict {Nom_Joueur: Equipe}.
    Returns:
        Dict des cotes: {'McDavid': {'BUTEUR': 2.2, 'PASSEUR': 1.8}}
    """
    if not players_map:
        return {}
        
    # Récupérer en parallèle les 3 marchés
    tasks = [
        OddsAPIClient.fetch_odds('icehockey_nhl', 'player_goal_scorer_anytime', players_map),
        OddsAPIClient.fetch_odds('icehockey_nhl', 'player_assists', players_map),
        OddsAPIClient.fetch_odds('icehockey_nhl', 'player_points', players_map)
    ]
    
    res_buteur, res_assist, res_points = await asyncio.gather(*tasks)
    
    # Fusion des résultats
    final_results = {}
    for name in players_map.keys():
        final_results[name] = {}
        if name in res_buteur and 'GOAL_SCORER_ANYTIME' in res_buteur[name]:
            final_results[name]['BUTEUR'] = res_buteur[name]['GOAL_SCORER_ANYTIME']
        if name in res_assist and 'ASSISTS' in res_assist[name]:
            final_results[name]['PASSEUR'] = res_assist[name]['ASSISTS']
        if name in res_points and 'POINTS' in res_points[name]:
            final_results[name]['POINTEUR'] = res_points[name]['POINTS']
            
    return final_results

async def fetch_mlb_odds(players_map: Dict[str, str]) -> Dict[str, Dict[str, float]]:
    """
    Scrape les cotes MLB (Strikeouts).
    Args:
        players_map: Dict {Nom_Lanceur: Equipe}.
    Returns:
        Dict des cotes: {'Gerrit Cole': {'STRIKEOUTS': 1.85}}
    """
    if not players_map:
        return {}
        
    return await OddsAPIClient.fetch_odds('baseball_mlb', 'pitcher_strikeouts', players_map)

async def fetch_mlb_batter_odds(players_map: Dict[str, str], market: str = 'batter_home_runs') -> Dict[str, Dict[str, float]]:
    """
    Scrape les cotes MLB pour les frappeurs (Home Runs, Hits, etc.).
    Args:
        players_map: Dict {Nom_Joueur: Equipe}.
        market: Le marché ('batter_home_runs', 'batter_hits', etc.).
    Returns:
        Dict des cotes: {'Shohei Ohtani': {'HOME_RUNS': 3.50}}
    """
    if not players_map:
        return {}
        
    return await OddsAPIClient.fetch_odds('baseball_mlb', market, players_map)
