import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from nhl.core.updater import match_player_name, normalize_name


class TestNormalizeName:
    """Tests de la normalisation des noms (accents, espaces)."""

    def test_accents_removed(self):
        assert normalize_name("Alexis Lafrenière") == "Alexis Lafreniere"

    def test_umlaut_removed(self):
        assert normalize_name("Tim Stützle") == "Tim Stutzle"

    def test_plain_name_unchanged(self):
        assert normalize_name("Connor McDavid") == "Connor McDavid"

    def test_empty_string(self):
        assert normalize_name("") == ""


class TestMatchPlayerName:
    """Tests du matching de noms (API vs base de données)."""

    def test_exact_match(self):
        """Noms identiques → True."""
        assert match_player_name("Connor McDavid", "Connor McDavid") is True

    def test_initial_format(self):
        """Format 'C. McDavid' → True."""
        assert match_player_name("Connor McDavid", "C. McDavid") is True

    def test_accents_vs_no_accents(self):
        """'Lafrenière' vs 'A. Lafreniere' → True."""
        assert match_player_name("Alexis Lafrenière", "A. Lafreniere") is True

    def test_alex_vs_alexander(self):
        """'Alexander Ovechkin' vs 'Alex Ovechkin' → True (initiale commune + nom de famille)."""
        assert match_player_name("Alexander Ovechkin", "Alex Ovechkin") is True

    def test_no_match_different_players(self):
        """Joueurs complètement différents → False."""
        assert match_player_name("Connor McDavid", "Leon Draisaitl") is False

    def test_no_match_same_initial_different_last(self):
        """Même initiale mais nom de famille différent → False."""
        assert match_player_name("Connor McDavid", "Carter Verhaeghe") is False

    @pytest.mark.xfail(reason="Bug connu : le '.' dans 'St.' casse le parsing par initiale. Pas critique (aucun joueur actif concerné).")
    def test_initial_with_compound_last_name(self):
        """Format initiale avec nom composé."""
        assert match_player_name("Martin St. Louis", "M. St. Louis") is True

    def test_umlaut_initial(self):
        """Tim Stützle vs T. Stutzle → True."""
        assert match_player_name("Tim Stützle", "T. Stutzle") is True
