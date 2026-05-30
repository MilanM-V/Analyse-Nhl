import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from nhl.core.bot_logic import NhlBot
from nhl.core.datastore import DataStore
from nhl.core.services import TelegramNotifier
from unittest.mock import MagicMock


@pytest.fixture
def bot():
    """Crée une instance NhlBot avec des mocks pour le testing."""
    ds = MagicMock(spec=DataStore)
    tg = MagicMock(spec=TelegramNotifier)
    tg.enabled = False
    return NhlBot(ds, tg)


class TestQuarterKelly:
    """Tests du calcul de mise (Quarter Kelly)."""

    def test_kelly_buteur_cap(self, bot):
        """BUTEUR plafonné à 1.5 U."""
        result = bot._calculate_quarter_kelly(proba=0.55, cote=2.5, categorie="BUTEUR")
        if result != "0 U":
            units = float(result.replace(" U", ""))
            assert units <= 1.5, f"BUTEUR ne doit JAMAIS dépasser 1.5 U, got {units}"

    def test_kelly_negative_value(self, bot):
        """Proba faible + grosse cote = value négative → retourne '0 U'."""
        result = bot._calculate_quarter_kelly(proba=0.10, cote=8.0, categorie="BUTEUR")
        units = float(result.replace(" U", ""))
        assert units == 0.0, f"Value négative devrait donner 0.0 U, got {units}"

    def test_kelly_no_cote(self, bot):
        """Pas de cote disponible → retourne '1 U' (défaut)."""
        result = bot._calculate_quarter_kelly(proba=0.60, cote=None, categorie="BUTEUR")
        assert result == "1 U", f"Sans cote, devrait retourner '1 U', got '{result}'"

    def test_kelly_cote_invalide(self, bot):
        """Cote <= 1.05 → retourne '1 U' (défaut)."""
        result = bot._calculate_quarter_kelly(proba=0.60, cote=1.02, categorie="BUTEUR")
        assert result == "1 U"


class TestCategoryCaps:
    """Vérifie que les plafonds de catégorie sont correctement définis."""

    def test_caps_existent(self):
        assert "BUTEUR" in NhlBot.CATEGORY_CAPS
        assert "PASSEUR" in NhlBot.CATEGORY_CAPS
        assert "POINTEUR" in NhlBot.CATEGORY_CAPS

    def test_caps_values(self):
        assert NhlBot.CATEGORY_CAPS["BUTEUR"] == 1.5
        assert NhlBot.CATEGORY_CAPS["PASSEUR"] == 2.0
        assert NhlBot.CATEGORY_CAPS["POINTEUR"] == 2.0


class TestNhlSessionDate:
    """Vérifie le calcul de la date de session NHL."""

    def test_returns_string(self):
        result = NhlBot.get_nhl_session_date()
        assert isinstance(result, str)
        assert len(result) == 10  # YYYY-MM-DD


class TestWaveDedup:
    """Vérifie que le système anti-doublons fonctionne."""

    def test_matchs_envoyes_set_exists(self, bot):
        assert hasattr(bot, 'matchs_envoyes')
        assert isinstance(bot.matchs_envoyes, set)

    def test_matchs_envoyes_initially_empty(self, bot):
        assert len(bot.matchs_envoyes) == 0
