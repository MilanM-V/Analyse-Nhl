import os
import sys
import time
import logging
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
    logger.info("=====================================================")
    logger.info("  DÉMARRAGE DU ROBOT NHL VALUE BETS V11 (ASYNC)   ")
    logger.info("  Architecture refactorisée (DataStore SQLite+RAM ) ")
    logger.info("=====================================================")

    if not os.path.exists("./stats"):
        os.makedirs("./stats")
    datastore = DataStore()
    telegram = TelegramNotifier()
    bot = NhlBot(datastore, telegram)

    telegram_app = create_telegram_app(bot)

    if telegram_app is not None:
        logger.info("Planificateur Telegram JobQueue initialisé.")
    else:
        logger.info("Mode sans Telegram activé.")

    logger.info("🚀 Lancement immédiat du premier scan de la journée en arrière-plan...")
    # Lancement d'un thread séparé pour le scan immédiat
    import threading
    threading.Thread(target=bot.run_scan_cycle, daemon=True).start()

    logger.info("Le bot est en attente...")

    try:
        telegram_app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        logger.info("Interruption forcée (Ctrl+C). Arrêt du bot.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"ERREUR CRITIQUE dans la boucle principale Telegram : {e}")
        logger.info("Fermeture.")

if __name__ == "__main__":
    main()
