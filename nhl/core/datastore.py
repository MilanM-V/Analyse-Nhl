import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import core.loaders as loaders

logger = logging.getLogger("NHL_Bot")

class DataStore:
    """
    Singleton-like component responsible for holding parsed CSV data in memory.
    This prevents repetitive disk I/O when processing multiple waves in a day.
    """
    def __init__(self, data_dir: str = "./stats") -> None:
        """
        Initializes the DataStore with a data directory.

        Args:
            data_dir: Directory where CSV files are stored.
        """
        self.data_dir = data_dir
        self.last_load_date: Optional[str] = None
        
        # In-memory datasets
        self.form_data: Dict[str, Dict[str, Any]] = {}
        self.matchups: Dict[str, Dict[str, float]] = {}
        self.pp_stats: Dict[str, float] = {}
        self.oi_data: Dict[str, Dict[str, float]] = {}
        self.v5_data: Dict[str, Dict[str, Any]] = {}
        self.goalie_stats: Dict[str, Dict[str, Any]] = {}
        self.pk_stats: Dict[str, float] = {}
        self.known_players: List[str] = []

    def load_all_data(self) -> None:
        """Loads all CSV files into dictionaries using loaders."""
        logger.info("Chargement en RAM des bases de données CSV...")
        
        self.form_data = loaders.load_recent_form(f'{self.data_dir}/last 10.csv')
        self.matchups = loaders.load_matchup_data_mp(f'{self.data_dir}/team.csv')
        self.pp_stats = loaders.load_powerplay_stats(f'{self.data_dir}/power play.csv')
        self.oi_data = loaders.load_on_ice_stats(f'{self.data_dir}/on_ice.csv')
        self.v5_data = loaders.load_v5_base_stats(f'{self.data_dir}/Player Season Totals.csv', self.oi_data)
        self.goalie_stats = loaders.load_goalie_stats(f'{self.data_dir}/goalies.csv')
        self.pk_stats = loaders.load_pk_stats(f'{self.data_dir}/pk.csv')

        # Inject PK stats into matchups
        for team_abbr, pk_pct in self.pk_stats.items():
            if team_abbr in self.matchups:
                self.matchups[team_abbr]['PK%'] = pk_pct

        self.known_players = list(set(list(self.form_data.keys()) + list(self.v5_data.keys()) + list(self.goalie_stats.keys())))
        
        self.last_load_date = (datetime.now() - timedelta(hours=14)).strftime("%Y-%m-%d")
        logger.info(f"Chargement RAM terminé. {len(self.known_players)} joueurs connus. Prêt pour l'analyse.")

    def refresh_if_needed(self) -> None:
        """Refreshes the memory datasets if the current day has changed."""
        # Logic managed by bot_logic.py
        pass
        
    def force_refresh(self) -> None:
        """Forces a reload of all data from disk."""
        self.load_all_data()
