import pytest
import os
import pandas as pd
from core.loaders import (
    clean_team_name, load_goalie_stats, load_on_ice_stats, 
    load_v5_base_stats, load_recent_form, load_matchup_data_mp
)

def test_clean_team_name():
    assert clean_team_name("Anaheim Ducks, CA") == "ANA"
    assert clean_team_name("L.A") == "LAK"
    assert clean_team_name("N.J.") == "NJD"
    assert clean_team_name("MTL") == "MTL"

def test_load_goalie_stats(tmp_path):
    d = tmp_path / "stats"
    d.mkdir()
    f = d / "goalies.csv"
    f.write_text("Player,Team,GP\nConnor Hellebuyck,Winnipeg Jets,60\nIgor Shesterkin,New York Rangers,55")
    
    stats = load_goalie_stats(str(f))
    assert "Connor Hellebuyck" in stats
    assert stats["Connor Hellebuyck"]["Team"] == "WPG"
    assert stats["Connor Hellebuyck"]["GP"] == 60

def test_load_on_ice_stats(tmp_path):
    f = tmp_path / "on_ice.csv"
    f.write_text("Player,PDO,On-Ice SH%\nConnor McDavid,1.02,0.12")
    
    stats = load_on_ice_stats(str(f))
    assert "Connor McDavid" in stats
    assert stats["Connor McDavid"]["PDO"] == 102.0
    assert stats["Connor McDavid"]["oiSH"] == 12.0

def test_load_matchup_data_mp(tmp_path):
    f = tmp_path / "team.csv"
    # Colonnes: Team, GP, GA, SA, CA, CF%, HDCA, HDCF%, PK%
    f.write_text("Team,GP,GA,SA,CA,CF%,HDCA,HDCF%,PK%\nEdmonton Oilers,82,200,2000,3000,55.0,800,52.0,80.0")
    
    matchups = load_matchup_data_mp(str(f))
    assert "EDM" in matchups
    assert matchups["EDM"]["GA_G"] == 200/82
    assert matchups["EDM"]["CF_pct"] == 55.0
