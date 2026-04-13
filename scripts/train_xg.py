"""
train_xg.py
Entraîne un modèle xG sur les vraies données de tirs NHL (play-by-play en cache).
Sauvegarde le modèle dans models/xg_shot_model.pkl
Lance : python scripts/train_xg.py
"""
import os, json, glob, math
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_score
from sklearn.metrics import roc_auc_score, brier_score_loss
import joblib
import warnings
warnings.filterwarnings('ignore')

CACHE_DIR  = "./stats/cache"
MODEL_PATH = "models/xg_shot_model.pkl"

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
        dist, angle, dist ** 2, math.sin(math.radians(angle)),
        ax, shot_val, int(is_pp), int(is_5v5), 1 / (dist + 1),
        slot, is_rebound, is_rush, period_norm, 
    ]

FEATURE_NAMES = [
    'distance', 'angle', 'distance_sq', 'sin_angle',
    'x_abs', 'shot_type_val', 'is_pp', 'is_5v5', 'inv_distance',
    'is_slot', 'is_rebound', 'is_rush', 'period',     
]

def main():
    print("Chargement des donnees de tirs...")
    X_raw, y_raw = [], []
    n_skipped = 0
    
    if not os.path.exists(CACHE_DIR):
        print(f"Erreur : Le dossier {CACHE_DIR} n'existe pas.")
        return

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

            prev_shot_time = play.get('timeInPeriod', '00:00')
            prev_play      = play

    if not X_raw:
        print("Aucun tir trouvé dans le cache.")
        return

    X = np.array(X_raw)
    y = np.array(y_raw)

    print(f"Tirs charges       : {len(X)}")
    print(f"Buts               : {y.sum()} ({y.mean()*100:.1f}%)")
    print("\nEntrainement du modele...")

    scaler = StandardScaler()
    X_sc   = scaler.fit_transform(X)

    lr = LogisticRegression(max_iter=1000, class_weight='balanced')
    lr_scores = cross_val_score(lr, X_sc, y, cv=5, scoring='roc_auc')
    lr.fit(X_sc, y)
    
    gb = GradientBoostingClassifier(n_estimators=100, max_depth=4, learning_rate=0.05, random_state=42)
    gb_scores = cross_val_score(gb, X, y, cv=5, scoring='roc_auc')
    gb.fit(X, y)

    best_model = gb if gb_scores.mean() > lr_scores.mean() else lr
    best_name  = "GradientBoosting" if gb_scores.mean() > lr_scores.mean() else "LogisticRegression"
    print(f"Meilleur modele : {best_name} (AUC CV: {max(gb_scores.mean(), lr_scores.mean()):.4f})")

    model_data = {
        'model':         best_model,
        'scaler':        scaler if best_model is lr else None,
        'model_name':    best_name,
        'feature_names': FEATURE_NAMES,
        'auc_cv':        float(max(gb_scores.mean(), lr_scores.mean())),
        'n_train':       len(X),
        'goal_rate':     float(y.mean()),
        'version':       'v14.3.1_shot',
    }

    joblib.dump(model_data, MODEL_PATH)
    print(f"\nModèle sauvegardé : {MODEL_PATH}")

    print("\nImportance des features:")
    importances = gb.feature_importances_ if best_model is gb else abs(lr.coef_[0])
    importances = importances / importances.sum()
    for name, imp in sorted(zip(FEATURE_NAMES, importances), key=lambda x: x[1], reverse=True):
        print(f"  {name:<20} {imp:.3f}  {'#' * int(imp * 30)}")

if __name__ == "__main__":
    main()
