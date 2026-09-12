"""
shared/utils.py — Utilitaires partagés entre tous les sports.

Contient les helpers génériques : retry HTTP, normalisation de noms, etc.
"""

import time
import unicodedata
import logging
from functools import wraps
from typing import Callable

import requests

logger = logging.getLogger("SharedUtils")


def retry_request(max_retries: int = 3, base_delay: float = 2.0) -> Callable:
    """Decorator pour exponential backoff sur les requêtes HTTP.

    Args:
        max_retries: Nombre maximum de tentatives.
        base_delay: Délai initial entre les tentatives en secondes.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except (requests.exceptions.RequestException, Exception) as e:
                    retries += 1
                    if retries == max_retries:
                        logger.error(
                            f"Erreur HTTP persistante après {max_retries} "
                            f"tentatives : {e}"
                        )
                        raise
                    delay = base_delay * (2 ** (retries - 1))
                    logger.warning(
                        f"Erreur HTTP ({e}). Tentative {retries}/{max_retries} "
                        f"dans {delay}s..."
                    )
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


@retry_request(max_retries=3, base_delay=2.0)
def safe_get(url: str, **kwargs) -> requests.Response:
    """Effectue une requête GET avec retry automatique.

    Args:
        url: URL cible.
        **kwargs: Arguments passés à requests.get().

    Returns:
        L'objet Response.
    """
    resp = requests.get(url, **kwargs)
    resp.raise_for_status()
    return resp


@retry_request(max_retries=3, base_delay=2.0)
def safe_post(url: str, **kwargs) -> requests.Response:
    """Effectue une requête POST avec retry automatique.

    Args:
        url: URL cible.
        **kwargs: Arguments passés à requests.post().

    Returns:
        L'objet Response.
    """
    resp = requests.post(url, **kwargs)
    resp.raise_for_status()
    return resp


def normalize_name(name: str) -> str:
    """Supprime les accents et normalise le texte pour comparaison.

    Args:
        name: Nom à normaliser.

    Returns:
        Nom sans accents ni diacritiques.
    """
    if not name:
        return ""
    normalized = unicodedata.normalize("NFD", name)
    return "".join(c for c in normalized if not unicodedata.combining(c)).strip()


def match_player_name(db_name: str, api_name: str) -> bool:
    """Compare deux noms de joueur avec tolérance aux accents et formats.

    Gère les formats :
    - 'Alexis Lafrenière' vs 'A. Lafreniere'
    - 'Alexander Ovechkin' vs 'Alex Ovechkin'

    Args:
        db_name: Nom tel qu'en base de données.
        api_name: Nom tel que retourné par l'API.

    Returns:
        True si les noms correspondent au même joueur.
    """
    db_clean = normalize_name(db_name).lower()
    api_clean = normalize_name(api_name).lower()

    # 1. Correspondance exacte après normalisation
    if db_clean == api_clean:
        return True

    # 2. Format API 'J. Hughes' → Initiale + Nom
    if "." in api_clean:
        parts = api_clean.split(".", 1)
        initial = parts[0].strip()
        last_name = parts[1].strip()
        db_parts = db_clean.split()
        if len(db_parts) >= 2:
            return db_clean.startswith(initial) and db_parts[-1] == last_name

    # 3. Initiale + Nom de famille identique
    db_parts = db_clean.split()
    api_parts = api_clean.split()
    if len(db_parts) >= 2 and len(api_parts) >= 2:
        return db_parts[0][0] == api_parts[0][0] and db_parts[-1] == api_parts[-1]

    return False
