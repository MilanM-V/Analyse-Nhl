import time
import os
import sys
import logging
import requests
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from dotenv import load_dotenv

if hasattr(time, 'tzset'):
    os.environ['TZ'] = 'Europe/Paris'
    time.tzset()

load_dotenv()

logger = logging.getLogger("NHL_Bot")

BRAVE_PATH = os.getenv("BRAVE_PATH")

TRASH_WORDS = ["NHL.TV", "BETCLIC", "CRYPTO.COM", "ARENA", ".FR", ".COM", ".TV", "NATIONWIDE", "CENTRE"]

# Sélecteurs CSS Flashscore — centralisés pour maintenance facile
FS_MATCH_SELECTOR = ".event__match"
FS_TIME_SELECTOR = "event__time"
FS_HOME_SELECTOR = "event__participant--home"
FS_AWAY_SELECTOR = "event__participant--away"
FS_HOME_PARTICIPANT = "event__homeParticipant"
FS_AWAY_PARTICIPANT = "event__awayParticipant"
FS_TAB_SELECTOR = '[data-testid="wcl-tab"]'
# Sélecteur principal pour les noms de joueurs dans les compos
FS_PLAYER_NAME_SELECTOR = '[data-testid="wcl-scores-simple-text-01"]'
# Sélecteurs de fallback si le principal change
FS_PLAYER_NAME_FALLBACK = [
    '.lf__participantName',
    '.lineups__participantName',
    '[class*="lineupPlayer"]',
]

NHL_BASE = "https://api-web.nhle.com"

# Import centralisé depuis la source unique
from config.constants import TEAM_ABBR_TO_FULL as NHL_ABBR_TO_FULL

def _nhl_date():
    now = datetime.now()
    if now.hour < 12:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")

def _utc_to_local(utc_str):
    """UTC → heure Paris via calcul DST correct (dernier dimanche de mars/octobre)."""
    try:
        from calendar import monthrange
        dt = datetime.strptime(utc_str[:19], "%Y-%m-%dT%H:%M:%S")

        def last_sunday(year, month):
            last_day = monthrange(year, month)[1]
            d = datetime(year, month, last_day)
            return d - timedelta(days=(d.weekday() + 1) % 7)

        dst_start = last_sunday(dt.year, 3).replace(hour=1)   # passage à UTC+2
        dst_end = last_sunday(dt.year, 10).replace(hour=1)     # retour à UTC+1
        offset = 2 if dst_start <= dt < dst_end else 1
        return (dt + timedelta(hours=offset)).strftime("%d.%m. %H:%M")
    except Exception:
        return ""

def get_driver(show_browser=False):
    options = Options()
    if BRAVE_PATH:
        options.binary_location = BRAVE_PATH
    if sys.platform.startswith('linux'):
        if not show_browser:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        service = Service(log_output=os.devnull)
    else:
        options.add_argument("--log-level=3")
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        options.add_argument("--disable-blink-features=AutomationControlled")
        if not show_browser:
            options.add_argument("--headless")
        service = Service(log_output=os.devnull)
        service.creation_flags = 0x08000000
    return webdriver.Chrome(options=options, service=service)

def is_valid_lineup(player_list):
    """Validates a scraped lineup list for completeness and cleanliness."""
    if len(player_list) < 22:
        return False
    for name in player_list:
        upper = name.upper()
        # Vérifier les mots-clés de pub/sponsoring
        if any(trash in upper for trash in TRASH_WORDS):
            return False
        # Rejeter les noms contenant des caractères suspects (URLs, symboles)
        if any(c in name for c in ['@', '#', '€', '$', '/', '\\', 'http']):
            return False
        # Rejeter les noms purement numériques ou trop courts
        if name.isdigit() or len(name.strip()) < 3:
            return False
    return True

def get_scheduled_matches(url="", driver=None):
    """
    Retourne les matchs NHL du soir via l'API officielle NHL.
    Fallback automatique sur Flashscore si l'API est injoignable avec driver persistant.
    """
    date_str = _nhl_date()
    try:
        r = requests.get(f"{NHL_BASE}/v1/schedule/{date_str}", timeout=10)
        if r.status_code != 200:
            raise Exception(f"HTTP {r.status_code}")
        data = r.json()
    except Exception as e:
        logger.warning(f"API NHL schedule indisponible ({e}), fallback Flashscore")
        return _get_scheduled_matches_flashscore(
            url or "https://www.flashscore.fr/hockey/usa/nhl/", driver)

    now = datetime.now()
    ref = now - timedelta(days=1) if now.hour < 12 else now
    start_limit = ref.replace(hour=17, minute=0, second=0, microsecond=0)
    end_limit   = (ref + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)

    matches_found = []
    for day in data.get("gameWeek", []):
        if day.get("date") != date_str:
            continue
        for g in day.get("games", []):
            if g.get("gameType", 2) not in (2, 3):  
                continue
            game_id    = str(g.get("id", ""))
            start_utc  = g.get("startTimeUTC", "")
            home_abbr  = g.get("homeTeam", {}).get("abbrev", "")
            away_abbr  = g.get("awayTeam", {}).get("abbrev", "")
            home_full  = NHL_ABBR_TO_FULL.get(home_abbr, home_abbr)
            away_full  = NHL_ABBR_TO_FULL.get(away_abbr, away_abbr)
            time_local = _utc_to_local(start_utc)
            if not time_local:
                continue
            try:
                dt_local = datetime.strptime(f"{time_local} {now.year}", "%d.%m. %H:%M %Y")
                if dt_local < now - timedelta(hours=12):
                    dt_local += timedelta(days=1)
                if not (start_limit <= dt_local <= end_limit):
                    continue
            except Exception:
                continue

            matches_found.append({
                "id":   game_id,  
                "time": time_local,
                "home": home_full,
                "away": away_full,
            })

    logger.info(f"[API NHL] {len(matches_found)} match(s) pour {date_str}")
    return matches_found

def _get_scheduled_matches_flashscore(url, driver=None):
    """Fallback Selenium sur Flashscore si l'API NHL est down."""
    local_driver = False
    if driver is None:
        driver = get_driver()
        local_driver = True

    now = datetime.now()
    ref = now - timedelta(days=1) if now.hour < 12 else now
    start_limit = ref.replace(hour=17, minute=0, second=0, microsecond=0)
    end_limit   = (ref + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
    matches_found = []
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "event__match")))
        for row in driver.find_elements(By.CSS_SELECTOR, ".event__match"):
            try:
                time_str = row.find_element(By.CLASS_NAME, "event__time").text
                match_dt = datetime.strptime(f"{time_str} {ref.year}", "%d.%m. %H:%M %Y")
                if match_dt > end_limit:
                    break
                if match_dt >= start_limit:
                    home = row.find_element(By.CLASS_NAME, "event__participant--home").text
                    away = row.find_element(By.CLASS_NAME, "event__participant--away").text
                    match_id = row.get_attribute("id").replace("g_4_", "")
                    matches_found.append({"id": match_id, "time": time_str,
                                          "home": home, "away": away})
            except Exception as e:
                logger.warning(f"_flashscore_schedule row : {e}")
    finally:
        if local_driver:
            driver.quit()
    return matches_found

_FS_ID_CACHE: dict = {}  

def _resolve_flashscore_id(nhl_game_id, home, away, driver=None):
    """
    Trouve l'ID Flashscore en scrapant la page calendrier NHL de Flashscore.
    Matching sur le dernier mot du nom d'équipe (ex: "Bruins", "Oilers").
    Résultat mis en cache pour toute la session.
    """
    if nhl_game_id in _FS_ID_CACHE:
        return _FS_ID_CACHE[nhl_game_id]

    def get_team_keyword(team_name):
        if not team_name: return ""
        if "Utah" in team_name: return "utah"
        return team_name.split()[-1].lower()

    home_kw = get_team_keyword(home)
    away_kw = get_team_keyword(away)

    local_driver = False
    if driver is None:
        driver = get_driver()
        local_driver = True

    fs_id = None
    try:
        driver.get("https://www.flashscore.fr/hockey/usa/nhl/calendrier/")
        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "event__match")))
        for row in driver.find_elements(By.CSS_SELECTOR, ".event__match"):
            try:
                home_txt = row.find_element(
                    By.CLASS_NAME, "event__homeParticipant").text.lower()
                away_txt = row.find_element(
                    By.CLASS_NAME, "event__awayParticipant").text.lower()
                if home_kw and away_kw and home_kw in home_txt and away_kw in away_txt:
                    fs_id = row.get_attribute("id").replace("g_4_", "")
                    break

            except Exception as e:
                logger.error(f"_resolve_flashscore_id : {e}")
    except Exception as e:
        logger.error(f"_resolve_flashscore_id : {e}")
    finally:
        if local_driver:
            driver.quit()

    if fs_id:
        _FS_ID_CACHE[nhl_game_id] = fs_id
        logger.info(f"[Scraper] {home} vs {away} → FS id={fs_id}")
    else:
        logger.warning(f"ID Flashscore introuvable pour {home} vs {away}")
    return fs_id

def get_lineups(match_id, home="", away="", driver=None):
    """
    Scrape les compos depuis Flashscore.

    match_id peut être :
      - NHL game ID numérique (ex: '2025021027') → résolu en ID Flashscore via calendrier
      - ID Flashscore alphanumérique (ex: 'ScbBd4Qi') → URL directe (fallback Flashscore)

    home / away sont utilisés pour le matching Flashscore quand match_id est un NHL ID.
    main_bot.py les passe automatiquement via m['home'] et m['away'].
    """
    if match_id.isdigit() and len(match_id) >= 9:
        fs_id = _resolve_flashscore_id(match_id, home, away, driver)
        if not fs_id:
            return "compo pas dispo"
    else:
        fs_id = match_id

    url = f"https://www.flashscore.fr/match/{fs_id}/"

    local_driver = False
    if driver is None:
        driver = get_driver()
        local_driver = True

    try:
        driver.get(url)
        wait = WebDriverWait(driver, 10)

        tabs = wait.until(EC.presence_of_all_elements_located(
            (By.CSS_SELECTOR, FS_TAB_SELECTOR)))
        
        found_compos_tab = False
        for tab in tabs:
            if "COMPOS" in tab.text.upper() or "LINEUPS" in tab.text.upper():
                driver.execute_script("arguments[0].click();", tab)
                found_compos_tab = True
                break

        if not found_compos_tab:
            logger.info(f"[Scraper] {home} vs {away} : compo pas encore dispo (onglet absent)")
            return "compo pas dispo"

        try:
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, FS_PLAYER_NAME_SELECTOR)))
            time.sleep(2)
        except:
            time.sleep(3)                                                

        full_list = []

        # Sélecteur principal
        els = driver.find_elements(By.CSS_SELECTOR, FS_PLAYER_NAME_SELECTOR)
        
        # Fallback si le sélecteur principal ne trouve rien
        if not els:
            for fallback_sel in FS_PLAYER_NAME_FALLBACK:
                els = driver.find_elements(By.CSS_SELECTOR, fallback_sel)
                if els:
                    logger.info(f"[Scraper] Sélecteur principal cassé, fallback '{fallback_sel}' utilisé.")
                    break
            if not els:
                logger.warning(f"[Scraper] AUCUN sélecteur CSS ne fonctionne pour les compos. Structure Flashscore modifiée ?")
                return "compo pas dispo"

        for e in els:
            name = e.text.strip()
            if name and not name.startswith('(') and not name.isdigit() and name.upper() not in ["V", "D", "?", "P"]:
                full_list.append(name)

        if not is_valid_lineup(full_list):
            logger.warning(f"[Scraper] Compo invalide (trop courte ou pub détectée) : {len(full_list)} joueurs trouvés pour {home} vs {away}")
            return "compo pas dispo"

        return {
            "goalDom": full_list[0],
            "goalext": full_list[6],
            "f1_dom":  ", ".join(full_list[1:6]),
            "f1_ext":  ", ".join(full_list[7:12]),
            "f2_dom":  ", ".join(full_list[12:17]),
            "f2_ext":  ", ".join(full_list[17:22]),
        }

    except Exception as e:
        logger.error(f"get_lineups {fs_id} : {e}")
        return "compo pas dispo"
    finally:
        if local_driver:
            driver.quit()

class ScraperDriverContext:
    """
    Context manager that provides a persistent selenium webdriver instance
    to prevent starting/quitting Brave repeatedly during a wave scan.
    """
    def __init__(self):
        self.driver = None

    def __enter__(self):
        self.driver = get_driver()
        return self.driver

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.driver:
            self.driver.quit()
            self.driver = None

if __name__ == "__main__":
    print("=== Test schedule (API NHL) ===")
    matches = get_scheduled_matches()
    for m in matches:
        print(f"  [{m['id']}] {m['home']} vs {m['away']} @ {m['time']}")

    if matches:
        m = matches[0]
        print(f"\n=== Test lineups : {m['home']} vs {m['away']} ===")
        result = get_lineups(m["id"], m["home"], m["away"])
        if isinstance(result, dict):
            for k, v in result.items():
                print(f"  {k}: {v}")
        else:
            print(f"  → {result}")
