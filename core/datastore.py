import os
import logging
import core.predictor_v12 as predictor_v11
from datetime import datetime, timedelta

logger = logging.getLogger("NHL_Bot")

class DataStore:
    """
    Singleton-like component responsible for holding parsed CSV data in memory.
    This prevents repetitive disk I/O when processing multiple waves in a day.
    """
    def __init__(self, data_dir="./stats"):
        self.data_dir = data_dir
        self.last_load_date = None
        
        # In-memory datasets
        self.form_data = {}
        self.matchups = {}
        self.pp_stats = {}
        self.oi_data = {}
        self.v5_data = {}
        self.goalie_stats = {}
        self.pk_stats = {}
        self.known_players = []

    def load_all_data(self):
        """Loads all CSV files into dictionaries using predictor_v11 loaders."""
        logger.info("Chargement en RAM des bases de données CSV...")
        
        self.form_data = predictor_v11.load_recent_form(f'{self.data_dir}/last 10.csv')
        self.matchups = predictor_v11.load_matchup_data_mp(f'{self.data_dir}/team.csv')
        self.pp_stats = predictor_v11.load_powerplay_stats(f'{self.data_dir}/power play.csv')
        self.oi_data = predictor_v11.load_on_ice_stats(f'{self.data_dir}/on_ice.csv')
        self.v5_data = predictor_v11.load_v5_base_stats(f'{self.data_dir}/Player Season Totals.csv', self.oi_data)
        self.goalie_stats = predictor_v11.load_goalie_stats(f'{self.data_dir}/goalies.csv')
        self.pk_stats = predictor_v11.load_pk_stats(f'{self.data_dir}/pk.csv')

        # Inject PK stats into matchups
        for team_abbr, pk_pct in self.pk_stats.items():
            if team_abbr in self.matchups:
                self.matchups[team_abbr]['PK%'] = pk_pct

        self.known_players = list(self.form_data.keys()) + list(self.v5_data.keys()) + list(self.goalie_stats.keys())
        
        self.last_load_date = datetime.now().strftime("%Y-%m-%d")
        logger.info("Chargement RAM terminé. Prêt pour l'analyse.")

    def refresh_if_needed(self):
        """Refreshes the memory datasets if the current day has changed."""
        now = datetime.now()
        nhl_date = (now - timedelta(hours=12)).strftime("%Y-%m-%d") if now.hour < 12 else now.strftime("%Y-%m-%d")
        # To avoid complex nhl_date logic here, we just use simple date string format passed by bot_logic
        pass # Will be managed by bot_logic.py instead to keep it unified.
        
    def force_refresh(self):
        self.load_all_data()

