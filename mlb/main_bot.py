"""
mlb/main_bot.py — Point d'entrée principal pour le bot MLB.
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv
import logging
import asyncio

# Setup paths (same as NHL)
_SPORT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SPORT_DIR.parent

sys.path.insert(0, str(_SPORT_DIR))
sys.path.insert(0, str(_REPO_ROOT))

os.chdir(_SPORT_DIR)
load_dotenv(_REPO_ROOT / ".env")

# Logger MLB
logger = logging.getLogger("MLB")
logger.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
fh = logging.FileHandler("bot.log", encoding="utf-8")
sh = logging.StreamHandler()
fh.setFormatter(fmt)
sh.setFormatter(fmt)
logger.addHandler(fh)
logger.addHandler(sh)

def main():
    logger.info("=====================================================")
    logger.info("      DÉMARRAGE DU BOT MLB V1 (BETA)                 ")
    logger.info("=====================================================")
    
    from mlb.core.bot_logic import MlbBot
    
    bot = MlbBot()
    
    # Pour l'instant, on exécute un scan immédiatement au démarrage pour tester
    bot.run_scan_cycle()
    
    # La boucle infinie (ou le scheduler) viendra ici plus tard, 
    # pour l'instant le watchdog peut s'en charger ou on mettra apscheduler comme dans NHL.
    logger.info("Scan initial MLB terminé. (En attente d'implémentation du Scheduler permanent)")

if __name__ == "__main__":
    main()
