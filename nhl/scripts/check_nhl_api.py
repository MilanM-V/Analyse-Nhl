import requests
import json

date_str = "2026-03-28"
print(f"Checking schedule for {date_str}...")
try:
    sched = requests.get(f"https://api-web.nhle.com/v1/schedule/{date_str}", timeout=10).json()
    games = []
    for gw in sched.get("gameWeek", []):
        if gw["date"] == date_str:
            games = gw.get("games", [])
            break
    
    print(f"Found {len(games)} games.")
    for g in games:
        print(f"Game {g['id']}: {g['homeTeam']['abbrev']} vs {g['awayTeam']['abbrev']} - {g['gameState']}")
except Exception as e:
    print(f"Error: {e}")
