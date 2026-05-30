from pybaseball import batting_stats
df = batting_stats(2023)
print("Columns containing 'EV' or 'Angle':")
print([c for c in df.columns if 'EV' in c or 'Angle' in c or 'Velocity' in c])
print(df.head())
