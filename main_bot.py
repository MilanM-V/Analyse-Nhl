import os
import sys
import time
import logging
import subprocess
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

from core.datastore import DataStore
from core.services import TelegramNotifier, create_telegram_app
from core.bot_logic import NhlBot

logger = logging.getLogger("NHL_Bot")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = RotatingFileHandler('bot.log', maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
file_handler.setFormatter(formatter)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

load_dotenv()

if hasattr(time, 'tzset'):
    os.environ['TZ'] = 'Europe/Paris'
    time.tzset()

def main():
    # Initialisation minimale avant le try global
    from core.database import init_db
    init_db()  # Auto-migration de la BDD lors du push serveur
    
    if not os.path.exists("./stats"):
        os.makedirs("./stats")
        
    datastore = DataStore()
    telegram = TelegramNotifier()

    try:
        mode_str = "PLAYOFF 🏆" if cfg.api.mode == "playoff" else "Saison Régulière 🏒"
        logger.info("=====================================================")
        logger.info(f"  DÉMARRAGE DU ROBOT NHL V18 — MODE: {mode_str}")
        logger.info("  Architecture refactorisée (DataStore SQLite+RAM ) ")
        logger.info("=====================================================")

        bot = NhlBot(datastore, telegram)

        telegram_app = create_telegram_app(bot)

        if telegram_app is not None:
            logger.info("Planificateur Telegram JobQueue initialisé.")
        else:
            logger.info("Mode sans Telegram activé.")

        logger.info("🚀 Lancement immédiat du premier scan de la journée en arrière-plan...")
        import threading
        threading.Thread(target=bot.run_scan_cycle, daemon=True).start()

        # NB: V17 - Le système de Retraining ML a été retiré (overfitting).

        logger.info("Le bot est en attente...")

        if telegram_app is not None:
            from telegram.error import Conflict
            try:
                telegram_app.run_polling(drop_pending_updates=True)
            except KeyboardInterrupt:
                logger.info("Interruption forcée (Ctrl+C). Arrêt du bot.")
                sys.exit(0)
            except Conflict:
                logger.error("🛑 ERREUR CRITIQUE : Un autre bot utilise déjà ce token Telegram !")
                logger.error("👉 Solution : Ferme tous tes autres terminaux/consoles qui font tourner le bot, puis relance.")
                sys.exit(1)
        else:
            # Mode sans Telegram : boucle de scan manuelle
            logger.info("Mode sans Telegram : boucle de scan toutes les 15 minutes.")
            while True:
                bot.run_scan_cycle()
                time.sleep(900)

    except KeyboardInterrupt:
        logger.info("Interruption forcée (Ctrl+C). Arrêt du bot.")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"🚨 CRASH FATAL : {type(e).__name__}: {e}", exc_info=True)
        telegram.send_crash_alert(e, context="main_bot.py — Boucle Principale")
        sys.exit(1)

if __name__ == "__main__":
    main()

