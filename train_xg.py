"""
train_xg.py
Entraîne un modèle xG sur les vraies données de tirs NHL (play-by-play en cache).
Sauvegarde le modèle dans stats/xg_model.pkl
Lance : python train_xg.py

Features v2 (vs v1) :
  + is_rush       — tir en contre-attaque (événement précédent zone neutre/def < 4s)
  + is_rebound    — tir < 3s après un autre tir
  + is_slot       — tir depuis le slot (zone dangereuse devant le filet)
  + period        — période du match
"""
import os, json, glob, math, pickle
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_score
from sklearn.metrics import roc_auc_score, brier_score_loss
import warnings
warnings.filterwarnings('ignore')

CACHE_DIR  = "./stats/cache"
MODEL_PATH = "./xg_modelv2.pkl"

SHOT_TYPE_ENCODE = {
    'wrist':       1.00,
    'snap':        0.85,
    'backhand':    0.75,
    'tip-in':      1.20,
    'deflected':   1.15,
    'slap':        0.65,
    'wrap-around': 0.70,
    'bat':         0.60,
}

def _to_sec(ts):
    parts = ts.split(':')
    return int(parts[0]) * 60 + int(parts[1])

def _is_slot(ax, y):
    """Slot = devant le filet, x>69 et |y|<22 (coordonnées NHL)."""
    return int(ax >= 69 and abs(y) <= 15)

def extract_features(play, prev_play=None, prev_shot_time=None):
    det       = play.get('details', {})
    x         = det.get('xCoord', 0)
    y         = det.get('yCoord', 0)
    zone      = det.get('zoneCode', '')
    shot_type = det.get('shotType', 'wrist')
    sit       = play.get('situationCode', '1551')
    period    = play.get('periodDescriptor', {}).get('number', 1)
    time_in   = play.get('timeInPeriod', '00:00')

    if zone != 'O':
        return None

    bx    = 89.0
    ax    = abs(x)
    dist  = math.sqrt((bx - ax) ** 2 + y ** 2)
    angle = math.degrees(math.atan2(abs(y), bx - ax)) if (bx - ax) > 0 else 90.0

    is_pp  = len(sit) >= 3 and sit[1] != sit[2] and sit[1] > sit[2]
    is_5v5 = sit == '1551'
    shot_val = SHOT_TYPE_ENCODE.get(shot_type, 0.80)
    slot     = _is_slot(ax, y)

    is_rebound = 0
    if prev_shot_time is not None:
        try:
            delta = _to_sec(time_in) - _to_sec(prev_shot_time)
            if 0 < delta <= 4:
                is_rebound = 1
        except Exception:
            pass

    is_rush = 0
    if prev_play is not None:
        prev_zone = prev_play.get('details', {}).get('zoneCode', '')
        prev_time = prev_play.get('timeInPeriod', '00:00')
        if prev_zone in ('N', 'D'):
            try:
                delta = _to_sec(time_in) - _to_sec(prev_time)
                if 0 < delta <= 4:
                    is_rush = 1
            except Exception:
                pass

    period_norm = min(period, 4)

    return [
        dist,
        angle,
        dist ** 2,
        math.sin(math.radians(angle)),
        ax,
        shot_val,
        int(is_pp),
        int(is_5v5),
        1 / (dist + 1),
        slot,        
        is_rebound,  
        is_rush,     
        period_norm, 
    ]

FEATURE_NAMES = [
    'distance', 'angle', 'distance_sq', 'sin_angle',
    'x_abs', 'shot_type_val',
    'is_pp', 'is_5v5', 'inv_distance',
    'is_slot',    
    'is_rebound', 
    'is_rush',    
    'period',     
]

print("Chargement des donnees de tirs...")
X_raw, y_raw = [], []
n_skipped = 0
n_rebound = 0
n_rush    = 0
n_slot    = 0

for f in sorted(glob.glob(f"{CACHE_DIR}/pbp_cache_*.json")):
    with open(f) as fp:
        pbp = json.load(fp)

    plays          = pbp.get('plays', [])
    prev_play      = None
    prev_shot_time = None

    for play in plays:
        t = play.get('typeDescKey', '')

        if t not in ('shot-on-goal', 'goal'):
            prev_play = play
            continue

        feats = extract_features(play, prev_play, prev_shot_time)

        if feats is None:
            n_skipped += 1
            prev_play  = play
            continue

        label = 1 if t == 'goal' else 0
        X_raw.append(feats)
        y_raw.append(label)

        if feats[10]: n_rebound += 1
        if feats[11]: n_rush    += 1
        if feats[9]:  n_slot    += 1

        prev_shot_time = play.get('timeInPeriod', '00:00')
        prev_play      = play

X = np.array(X_raw)
y = np.array(y_raw)

print(f"Tirs charges       : {len(X)}")
print(f"Buts               : {y.sum()} ({y.mean()*100:.1f}%)")
print(f"Ignores (zone D/N) : {n_skipped}")
print(f"Dont slot          : {n_slot}  ({n_slot/max(len(X),1)*100:.1f}%)")
print(f"Dont rebounds      : {n_rebound}  ({n_rebound/max(len(X),1)*100:.1f}%)")
print(f"Dont rush          : {n_rush}  ({n_rush/max(len(X),1)*100:.1f}%)")

print("\nEntrainement du modele...")

scaler = StandardScaler()
X_sc   = scaler.fit_transform(X)

lr = LogisticRegression(max_iter=1000, class_weight='balanced')
lr_scores = cross_val_score(lr, X_sc, y, cv=5, scoring='roc_auc')
lr.fit(X_sc, y)
lr_auc   = roc_auc_score(y, lr.predict_proba(X_sc)[:, 1])
lr_brier = brier_score_loss(y, lr.predict_proba(X_sc)[:, 1])
print(f"\nLogistic Regression:")
print(f"  AUC (CV 5-fold) : {lr_scores.mean():.4f} +/- {lr_scores.std():.4f}")
print(f"  AUC (train)     : {lr_auc:.4f}")
print(f"  Brier score     : {lr_brier:.4f}")

gb = GradientBoostingClassifier(
    n_estimators=200, max_depth=4,
    learning_rate=0.05, subsample=0.8,
    random_state=42
)
gb_scores = cross_val_score(gb, X, y, cv=5, scoring='roc_auc')
gb.fit(X, y)
gb_auc   = roc_auc_score(y, gb.predict_proba(X)[:, 1])
gb_brier = brier_score_loss(y, gb.predict_proba(X)[:, 1])
print(f"\nGradient Boosting:")
print(f"  AUC (CV 5-fold) : {gb_scores.mean():.4f} +/- {gb_scores.std():.4f}")
print(f"  AUC (train)     : {gb_auc:.4f}")
print(f"  Brier score     : {gb_brier:.4f}")

best_model = gb if gb_scores.mean() > lr_scores.mean() else lr
best_name  = "GradientBoosting" if gb_scores.mean() > lr_scores.mean() else "LogisticRegression"
print(f"\nMeilleur modele : {best_name}")

print("\nImportance des features:")
if best_model is gb:
    importances = gb.feature_importances_
else:
    importances = abs(lr.coef_[0])
    importances = importances / importances.sum()

for name, imp in sorted(zip(FEATURE_NAMES, importances), key=lambda x: x[1], reverse=True):
    bar = '█' * int(imp * 50)
    print(f"  {name:<20} {imp:.3f}  {bar}")

print("\nCalibration par distance :")
df_check = pd.DataFrame(X, columns=FEATURE_NAMES)
df_check['label']   = y
df_check['xg_pred'] = gb.predict_proba(X)[:, 1]

for lo, hi in [(0, 10), (10, 20), (20, 30), (30, 40), (40, 60)]:
    sub = df_check[(df_check['distance'] >= lo) & (df_check['distance'] < hi)]
    if len(sub) < 10:
        continue
    real = sub['label'].mean() * 100
    pred = sub['xg_pred'].mean() * 100
    print(f"  {lo:>2}-{hi:>2} pieds : reel={real:>5.1f}%  predit={pred:>5.1f}%  n={len(sub)}")

print("\nImpact nouvelles features sur taux de but reel :")
for feat, label in [('is_slot', 'Slot'), ('is_rebound', 'Rebound'), ('is_rush', 'Rush')]:
    idx     = FEATURE_NAMES.index(feat)
    sub_yes = df_check[X[:, idx] == 1]
    sub_no  = df_check[X[:, idx] == 0]
    if len(sub_yes) > 10:
        print(f"  {label:<10} oui={sub_yes['label'].mean()*100:.1f}%  non={sub_no['label'].mean()*100:.1f}%  (n_oui={len(sub_yes)})")

model_data = {
    'model':         best_model,
    'scaler':        scaler if best_model is lr else None,
    'model_name':    best_name,
    'feature_names': FEATURE_NAMES,
    'auc_cv':        float(gb_scores.mean() if best_model is gb else lr_scores.mean()),
    'n_train':       len(X),
    'goal_rate':     float(y.mean()),
    'version':       2,
}

with open(MODEL_PATH, 'wb') as f:
    pickle.dump(model_data, f)

print(f"\nModele sauvegarde : {MODEL_PATH}")
print(f"AUC CV            : {model_data['auc_cv']:.4f}")
print(f"Entraine sur      : {len(X)} tirs reels NHL")
