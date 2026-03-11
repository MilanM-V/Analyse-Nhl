import time
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from datetime import datetime, timedelta
from selenium.webdriver.chrome.service import Service
from dotenv import load_dotenv
import sys

load_dotenv()

# Récupère les variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BRAVE_PATH = os.getenv("BRAVE_PATH")

# Liste des mots pub à bannir absolument
TRASH_WORDS = ["NHL.TV", "BETCLIC", "CRYPTO.COM", "ARENA", ".FR", ".COM", ".TV", "NATIONWIDE", "CENTRE"]

def get_driver(show_browser=False):
    options = Options()
    options.binary_location = BRAVE_PATH
    if sys.platform.startswith('linux'):
        if not show_browser:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        service = Service( log_output=os.devnull)
    else:
        show_browser=False
        options.add_argument("--log-level=3")
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        options.add_argument("--disable-blink-features=AutomationControlled")
        if not show_browser:
            options.add_argument("--headless") 
        service = Service(log_output=os.devnull)
        service.creation_flags = 0x08000000 

    
    return webdriver.Chrome(options=options, service=service)

def is_valid_lineup(player_list):
    if len(player_list) < 22:
        return False
    
    for name in player_list:
        n_upper = name.upper()
        if any(trash in n_upper for trash in TRASH_WORDS):
            return False
            
    return True

def get_scheduled_matches(url):
    driver = get_driver(show_browser=False)
    now = datetime.now()
    if now.hour < 12:
        reference_date = now - timedelta(days=1)
    else:
        reference_date = now
    now=reference_date
    start_limit = now.replace(hour=17, minute=0, second=0, microsecond=0)
    end_limit = (now + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
    
    matches_found = []
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "event__match")))
        rows = driver.find_elements(By.CSS_SELECTOR, ".event__match")

        for row in rows:
            try:
                time_str = row.find_element(By.CLASS_NAME, "event__time").text
                match_dt = datetime.strptime(f"{time_str} {now.year}", "%d.%m. %H:%M %Y")

                if match_dt > end_limit:
                    break
                if match_dt >= start_limit:
                    home = row.find_element(By.CLASS_NAME, "event__participant--home").text
                    away = row.find_element(By.CLASS_NAME, "event__participant--away").text
                    match_id = row.get_attribute("id").replace("g_4_", "")
                    matches_found.append({"id": match_id, "time": time_str, "home": home, "away": away})
            except:
                continue
    finally:
        driver.quit()
    return matches_found

def get_lineups(match_id):
    url = f"https://www.flashscore.fr/match/{match_id}/"
    driver = get_driver(show_browser=False) 
    
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 10)

        tabs = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, '[data-testid="wcl-tab"]')))
        for tab in tabs:
            if "COMPOS" in tab.text.upper() or "LINEUPS" in tab.text.upper():
                driver.execute_script("arguments[0].click();", tab)
                break
        
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="wcl-scores-simple-text-01"]')))
        time.sleep(2) 

        els = driver.find_elements(By.CSS_SELECTOR, '[data-testid="wcl-scores-simple-text-01"]')
        full_list = []
        for e in els:
            name = e.text.strip()
            if name and not name.startswith('(') and not name.isdigit() and name.upper() not in ["V", "D", "?", "P"]:
                full_list.append(name)

        if not is_valid_lineup(full_list):
            return "compo incomplète ou pub détectée"

        return {
            "goalDom": full_list[0],
            "goalext": full_list[6],
            "f1_dom": ", ".join(full_list[1:6]),
            "f1_ext": ", ".join(full_list[7:12]),
            "f2_dom": ", ".join(full_list[12:17]),
            "f2_ext": ", ".join(full_list[17:22])
        }

    except Exception:
        return "compo pas dispo"
    finally:
        driver.quit()

if __name__ == "__main__":
    print("Test local du scraper...")
    print(get_scheduled_matches("https://www.flashscore.fr/hockey/usa/nhl/calendrier/"))
