import pybaseball
print(dir(pybaseball))
try:
    df = pybaseball.statcast_batter_exitvelo_barrels(2024)
    print(df.head())
except Exception as e:
    print(e)
