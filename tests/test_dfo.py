import undetected_chromedriver as uc
import time

def test_dfo():
    print("Testing DailyFaceoff...")
    options = uc.ChromeOptions()
    options.headless = True
    driver = uc.Chrome(options=options)
    
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
