import os
import sys
from dotenv import load_dotenv

# Add parent dir to path
sys.path.append(os.getcwd())

from core.updater import update_pending_picks
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NHL_Bot")

if __name__ == "__main__":
    load_dotenv()
    print("Lancement manuel de la resolution des picks...")
    update_pending_picks()
    print("Termine.")
