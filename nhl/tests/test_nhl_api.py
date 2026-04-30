import requests

date_test = "2024-03-20"
resp = requests.get(f"https://api-web.nhle.com/v1/schedule/{date_test}").json()
for gw in resp.get("gameWeek", []):
    if gw["date"] == date_test:
        for g in gw.get("games", []):
            if g.get("gameState") in ('FINAL', 'OFF'):
                gid = g["id"]
                box = requests.get(f"https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore").json()
                print("Game:", g["awayTeam"]["abbrev"], "@", g["homeTeam"]["abbrev"])
                players = box.get('playerByGameStats', {}).get('homeTeam', {}).get('forwards', [])
                if players:
                    print("Example:", players[0]["name"]["default"], players[0].get("goals", 0))
                break
