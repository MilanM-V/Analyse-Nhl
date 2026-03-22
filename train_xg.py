"""
train_xg.py
Entraîne un modèle xG sur les vraies données de tirs NHL (play-by-play en cache).
Sauvegarde le modèle dans stats/xg_model.pkl
Lance : python train_xg.py
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
MODEL_PATH = "./xg_model.pkl"  

SHOT_TYPE_ENCODE = {
    'wrist':     1.0,
    'snap':      0.85,
    'backhand':  0.75,
    'tip-in':    1.2,  
    'deflected': 1.15,
    'slap':      0.65,
    'wrap-around': 0.70,
    'bat':       0.60,
}

def extract_features(play):
    """Extrait les features d'un tir pour le modèle xG."""
    det  = play.get('details', {})
    x    = det.get('xCoord', 0)
    y    = det.get('yCoord', 0)
    zone = det.get('zoneCode', '')
    shot_type = det.get('shotType', 'wrist')
    sit  = play.get('situationCode', '1551')

    if zone != 'O':
        return None

    bx   = 89.0
    ax   = abs(x)
    dist = math.sqrt((bx - ax)**2 + y**2)
    angle = math.degrees(math.atan2(abs(y), bx - ax)) if (bx - ax) > 0 else 90.0

    is_pp = sit[1] != sit[2] and sit[1] > sit[2]   
    is_pk = sit[1] != sit[2] and sit[1] < sit[2]   
    is_5v5 = sit == '1551'

    shot_val = SHOT_TYPE_ENCODE.get(shot_type, 0.8)

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
    ]

FEATURE_NAMES = [
    'distance', 'angle', 'distance_sq', 'sin_angle',
    'x_abs', 'shot_type_val',
    'is_pp', 'is_5v5', 'inv_distance'
]

print("Chargement des données de tirs...")
X_raw, y_raw = [], []
n_skipped = 0

for f in sorted(glob.glob(f"{CACHE_DIR}/pbp_cache_*.json")):
    with open(f) as fp:
        pbp = json.load(fp)

    for play in pbp.get('plays', []):
        t = play.get('typeDescKey', '')
        if t not in ('shot-on-goal', 'goal'):
            continue

        feats = extract_features(play)
        if feats is None:
            n_skipped += 1
            continue

        label = 1 if t == 'goal' else 0
        X_raw.append(feats)
        y_raw.append(label)

X = np.array(X_raw)
y = np.array(y_raw)

print(f"Tirs chargés  : {len(X)}")
print(f"Buts          : {y.sum()} ({y.mean()*100:.1f}%)")
print(f"Ignorés (zone D/N): {n_skipped}")

print("\nEntraînement du modèle...")

scaler = StandardScaler()
X_sc = scaler.fit_transform(X)

lr = LogisticRegression(max_iter=1000, class_weight='balanced')
lr_scores = cross_val_score(lr, X_sc, y, cv=5, scoring='roc_auc')
lr.fit(X_sc, y)
lr_auc = roc_auc_score(y, lr.predict_proba(X_sc)[:,1])
lr_brier = brier_score_loss(y, lr.predict_proba(X_sc)[:,1])
print(f"\nLogistic Regression:")
print(f"  AUC (CV 5-fold): {lr_scores.mean():.4f} ± {lr_scores.std():.4f}")
print(f"  AUC (train):     {lr_auc:.4f}")
print(f"  Brier score:     {lr_brier:.4f}")

gb = GradientBoostingClassifier(
    n_estimators=100, max_depth=3,
    learning_rate=0.1, subsample=0.8,
    random_state=42
)
gb_scores = cross_val_score(gb, X, y, cv=5, scoring='roc_auc')
gb.fit(X, y)
gb_auc = roc_auc_score(y, gb.predict_proba(X)[:,1])
gb_brier = brier_score_loss(y, gb.predict_proba(X)[:,1])
print(f"\nGradient Boosting:")
print(f"  AUC (CV 5-fold): {gb_scores.mean():.4f} ± {gb_scores.std():.4f}")
print(f"  AUC (train):     {gb_auc:.4f}")
print(f"  Brier score:     {gb_brier:.4f}")

best_model  = gb if gb_scores.mean() > lr_scores.mean() else lr
best_name   = "GradientBoosting" if gb_scores.mean() > lr_scores.mean() else "LogisticRegression"
best_scaler = scaler if best_model is lr else None
print(f"\nMeilleur modèle: {best_name}")

print("\nImportance des features:")
if best_model is gb:
    importances = gb.feature_importances_
else:
    importances = abs(lr.coef_[0])
    importances = importances / importances.sum()

for name, imp in sorted(zip(FEATURE_NAMES, importances), key=lambda x: x[1], reverse=True):
    bar = '█' * int(imp * 50)
    print(f"  {name:<20} {imp:.3f}  {bar}")

print("\nCalibration (xG moyen par tranche de distance):")
df_check = pd.DataFrame(X, columns=FEATURE_NAMES)
df_check['label']  = y
df_check['xg_pred'] = gb.predict_proba(X)[:,1]

for lo, hi in [(0,10),(10,20),(20,30),(30,40),(40,60)]:
    sub = df_check[(df_check['distance']>=lo) & (df_check['distance']<hi)]
    if len(sub) < 10: continue
    real = sub['label'].mean()*100
    pred = sub['xg_pred'].mean()*100
    print(f"  {lo:>2}-{hi:>2} pieds: réel={real:>5.1f}%  prédit={pred:>5.1f}%  n={len(sub)}")

model_data = {
    'model':         best_model,
    'scaler':        scaler if best_model is lr else None,
    'model_name':    best_name,
    'feature_names': FEATURE_NAMES,
    'auc_cv':        float(gb_scores.mean() if best_model is gb else lr_scores.mean()),
    'n_train':       len(X),
    'goal_rate':     float(y.mean()),
}

with open(MODEL_PATH, 'wb') as f:
    pickle.dump(model_data, f)

print(f"\nModele sauvegarde : {MODEL_PATH}")
print(f"AUC CV : {model_data['auc_cv']:.4f}")
print(f"Entraine sur {len(X)} tirs reels NHL")