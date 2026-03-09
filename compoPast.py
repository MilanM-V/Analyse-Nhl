import re
import time
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime, timedelta
from selenium.webdriver.chrome.service import Service
import logging
from logging.handlers import RotatingFileHandler

# Configuration du logging
logger = logging.getLogger("NHL_Bot")
logger.setLevel(logging.INFO)

# Formateur : Date - Nom - Niveau - Message
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Handler pour le fichier (5 Mo max, 5 fichiers de backup)
file_handler = RotatingFileHandler('bot.log', maxBytes=5*1024*1024, backupCount=5)
file_handler.setFormatter(formatter)

# Handler pour la console (pour voir les messages en direct)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(stream_handler)
# --- CONFIGURATION ---
BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
FILE_NAME = "resultats_nhl.txt"

def get_driver(show_browser=True):
    options = Options()
    options.binary_location = BRAVE_PATH
    options.add_argument("--log-level=3")
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    options.add_argument("--disable-blink-features=AutomationControlled")
    if not show_browser:
        options.add_argument("--headless") 
    service = Service(log_output=os.devnull)
    service.creation_flags = 0x08000000 
    return webdriver.Chrome(options=options, service=service)

def get_past_matches(url):
    driver = get_driver(show_browser=True)
    now = datetime.now()
    # Fenêtre : Hier 17h -> Ce matin 6h
    start_limit = (now - timedelta(days=5)).replace(hour=17, minute=0, second=0, microsecond=0)
    end_limit = (now - timedelta(days=4)).replace(hour=6, minute=0, second=0, microsecond=0)
    
    matches_found = []
    try:
        driver.get(url)
        time.sleep(5)
        # Scroll pour charger les matchs de nuit
        driver.execute_script("window.scrollTo(0, 2000);")
        time.sleep(2)
        rows = driver.find_elements(By.CSS_SELECTOR, ".event__match")

        for row in rows:
            try:
                raw_text = row.find_element(By.CLASS_NAME, "event__time").text.strip()
                # On prend les 12 premiers chars pour JJ.MM. HH:MM
                clean_time = raw_text.replace('\n', ' ')[:12].strip()
                try:
                    match_dt = datetime.strptime(f"{clean_time} 2026", "%d.%m. %H:%M %Y")
                except:
                    try:
                        alt = clean_time.replace('. ', ' ')
                        match_dt = datetime.strptime(f"{alt} 2026", "%d.%m %H:%M %Y")
                    except: continue

                if start_limit <= match_dt <= end_limit:
                    home = row.find_element(By.CLASS_NAME, "event__participant--home").text
                    away = row.find_element(By.CLASS_NAME, "event__participant--away").text
                    mid = row.get_attribute("id").replace("g_4_", "")
                    matches_found.append({"id": mid, "time": clean_time, "home": home, "away": away})
            except: continue
    finally:
        driver.quit()
    return matches_found

def get_lineups(match_id):
    url = f"https://www.flashscore.fr/match/{match_id}/"
    driver = get_driver(show_browser=True)
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 10)

        # Clic sur l'onglet Compos
        tabs = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, '[data-testid="wcl-tab"]')))
        for tab in tabs:
            if "COMPOS" in tab.text.upper() or "LINEUPS" in tab.text.upper():
                driver.execute_script("arguments[0].click();", tab)
                break
        
        # Attente des noms de joueurs
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="wcl-scores-simple-text-01"]')))
        time.sleep(2) 

        els = driver.find_elements(By.CSS_SELECTOR, '[data-testid="wcl-scores-simple-text-01"]')
        full_list = []
        for e in els:
            name = e.text.strip()
            # On ignore les (G), numéros, et symboles de forme
            if name and not name.startswith('(') and not name.isdigit() and name.upper() not in ["V", "D", "?", "P"]:
                full_list.append(name)

        if len(full_list) < 5:
            return None

        # Slicing sécurisé pour extraire les blocs de joueurs
        def safe_list(lst, start, end):
            return ", ".join(lst[start:end]) if len(lst) >= end else "N/A"

        return {
            "goalDom": full_list[0] if len(full_list) > 0 else "N/A",
            "goalext": full_list[6] if len(full_list) > 6 else "N/A",
            "f1_dom": safe_list(full_list, 1, 6),
            "f1_ext": safe_list(full_list, 7, 12),
            "f2_dom": safe_list(full_list, 12, 17),
            "f2_ext": safe_list(full_list, 17, 22)
        }
    except: return None
    finally: driver.quit()

# --- EXECUTION ET ECRITURE ---
if __name__ == "__main__":
    URL_RES = "https://www.flashscore.fr/hockey/usa/nhl/resultats/"
    logger.info("--- DEBUT DU SCAN NHL ---")
    matches = get_past_matches(URL_RES)

    if not matches:
        logger.info("Aucun match trouvé pour la nuit dernière.")
    else:
        logger.info(f"{len(matches)} matchs trouvés. Analyse en cours...")
        
        # 'w' pour écraser le fichier à chaque lancement, 'encoding' pour les accents
        with open(FILE_NAME, "w", encoding="utf-8") as f:
            for m in matches:
                logger.info(f"Extraction : {m['home']} vs {m['away']}...")
                c = get_lineups(m['id'])
                
                if c:
                    # Construction de la chaîne de caractères au format demandé
                    output = (
                        f"Match : {m['home']} - {m['away']} ({m['time']})\n"
                        f"  goal dom: {c['goalDom']}\n"
                        f"  goal ext: {c['goalext']}\n"
                        f"  f1 dom: {c['f1_dom']}\n"
                        f"  f1 ext: {c['f1_ext']}\n"
                        f"  f2 dom: {c['f2_dom']}\n"
                        f"  f2 ext: {c['f2_ext']}\n"
                        f"{'-'*40}\n"
                    )
                    f.write(output)
                    logger.info("   Match ajouté au fichier.")
                else:
                    logger.info(f"   Compo non disponible pour {m['home']}.")
        
        logger.info(f"\n--- TERMINE ---")
        logger.info(f"Le fichier '{FILE_NAME}' a été mis à jour dans le dossier du script.")