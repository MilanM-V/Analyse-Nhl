"""
data/xg_model.py — LogisticRegression fallback model for expected goals (xG).
Includes thread-safe initialization to prevent duplicate training.
"""

import os
import math
import pickle
import threading
import logging
import sys
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

# Ajout du dossier racine au sys.path pour permettre l'exécution standalone
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("NHL_Bot")

SHOT_TYPE_ENCODE = {
    'wrist': 1.0, 'snap': 0.85, 'backhand': 0.75,
    'tip-in': 1.2, 'deflected': 1.15, 'slap': 0.65,
    'wrap-around': 0.70, 'bat': 0.60,
}

# The path needs to be relative to the project root or absolute. Assuming run from root.
XG_MODEL_PATH = "models/xg_model.pkl"

def _xg_features(x, y, shot_type='wrist', is_pp=False, is_5v5=True,
                  is_slot=False, is_rebound=False, is_rush=False, period=1):
    bx   = 89.0
    ax   = abs(x)
    dist = math.sqrt((bx - ax)**2 + y**2)
    angle = math.degrees(math.atan2(abs(y), bx - ax)) if (bx - ax) > 0 else 90.0
    shot_val = SHOT_TYPE_ENCODE.get(shot_type, 0.8)
    slot = int(ax >= 69 and abs(y) <= 15)
    return [
        dist, angle, dist**2, math.sin(math.radians(angle)),
        ax, shot_val, int(is_pp), int(is_5v5), 1/(dist+1),
        slot, int(is_rebound), int(is_rush), min(period, 4),
    ]

class XGModel:
    def __init__(self):
        self._load_or_train()

    def _load_or_train(self):
        if os.path.exists(XG_MODEL_PATH):
            try:
                # Utilise joblib.load pour charger le dictionnaire contenant le modèle XGBoost
                data = joblib.load(XG_MODEL_PATH)
                self.model   = data['model']
                self.scaler  = data.get('scaler')
                self.use_pkl = True
                
                version = data.get('version', 'unknown')
                logger.info(f"[xG model] Modèle RÉEL chargé — Version: {version}")
                return
            except Exception as e:
                logger.warning(f"[xG model] Erreur chargement joblib: {e}")

        logger.warning("⚠️ MODÈLE xG SYNTHÉTIQUE — Le vrai modèle (.pkl) n'a pas été trouvé. Un modèle factice est généré. Veillez à entraîner un vrai modèle !")
        self.use_pkl = False
        self.scaler  = StandardScaler()
        np.random.seed(42)
        n = 10000
        xs = np.random.uniform(25, 89, n)
        ys = np.random.uniform(-30, 30, n)
        feats = np.array([_xg_features(xi, yi) for xi, yi in zip(xs, ys)])
        dist  = feats[:, 0]
        prob  = 1 / (1 + np.exp(0.12 * (dist - 18)))
        labels = (np.random.random(n) < prob).astype(int)
        X_sc = self.scaler.fit_transform(feats)
        self.model = LogisticRegression(max_iter=1000)
        self.model.fit(X_sc, labels)

    def predict(self, x, y, shot_type='wrist', sit='1551', is_rebound=False, is_rush=False, period=1):
        is_pp  = len(sit) >= 3 and sit[1] > sit[2]
        is_5v5 = sit == '1551'
        feats  = np.array([_xg_features(x, y, shot_type, is_pp, is_5v5, False, is_rebound, is_rush, period)])
        if self.scaler:
            feats = self.scaler.transform(feats)
        return float(self.model.predict_proba(feats)[0][1])

def is_high_danger(x, y, zone_code, home_defending_side, event_owner_team_id, home_team_id):
    if zone_code != 'O': return False
    ax = abs(x)
    dist = math.sqrt((89 - ax)**2 + y**2)
    in_slot = ax >= 54 and abs(y) <= 9
    return in_slot or dist < 20

# Thread-safe singleton for the model
_xg_lock = threading.Lock()
_xg_model = None

def get_xg_model():
    global _xg_model
    if _xg_model is None:
        with _xg_lock:
            if _xg_model is None:
                _xg_model = XGModel()
    return _xg_model
