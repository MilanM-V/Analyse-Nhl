import os
import time
import csv
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
import sys

logger = logging.getLogger("NHL_Bot")
logger.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

file_handler = RotatingFileHandler('bot.log', maxBytes=5*1024*1024, backupCount=5)
file_handler.setFormatter(formatter)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(stream_handler)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN_TEST")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID_TEST")
BRAVE_PATH = os.getenv("BRAVE_PATH")
FOLDER_NAME = "stats"

if not os.path.exists(FOLDER_NAME):
    os.makedirs(FOLDER_NAME)

def get_super_light_driver():
    options = Options()
    options.binary_location = BRAVE_PATH
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    prefs = {"profile.managed_default_content_settings.images": 2,
             "profile.managed_default_content_settings.stylesheets": 2}
    options.add_experimental_option("prefs", prefs)
    if sys.platform.startswith('linux'):
        service = Service(log_output=os.devnull)
    else:
        service = Service(log_output=os.devnull)
        service.creation_flags = 0x08000000 
    return webdriver.Chrome(options=options, service=service)

def convert_toi(toi_str):
    try:
        if ':' in toi_str:
            m, s = map(int, toi_str.split(':'))
            return m + s/60.0
        return float(toi_str)
    except:
        return toi_str

def process_nst_file(url, filename, is_player_data=True):
    clean_url = url + "&print=csv" if "print=csv" not in url else url
    output_path = os.path.join(FOLDER_NAME, filename)
    
    logger.info(f" Extraction : {filename}...")
    driver = get_super_light_driver()
    
    try:
        driver.get(clean_url)
        wait = WebDriverWait(driver, 60)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(5)
        
        raw_text = driver.find_element(By.TAG_NAME, "body").text
        lines = raw_text.splitlines()
        
        if is_player_data == "on_ice":
            NB_STATS = 38
            headers_oi = ["", "Player", "Team", "Position",
                          "GP", "TOI", "CF", "CA", "CF%", "FF", "FA", "FF%",
                          "SF", "SA", "SF%", "GF", "GA", "GF%",
                          "xGF", "xGA", "xGF%", "SCF", "SCA", "SCF%",
                          "HDCF", "HDCA", "HDCF%", "HDGF", "HDGA", "HDGF%",
                          "On-Ice SH%", "On-Ice SV%", "PDO",
                          "Off. Zone Starts", "Neu. Zone Starts", "Def. Zone Starts",
                          "On The Fly Starts", "Off. Zone Start %",
                          "Off. Zone Faceoffs", "Neu. Zone Faceoffs",
                          "Def. Zone Faceoffs", "Off. Zone Faceoff %"]

            data = []
            for line in lines:
                line = line.strip()
                if not line or not line[0].isdigit(): continue
                parts = line.split()
                if len(parts) < NB_STATS + 4: continue  

                stats_part = parts[-NB_STATS:]
                stats_part[1] = convert_toi(stats_part[1])
                position = parts[-(NB_STATS + 1)]
                idx = parts[0]

                remaining = parts[1:-(NB_STATS + 1)]
                team_parts, player_parts = [], []
                found_team = False
                for i in range(len(remaining) - 1, -1, -1):
                    part = remaining[i]
                    if not found_team and (part.isupper() or ',' in part or '.' in part):
                        team_parts.insert(0, part)
                    else:
                        found_team = True
                        player_parts.insert(0, part)

                row = [idx, " ".join(player_parts), " ".join(team_parts), position] + stats_part
                data.append(row)

            df = pd.DataFrame(data, columns=headers_oi)
            df.to_csv(output_path, index=False, quoting=csv.QUOTE_ALL, encoding='utf-8-sig')

        elif is_player_data:
            headers = ["", "Player", "Team", "Position", "GP", "TOI", "Goals", "Total Assists", 
                       "First Assists", "Second Assists", "Total Points", "IPP", "Shots", "SH%", 
                       "ixG", "iCF", "iFF", "iSCF", "iHDCF", "Rush Attempts", "Rebounds Created", 
                       "PIM", "Total Penalties", "Minor", "Major", "Misconduct", "Penalties Drawn", 
                       "Giveaways", "Takeaways", "Hits", "Hits Taken", "Shots Blocked", 
                       "Faceoffs Won", "Faceoffs Lost", "Faceoffs %"]
            
            data = []
            for line in lines:
                line = line.strip()
                if not line or not line[0].isdigit(): continue
                parts = line.split()
                if len(parts) < 32: continue
                
                stats_part = parts[-31:]
                stats_part[1] = convert_toi(stats_part[1])
                position = parts[-32]
                idx = parts[0]
                
                remaining = parts[1:-32]
                team_parts, player_parts = [], []
                found_team = False
                for i in range(len(remaining)-1, -1, -1):
                    part = remaining[i]
                    if not found_team and (part.isupper() or ',' in part or '.' in part):
                        team_parts.insert(0, part)
                    else:
                        found_team = True
                        player_parts.insert(0, part)
                
                row = [idx, " ".join(player_parts), " ".join(team_parts), position] + stats_part
                data.append(row)

            df = pd.DataFrame(data, columns=headers)
            df.to_csv(output_path, index=False, quoting=csv.QUOTE_ALL, encoding='utf-8-sig')
        
        else:
            clean_lines = [l for l in lines if l.strip() and not l.startswith(("Login", "Games", "Players", "Teams", "Tools", "Trivia"))]
            with open(output_path, "w", encoding="utf-8-sig") as f:
                f.write("\n".join(clean_lines))

        logger.info(f" Terminé : {output_path}")

    except Exception as e:
        logger.info(f" Erreur sur {filename} : {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    jobs = [
        ["https://www.naturalstattrick.com/teamtable.php?fromseason=20252026&thruseason=20252026&stype=2&sit=5v5&score=all&rate=n&team=all&loc=B&gpf=10&fd=&td=", "team.csv", False],
        ["https://www.naturalstattrick.com/playerteams.php?fromseason=20252026&thruseason=20252026&stype=2&sit=all&score=all&stdoi=std&rate=n&team=ALL&pos=S&loc=B&toi=0&gpfilt=none&fd=&td=&tgp=410&lines=single&draftteam=ALL", "Player Season Totals.csv", True],
        ["https://www.naturalstattrick.com/games.php?fromseason=20252026&thruseason=20252026&stype=2&sit=5v5&loc=B&team=All&rate=n", "match.csv", False],
        ["https://www.naturalstattrick.com/playerteams.php?stdoi=oi","on_ice.csv", "on_ice"],
        ["https://www.naturalstattrick.com/playerteams.php?fromseason=20252026&thruseason=20252026&stype=2&sit=all&score=all&stdoi=std&rate=n&team=ALL&pos=S&loc=B&toi=0&gpfilt=gpteam&fd=&td=&tgp=10&lines=single&draftteam=ALL", "last 10.csv", True],
        ["https://www.naturalstattrick.com/playerteams.php?fromseason=20252026&thruseason=20252026&stype=2&sit=5v4&score=all&stdoi=std&rate=n&team=ALL&pos=S&loc=B&toi=0&gpfilt=none&fd=&td=&tgp=410&lines=single&draftteam=ALL", "power play.csv", True],
        ["https://www.naturalstattrick.com/playerteams.php?fromseason=20252026&thruseason=20252026&stype=2&sit=all&score=all&stdoi=std&rate=n&team=ALL&pos=G&loc=B&toi=0&gpfilt=none&fd=&td=&lines=single", "goalies.csv", True],

    ]

    for url, name, is_player in jobs:
        process_nst_file(url, name, is_player)

    logger.info(f"\n TOUS LES FICHIERS SONT DANS LE DOSSIER : {os.path.abspath(FOLDER_NAME)}")