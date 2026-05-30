import undetected_chromedriver as uc
import time
import pytest

def test_dfo():
    print("Testing DailyFaceoff...")
    options = uc.ChromeOptions()
    options.headless = True
    chrome_path = uc.find_chrome_executable()
    if not chrome_path:
        pytest.skip("Chrome executable introuvable sur cette machine.")
    options.binary_location = chrome_path
    driver = uc.Chrome(options=options, version_main=148)
    
    driver.get("https://www.dailyfaceoff.com/teams/washington-capitals/line-combinations")
    time.sleep(3)
    html = driver.page_source
    
    print("Page length:", len(html))
    if "Ovechkin" in html:
        print("Scrape OK: Ovechkin found.")
    else:
        print("Ovechkin not found.")
    
    driver.quit()

if __name__ == "__main__":
    test_dfo()
