import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from core import scraper

def run_scraper_test():
    print("=== TEST FALLBACK STRATEGY FLASHSCORE ===")
    driver = scraper.get_driver()
    url = "https://www.flashscore.fr/match/6y2eDP9e/"
    print(f"Ouverture de {url}...")
    
    try:
        driver.get(url)
        wait = WebDriverWait(driver, 10)

        # 1. Clic sur l'onglet COMPOS
        tabs = wait.until(EC.presence_of_all_elements_located(
            (By.CSS_SELECTOR, '[data-testid="wcl-tab"]')))
        for tab in tabs:
            if "COMPOS" in tab.text.upper() or "LINEUPS" in tab.text.upper():
                driver.execute_script("arguments[0].click();", tab)
                break
                
        time.sleep(2)
        
        # --- TEST 1 : data-testid
        print("\n--- TEST 1 : data-testid (wcl-scores-simple-text-01) ---")
        try:
            els1 = driver.find_elements(By.CSS_SELECTOR, '[data-testid="wcl-scores-simple-text-01"]')
            names1 = [e.text.strip() for e in els1 if e.text.strip()]
            print(f"Trouvé {len(names1)} éléments.")
            if len(names1) >= 20: 
                print(f"Exemple : {names1[:3]}")
        except Exception as e:
            print("Test 1 failed:", e)

        # --- TEST 2 : Liens /joueur/
        print("\n--- TEST 2 : href contenant /joueur/ ---")
        try:
            els2 = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/joueur/"]')
            names2 = [e.text.strip() for e in els2 if e.text.strip()]
            print(f"Trouvé {len(names2)} éléments.")
            if len(names2) >= 20:
                print(f"Exemple : {names2[:3]}")
        except Exception as e:
            print("Test 2 failed:", e)

        # --- TEST 3 : Noms de classe Participant
        print("\n--- TEST 3 : classes type '*participantName*' ---")
        try:
            els3 = driver.find_elements(By.XPATH, "//*[contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'participantname') or contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'playername')]")
            names3 = [e.text.strip() for e in els3 if e.text.strip()]
            print(f"Trouvé {len(names3)} éléments.")
            if len(names3) >= 20:
                print(f"Exemple : {names3[:3]}")
        except Exception as e:
            print("Test 3 failed:", e)

    except Exception as e:
        print("Erreur globale :", e)
    finally:
        driver.quit()
        print("\nTest terminé.")

if __name__ == "__main__":
    run_scraper_test()
