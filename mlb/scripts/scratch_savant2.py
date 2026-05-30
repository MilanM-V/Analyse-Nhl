import pybaseball
df = pybaseball.statcast_batter_exitvelo_barrels(2024)
print(df.columns.tolist())
