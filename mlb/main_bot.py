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

import schedule
import time
if hasattr(time, 'tzset'):
    os.environ['TZ'] = 'Europe/Paris'
    time.tzset()

def main():
    try:
        logger.info("=====================================================")
        logger.info("      DÉMARRAGE DU BOT MLB V1 (BETA)                 ")
        logger.info("=====================================================")
        
        from mlb.core.bot_logic import MlbBot
        
        bot = MlbBot()
        
        # 1. Planification des scans
        # Scan de fin d'après-midi (avant les premiers matchs)
        schedule.every().day.at("16:30").do(bot.run_scan_cycle)
        # Scan de soirée
        schedule.every().day.at("22:30").do(bot.run_scan_cycle)
        # Nettoyage et Harvester en fin de nuit (5h00 UTC)
        schedule.every().day.at("05:00").do(bot.end_of_day_cleanup)
        
        logger.info("Scans programmés : 16:30, 22:30 et 05:00 (Cleanup).")
        
        # Exécuter un scan au démarrage pour les tests (optionnel sur VPS)
        bot.run_scan_cycle()
        
        # Boucle infinie pour maintenir le scheduler
        while True:
            schedule.run_pending()
            time.sleep(60)

    except KeyboardInterrupt:
        logger.info("Interruption forcée (Ctrl+C). Arrêt du bot MLB.")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"🚨 CRASH FATAL MLB : {type(e).__name__}: {e}", exc_info=True)
        try:
            from shared.telegram_hub import send_telegram
            send_telegram(f"🚨 <b>CRASH FATAL MLB</b>\n\nErreur: {type(e).__name__}: {e}\nRegarde le fichier bot.log ou mlb_stderr.log pour la stacktrace complète.", recipient="admin")
        except:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()
