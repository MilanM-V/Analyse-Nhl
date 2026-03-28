import pandas as pd
import math

def calculate_base_qs_defense(ixg, hdcf, sog, atoi, season_g, oish, pdo,
                          ga_g, pk_pct, hdca_g, is_pp1, is_home, is_b2b,
                          is_backup, consec):
    qs = 3.5

    if oish > 16.0:   qs -= 2.0
    elif oish > 14.0: qs -= 1.0
    if is_b2b: qs -= 1.5

    g1 = 0.0
    ixg_score = (4.0 if ixg >= 0.55 else
                 3.0 if ixg >= 0.45 else
                 2.5 if ixg >= 0.38 else
                 1.5 if ixg >= 0.30 else
                 0.5 if ixg >= 0.22 else
                -1.0)
    g1 += ixg_score

    if hdcf >= 3.0:   g1 += 2.5
    elif hdcf >= 2.5: g1 += 1.5
    elif hdcf >= 2.0: g1 += 0.75
    elif hdcf >= 1.5: g1 += 0.5
    else:             g1 -= 0.5

    if sog >= 3.5:   g1 += 1.0
    elif sog >= 2.5: g1 += 0.5

    qs += min(g1, 5.0)

    g2 = 0.0
    if ga_g >= 3.00:   g2 += 2.5
    elif ga_g >= 2.80: g2 += 1.5
    elif ga_g >= 2.50: g2 += 0.5
    elif ga_g < 2.30:  g2 -= 0.5

    if pk_pct < 77.0:   g2 += 1.0
    elif pk_pct < 80.0: g2 += 0.5
    elif pk_pct > 85.0: g2 -= 0.5

    if hdca_g >= 12.0:   g2 += 0.75
    elif hdca_g >= 10.0: g2 += 0.375
    elif hdca_g <= 5.0:  g2 -= 0.5

    qs += min(g2, 3.5)

    g3 = 0.0
    if atoi >= 20.0:   g3 += 1.5
    elif atoi >= 18.0: g3 += 0.75

    if pdo < 96.0:    g3 += 2.0
    elif pdo < 98.0:  g3 += 1.0
    elif pdo > 103.0: g3 -= 1.0
    elif pdo > 100.0: g3 -= 0.5

    if season_g >= 0.35:   g3 += 0.5
    elif season_g >= 0.25: g3 += 0.25

    qs += min(g3, 3.0)

    if is_pp1:
        if pk_pct < 77.0:   qs += 2.5
        elif pk_pct > 83.0: qs += 0.5
        else:               qs += 1.75

    if is_backup and ga_g >= 2.8:
        qs += 2.0
    elif is_backup:
        qs += 0.75

    if consec >= 3:
        qs += 1.0
    elif consec == 2:
        qs += 0.5

    qs_normalized = 2 + 10 * (1 / (1 + math.exp(-0.45 * (qs - 6.5))))
    return qs_normalized

print("Chargement CSV...")
df = pd.read_csv('./stats/skaters_all.csv', usecols=['playerId', 'name', 'position', 'situation', 'I_F_goals', 'I_F_xGoals', 'I_F_shotsOnGoal', 'I_F_highDangerShots', 'icetime'], low_memory=False)

def_df = df[df['position'].isin(['D', 'LD', 'RD'])]
def_all = def_df[def_df['situation'] == 'all']
print(f"Lignes def: {len(def_all)}")

"""
Since making a full simulation with proper window rolling for defensemen is very long, 
I will just apply the V10 logic to see what def score looks like.
"""
