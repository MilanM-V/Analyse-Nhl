"""Module de récupération des cotes NHL via The-Odds-API et calcul de Value Betting (Kelly).

Ce module gère :
- Le fetch des cotes "Anytime Goalscorer" pour un match donné.
- Le calcul du Critère de Kelly (fractionné) pour la gestion de bankroll.
- Un compteur de requêtes mensuel pour respecter le quota gratuit de 500/mois.
"""

import os
import json
import logging
import requests
from datetime import datetime
from difflib import SequenceMatcher
from typing import Dict, List, Any, Optional, Tuple
from core.services import safe_get

logger = logging.getLogger("NHL_Bot")

ODDS_COUNTER_FILE = "./stats/odds_api_counter.json"


def _load_counter() -> Dict[str, Any]:
    """Charge le compteur de requêtes API depuis le disque."""
    if os.path.exists(ODDS_COUNTER_FILE):
        try:
            with open(ODDS_COUNTER_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Reset automatique si on change de mois
            if data.get("month") != datetime.now().strftime("%Y-%m"):
                return {"month": datetime.now().strftime("%Y-%m"), "count": 0}
            return data
        except Exception:
            pass
    return {"month": datetime.now().strftime("%Y-%m"), "count": 0}


def _save_counter(data: Dict[str, Any]) -> None:
    """Sauvegarde le compteur de requêtes API sur le disque."""
    os.makedirs(os.path.dirname(ODDS_COUNTER_FILE), exist_ok=True)
    try:
        with open(ODDS_COUNTER_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning(f"Impossible de sauvegarder le compteur Odds API : {e}")


def _increment_counter() -> int:
    """Incrémente le compteur de requêtes et retourne le nombre actuel."""
    data = _load_counter()
    data["count"] += 1
    _save_counter(data)
    return data["count"]


def get_api_usage() -> str:
    """Retourne une chaîne résumant l'utilisation de l'API ce mois-ci.

    Returns:
        str: Ex: "42/500 requêtes utilisées (mars 2026)"
    """
    data = _load_counter()
    month_label = datetime.now().strftime("%B %Y")
    return f"{data['count']}/500 requêtes utilisées ({month_label})"


def get_kelly_bet(proba_bot: float, cote_bookmaker: float, kelly_fraction: int = 4) -> Tuple[bool, float]:
    """Calcule le pourcentage de Bankroll à miser selon le Critère de Kelly Fractionné.

    Args:
        proba_bot: Probabilité estimée par le modèle XGBoost (entre 0.0 et 1.0).
        cote_bookmaker: Cote en format décimal (ex: 3.50).
        kelly_fraction: Diviseur pour limiter la variance (4 = Quart de Kelly).

    Returns:
        tuple: (is_value_bet: bool, mise_pourcentage: float)
    """
    b = cote_bookmaker - 1.0
    p = proba_bot
    q = 1.0 - p

    if b <= 0:
        return False, 0.0

    f = (p * b - q) / b
    is_value = f > 0
    bet_percentage = (f / kelly_fraction) * 100.0 if is_value else 0.0

    return is_value, round(bet_percentage, 2)


def _fuzzy_match_name(player_name: str, api_names: List[str], threshold: float = 0.75) -> Optional[str]:
    """Trouve le meilleur match entre un nom de joueur NHL et les noms de l'API de cotes.

    Args:
        player_name: Nom du joueur NHL (ex: "Connor McDavid").
        api_names: Liste de noms venant de l'API de cotes.
        threshold: Score minimum de similarité (0.0 à 1.0).

    Returns:
        str or None: Le nom API correspondant, ou None si pas de match.
    """
    best_match = None
    best_score = 0.0

    player_lower = player_name.lower().strip()

    for api_name in api_names:
        api_lower = api_name.lower().strip()

        # Match exact
        if player_lower == api_lower:
            return api_name

        # Match partiel (ex: "C. McDavid" == "Connor McDavid")
        score = SequenceMatcher(None, player_lower, api_lower).ratio()

        # Bonus si le nom de famille est identique
        player_last = player_lower.split()[-1] if player_lower else ""
        api_last = api_lower.split()[-1] if api_lower else ""
        if player_last == api_last and len(player_last) > 2:
            score += 0.15

        if score > best_score:
            best_score = score
            best_match = api_name

    return best_match if best_score >= threshold else None


def fetch_market_odds(home_team: str, away_team: str, market_key: str = "player_goal_scorer_anytime") -> Dict[str, float]:
    """Récupère les cotes pour un marché spécifique (buteur, passeur, points).

    Args:
        home_team: Nom complet de l'équipe à domicile.
        away_team: Nom complet de l'équipe à l'extérieur.
        market_key: Le marché (player_goal_scorer_anytime, player_assist, player_points).

    Returns:
        dict: {player_name: cote_decimale}
    """
    api_key = os.getenv("ODDS_API_KEY")
    if not api_key:
        return {}

    counter = _load_counter()
    if counter["count"] >= 500:
        return {}

    try:
        url_events = f"https://api.the-odds-api.com/v4/sports/icehockey_nhl/events?apiKey={api_key}"
        resp_obj = safe_get(url_events, timeout=10)
        _increment_counter()
        events = resp_obj.json()

        target_event = None
        for ev in events:
            if (home_team.lower() in ev.get("home_team", "").lower()
                    or away_team.lower() in ev.get("away_team", "").lower()):
                target_event = ev
                break

        if not target_event:
            return {}

        event_id = target_event["id"]

        url_odds = (
            f"https://api.the-odds-api.com/v4/sports/icehockey_nhl/events/{event_id}/odds"
            f"?apiKey={api_key}&regions=us,eu&markets={market_key}&oddsFormat=decimal"
        )
        resp_odds_obj = safe_get(url_odds, timeout=10)
        _increment_counter()
        odds_data = resp_odds_obj.json()

        if not odds_data or "bookmakers" not in odds_data or not odds_data["bookmakers"]:
            return {}

        bookmaker = odds_data["bookmakers"][0]
        market = next((m for m in bookmaker["markets"] if m["key"] == market_key), None)

        if not market:
            return {}

        player_odds = {}
        for outcome in market.get("outcomes", []):
            name = outcome.get("name", "")
            price = outcome.get("price", 0)
            if name and name != "Yes" and name != "No" and price > 1.0:
                player_odds[name] = price

        return player_odds

    except Exception as e:
        logger.warning(f"Erreur Odds API ({market_key}) : {e}")
        return {}

def enrich_picks_with_odds(picks: List[Dict[str, Any]], home_team_full: str, away_team_full: str) -> List[Dict[str, Any]]:
    """Enrichit une liste de picks avec les cotes réelles et le calcul de Kelly."""
    if not picks: return picks
    
    # Déterminer le marché en fonction de la catégorie du premier pick
    cat = picks[0].get("Categorie", "")
    market_key = "player_goal_scorer_anytime"
    if "PASSEUR" in cat: market_key = "player_assist"
    elif "POINTEUR" in cat: market_key = "player_points"

    odds = fetch_market_odds(home_team_full, away_team_full, market_key)
    if not odds:
        return picks

    api_names = list(odds.keys())

    for pick in picks:
        joueur = pick.get("Joueur", "")
        matched = _fuzzy_match_name(joueur, api_names)

        if matched and matched in odds:
            cote = odds[matched]
            if "Proba" in pick:
                proba_estimee = pick["Proba"]
            else:
                score = pick.get("Score", 0)
                # Paliers de proba ajustés par marché
                if cat == "PASSEUR":
                    proba_estimee = min(0.70, max(0.15, score / 20.0))
                elif cat == "POINTEUR":
                    proba_estimee = min(0.85, max(0.30, score / 15.0))
                else:
                    proba_estimee = min(0.60, max(0.10, score / 25.0))

            is_value, kelly_pct = get_kelly_bet(proba_estimee, cote)

            pick["Cote"] = round(cote, 2)
            pick["ValueBet"] = is_value
            pick["Kelly"] = kelly_pct
        # On ne met plus à None si non trouvé, pour éviter d'écraser les picks d'autres matchs
        # ou de perdre le '?' informatif si l'API est indisponible.

    return picks
