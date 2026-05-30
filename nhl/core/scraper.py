import time
import os
import sys
import logging
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(time, 'tzset'):
    os.environ['TZ'] = 'Europe/Paris'
    time.tzset()

load_dotenv()
logger = logging.getLogger("NHL.Scraper")

import config.constants as constants

NHL_BASE = "https://api-web.nhle.com"
ROTOWIRE_URL = "https://www.rotowire.com/hockey/nhl-lineups.php"

# Cache pour RotoWire
_ROTOWIRE_CACHE = {
    "timestamp": 0,
    "soup": None
}
CACHE_TTL_SECONDS = 300  # 5 minutes

def _nhl_date():
    now = datetime.now()
    if now.hour < 12:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")

def _utc_to_local(utc_str):
    try:
        from calendar import monthrange
        dt = datetime.strptime(utc_str[:19], "%Y-%m-%dT%H:%M:%S")

        def last_sunday(year, month):
            last_day = monthrange(year, month)[1]
            d = datetime(year, month, last_day)
            return d - timedelta(days=(d.weekday() + 1) % 7)

        dst_start = last_sunday(dt.year, 3).replace(hour=1)
        dst_end = last_sunday(dt.year, 10).replace(hour=1)
        offset = 2 if dst_start <= dt < dst_end else 1
        return (dt + timedelta(hours=offset)).strftime("%d.%m. %H:%M")
    except Exception:
        return ""

def get_scheduled_matches(url=""):
    date_str = _nhl_date()
    try:
        r = requests.get(f"{NHL_BASE}/v1/schedule/{date_str}", timeout=10)
        if r.status_code != 200:
            raise Exception(f"HTTP {r.status_code}")
        data = r.json()
    except Exception as e:
        logger.error(f"[Scraper] API NHL schedule indisponible ({e})")
        return []

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
            home_full  = constants.TEAM_ABBR_TO_FULL.get(home_abbr, home_abbr)
            away_full  = constants.TEAM_ABBR_TO_FULL.get(away_abbr, away_abbr)
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

def _get_rotowire_soup():

    now = time.time()
    if _ROTOWIRE_CACHE["soup"] is not None and (now - _ROTOWIRE_CACHE["timestamp"] < CACHE_TTL_SECONDS):
        return _ROTOWIRE_CACHE["soup"]
        
    try:
        r = requests.get(ROTOWIRE_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            _ROTOWIRE_CACHE["soup"] = soup
            _ROTOWIRE_CACHE["timestamp"] = now
            return soup
        else:
            logger.error(f"[Scraper] Erreur RotoWire HTTP {r.status_code}")
    except Exception as e:
        logger.error(f"[Scraper] Exception RotoWire: {e}")
    
    return None

def _parse_rotowire_team(ul_element) -> dict:
    team_data = {
        "goalie": "",
        "lines": {"LINE 1": [], "LINE 2": [], "LINE 3": [], "LINE 4": [], "POWER PLAY #1": [], "POWER PLAY #2": []},
        "injuries": set()
    }
    
    if not ul_element:
        return team_data

    # Gardien
    goalie_item = ul_element.select_one('.lineup__player-highlight')
    if goalie_item:
        a_tag = goalie_item.select_one('a')
        if a_tag:
            team_data["goalie"] = a_tag.text.strip()
            
    # Lignes et Blessures
    current_title = None
    for li in ul_element.find_all('li', recursive=False):
        if 'lineup__title' in li.get('class', []):
            current_title = li.text.strip().upper()
        elif 'lineup__player' in li.get('class', []):
            a_tag = li.select_one('a')
            if not a_tag: continue
            name = a_tag.text.strip()
            
            if current_title == "INJURIES":
                team_data["injuries"].add(name)
            elif current_title in team_data["lines"]:
                team_data["lines"][current_title].append(name)
                
    return team_data

def get_lineups(match_id, home="", away=""):
    soup = _get_rotowire_soup()
    if not soup:
        logger.warning("[Scraper] Impossible de charger RotoWire.")
        return "compo pas dispo"
        
    blocks = soup.select('.lineup.is-nhl')
    target_block = None
    
    def normalize(t): 
        t_low = t.lower()
        if "utah" in t_low or "mammoth" in t_low: return "utah"
        if "blues" in t_low: return "blues" # st. louis
        if "maple leafs" in t_low: return "leafs"
        if "red wings" in t_low: return "wings"
        if "blue jackets" in t_low: return "jackets"
        if "golden knights" in t_low: return "knights"
        return t.split()[-1].lower() if t else ""
    
    home_norm = normalize(home)
    away_norm = normalize(away)
    
    for b in blocks:
        away_el = b.select_one('.lineup__mteam.is-visit')
        home_el = b.select_one('.lineup__mteam.is-home')
        if not away_el or not home_el: continue
        
        wl_away = away_el.select_one('.lineup__wl')
        if wl_away: wl_away.extract()
        wl_home = home_el.select_one('.lineup__wl')
        if wl_home: wl_home.extract()
        
        rw_away = normalize(away_el.text.strip())
        rw_home = normalize(home_el.text.strip())
        
        if (home_norm in rw_home or rw_home in home_norm) and (away_norm in rw_away or rw_away in away_norm):
            target_block = b
            break
            
    if not target_block:
        logger.info(f"[Scraper] {home} vs {away} : introuvable sur RotoWire.")
        return "compo pas dispo"

    away_data = _parse_rotowire_team(target_block.select_one('.lineup__list.is-visit'))
    home_data = _parse_rotowire_team(target_block.select_one('.lineup__list.is-home'))

    if not away_data["goalie"] or not home_data["goalie"]:
        logger.info(f"[Scraper] {home} vs {away} : Gardiens complets non trouvés.")
        return "compo pas dispo"

    def filter_injuries(lines_list, injuries_set):
        return ", ".join([p for p in lines_list if p not in injuries_set])

    def get_line_players(data, primary_key, fallback_key):
        return data["lines"].get(primary_key, []) or data["lines"].get(fallback_key, [])

    f1_ext = filter_injuries(get_line_players(away_data, "LINE 1", "POWER PLAY #1"), away_data["injuries"])
    f2_ext = filter_injuries(get_line_players(away_data, "LINE 2", "POWER PLAY #2"), away_data["injuries"])
    
    f1_dom = filter_injuries(get_line_players(home_data, "LINE 1", "POWER PLAY #1"), home_data["injuries"])
    f2_dom = filter_injuries(get_line_players(home_data, "LINE 2", "POWER PLAY #2"), home_data["injuries"])

    if len(f1_ext) < 3 or len(f1_dom) < 3:
        logger.info(f"[Scraper] {home} vs {away} : Lignes d'attaque vides ou invalides.")
        return "compo pas dispo"

    return {
        "goalDom": home_data["goalie"],
        "goalext": away_data["goalie"],
        "f1_dom":  f1_dom,
        "f1_ext":  f1_ext,
        "f2_dom":  f2_dom,
        "f2_ext":  f2_ext,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("=== Test schedule ===")
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
            print(f"  > {result}")
