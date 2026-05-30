import pandas as pd
from pybaseball import statcast

df = statcast(start_dt='2023-05-01', end_dt='2023-05-02')
print("Columns:", df.columns.tolist())
print(df[['game_date', 'batter', 'events', 'launch_speed', 'launch_angle', 'home_team']].head(10))
