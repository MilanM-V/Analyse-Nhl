# test.py
import pandas as pd
df = pd.read_csv('stats/last 10.csv')
print(f"Total: {len(df)}")
print(f"Team vides: {df['Team'].isna().sum()}")
print(df[['Player','Team']].head(10).to_string())