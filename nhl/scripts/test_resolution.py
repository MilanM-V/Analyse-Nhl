import logging
from core.updater import update_pending_picks

# Configurer les logs pour voir ce que fait l'updater
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("NHL.TestResolution")

if __name__ == "__main__":
    print("Début du test de résolution...")
    resolved = update_pending_picks()
    print(f"Test terminé. {resolved} picks résolus.")
