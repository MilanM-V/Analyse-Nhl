import os
import requests
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("api_odds")

url = f"https://api.the-odds-api.com/v4/historical/sports/icehockey_nhl/odds"
params = {
    'apiKey': api_key, 
    'regions': 'us', 
    'markets': 'player_goal_scorer_anytime,player_assists',
    'date': '2023-11-15T23:00:00Z'
}
res = requests.get(url, params=params)
print("status_code:", res.status_code)
if res.status_code != 200:
    print(res.json())
else:
    data = res.json()
    print("Events found:", len(data.get('data', [])))
