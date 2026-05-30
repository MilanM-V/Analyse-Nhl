import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from nhl.core.odds_scraper import normalize_name_for_url


class TestNormalizeNameForUrl:
    """Tests de la conversion de noms en slugs URL (legacy, conservé pour compatibilité)."""

    def test_simple_name(self):
        assert normalize_name_for_url("Connor McDavid") == "connor-mcdavid"

    def test_empty_string(self):
        assert normalize_name_for_url("") == ""


class TestOddsAPIStructure:
    """Vérifie que la structure du module Odds API est cohérente."""

    def test_cache_structure(self):
        from nhl.core.odds_scraper import _CACHE
        assert "data" in _CACHE
        assert "timestamp" in _CACHE

    def test_api_key_env_var(self):
        """Vérifie que la variable d'env est lue (peut être None en test)."""
        from nhl.core.odds_scraper import API_KEY
        # API_KEY peut être None en CI, mais ne doit pas crasher
        assert API_KEY is None or isinstance(API_KEY, str)

    def test_fetch_multiple_odds_no_key(self):
        """Sans clé API, retourne des résultats vides avec la structure correcte."""
        import asyncio
        from nhl.core.odds_scraper import fetch_multiple_odds
        
        # Simuler sans clé API
        import core.odds_scraper as ods
        orig_key = ods.API_KEY
        ods.API_KEY = None
        try:
            result = asyncio.run(fetch_multiple_odds({"Connor McDavid": "EDM"}))
            assert "Connor McDavid" in result
            assert result["Connor McDavid"]["BUTS"] is None
            assert result["Connor McDavid"]["ASSISTS"] is None
            assert result["Connor McDavid"]["POINTS"] is None
        finally:
            ods.API_KEY = orig_key
