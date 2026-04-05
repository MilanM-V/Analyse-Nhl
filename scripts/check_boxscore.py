import requests

gid = 2025021162 # CBJ vs DAL
print(f"Checking boxscore for game {gid}...")
try:
    box = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore", timeout=10).json()
    for side in ["homeTeam", "awayTeam"]:
        print(f"--- {side} ---")
        players_data = box.get('playerByGameStats', {}).get(side, {})
        all_players = players_data.get('forwards', []) + players_data.get('defense', [])
        for p in all_players[:10]:
            print(f"Name: {p.get('name', {}).get('default')}, Goals: {p.get('goals')}")
except Exception as e:
    print(f"Error: {e}")
