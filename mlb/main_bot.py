"""
mlb/main_bot.py — Point d'entrée du bot MLB.

Pour l'instant, ne lance que le harvester (collecte de données).
Le bot de paris sera développé dans une phase ultérieure.
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ─── PATH SETUP (Multi-Sport Architecture) ───────────────────────────────────
_SPORT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SPORT_DIR.parent

if str(_SPORT_DIR) not in sys.path:
    sys.path.insert(0, str(_SPORT_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.chdir(_SPORT_DIR)

from dotenv import load_dotenv
load_dotenv(_REPO_ROOT / ".env")

# ─── LOGGING ─────────────────────────────────────────────────────────────────
logger = logging.getLogger("MLB_Bot")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = RotatingFileHandler('mlb_bot.log', maxBytes=2*1024*1024, backupCount=3, encoding='utf-8')
file_handler.setFormatter(formatter)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)


def main() -> None:
    """Lance le harvester MLB en mode daemon."""
    logger.info("=====================================================")
    logger.info("  DÉMARRAGE DU BOT MLB — Mode Harvester (collecte)")
    logger.info("=====================================================")

    from core.harvester import init_db, run_harvester_loop
    init_db()
    run_harvester_loop()


if __name__ == "__main__":
    main()
