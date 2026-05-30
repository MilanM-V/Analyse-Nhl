import pytest
from nhl.config.constants import TEAM_FULL_TO_ABBR, TEAM_ABBR_TO_FULL, ALL_ABBRS

def test_team_mapping_count():
    """Vérifie qu'on a bien toutes les équipes NHL (32 franchises actives + 1 de renommée ou extension)."""
    # Actuellement on a 34 clés car "St Louis Blues" et "Utah Mammoth" sont des alias de renommée
    assert len(TEAM_FULL_TO_ABBR) >= 32

def test_reverse_mapping():
    """Vérifie que la vue inversée exclut bien les alias et est consistante."""
    for abbr, full_name in TEAM_ABBR_TO_FULL.items():
        assert TEAM_FULL_TO_ABBR[full_name] == abbr

    assert "St Louis Blues" not in TEAM_ABBR_TO_FULL.values()
    assert "Utah Mammoth" not in TEAM_ABBR_TO_FULL.values()

def test_all_abbrs_valid():
    """Vérifie l'ensemble des abbréviations uniques."""
    assert len(ALL_ABBRS) == 32
    assert "MTL" in ALL_ABBRS
    assert "UTA" in ALL_ABBRS
