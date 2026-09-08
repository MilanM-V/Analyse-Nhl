"""
core/ensemble_model.py — Architecture d'Ensemble Multi-Boosting NHL.

Combine XGBoost, LightGBM et CatBoost sous validation croisée temporelle
stricte (TimeSeriesSplit) avec calibration isotonique et pondération convexe.
Permet d'utiliser soit l'Ensemble complet (Blending), soit le modèle Champion
pour chaque marché spécifique.
"""
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.model_selection import TimeSeriesSplit
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, roc_auc_score
from scipy.optimize import minimize

from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from catboost import CatBoostClassifier


class NHLEnsembleClassifier(BaseEstimator, ClassifierMixin):
    """Classifieur d'Ensemble pour les marchés NHL (Buteurs & Passeurs).

    Combine XGBoost, LightGBM et CatBoost via Blending pondéré convexe
    optimisé sur le Brier Score avec validation temporelle stricte.
    """

    def __init__(self, market: str = "but", mode: str = "ensemble", n_splits: int = 3, random_state: int = 42):
        """
        Args:
            market: 'but' ou 'ast'.
            mode: 'ensemble' (blending pondéré des 3) ou 'champion' (sélectionne le meilleur).
            n_splits: Nombre de folds temporels pour TimeSeriesSplit.
            random_state: Seed aléatoire pour reproductibilité.
        """
        self.market = market
        self.mode = mode
        self.n_splits = n_splits
        self.random_state = random_state
        self.models_ = {}
        self.weights_ = None
        self.best_model_name_ = None
        self.calibrated_models_ = {}
        self.classes_ = np.array([0, 1])

    def _load_optimal_params(self) -> Dict[str, Any]:
        """Tente de charger les hyperparamètres Optuna optimaux."""
        import os
        import json
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "optimal_hyperparams.json")
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get(self.market, {})
            except Exception:
                pass
        return {}

    def _init_base_models(self, scale_pos: float) -> Dict[str, Any]:
        opt_params = self._load_optimal_params()
        
        # 1. CatBoost
        cat_p = {
            'iterations': 100, 'depth': 3, 'learning_rate': 0.05,
            'scale_pos_weight': scale_pos, 'random_seed': self.random_state,
            'verbose': False
        }
        if 'CatBoost' in opt_params:
            cat_p.update(opt_params['CatBoost'])
            cat_p['scale_pos_weight'] = scale_pos
            cat_p['verbose'] = False
        cat = CatBoostClassifier(**cat_p)

        # 2. LightGBM
        lgb_p = {
            'n_estimators': 100, 'max_depth': 3, 'num_leaves': 7, 'learning_rate': 0.05,
            'scale_pos_weight': scale_pos, 'random_state': self.random_state,
            'subsample': 0.8, 'colsample_bytree': 0.8, 'verbose': -1
        }
        if 'LightGBM' in opt_params:
            lgb_p.update(opt_params['LightGBM'])
            lgb_p['scale_pos_weight'] = scale_pos
            lgb_p['verbose'] = -1
        lgb = LGBMClassifier(**lgb_p)

        # 3. XGBoost
        xgb_p = {
            'n_estimators': 100, 'max_depth': 3, 'learning_rate': 0.05,
            'scale_pos_weight': scale_pos, 'eval_metric': 'logloss',
            'random_state': self.random_state, 'subsample': 0.8, 'colsample_bytree': 0.8,
            'verbosity': 0
        }
        if 'XGBoost' in opt_params:
            xgb_p.update(opt_params['XGBoost'])
            xgb_p['scale_pos_weight'] = scale_pos
            xgb_p['eval_metric'] = 'logloss'
            xgb_p['verbosity'] = 0
        xgb = XGBClassifier(**xgb_p)

        return {'CatBoost': cat, 'LightGBM': lgb, 'XGBoost': xgb}

    def fit(self, X: np.ndarray, y: np.ndarray):
        """Entraîne et calibre les modèles de base puis optimise les poids."""
        n_samples = len(y)
        n_pos = int(sum(y))
        n_neg = int(n_samples - n_pos)
        scale_pos = n_neg / max(1, n_pos)

        n_splits_actual = min(self.n_splits, max(2, n_samples // 400))
        tscv = TimeSeriesSplit(n_splits=n_splits_actual)

        base_models = self._init_base_models(scale_pos)
        self.models_ = base_models
        oof_preds = {name: np.zeros(n_samples) for name in base_models}

        # 1. Génération Out-of-Fold temporelle
        for train_idx, val_idx in tscv.split(X):
            X_tr, y_tr = X[train_idx], y[train_idx]
            X_val = X[val_idx]
            fold_models = self._init_base_models(scale_pos)
            for name, model in fold_models.items():
                model.fit(X_tr, y_tr)
                oof_preds[name][val_idx] = model.predict_proba(X_val)[:, 1]

        # 2. Entraînement et calibration de chaque modèle complet
        brier_scores = {}
        first_val_idx = list(tscv.split(X))[0][1][0]
        y_val_oof = y[first_val_idx:]

        for name, model in base_models.items():
            calibrated = CalibratedClassifierCV(model, method='sigmoid', cv=tscv)
            calibrated.fit(X, y)
            self.calibrated_models_[name] = calibrated

            oof_slice = oof_preds[name][first_val_idx:]
            brier_scores[name] = brier_score_loss(y_val_oof, oof_slice)

        # Identification du meilleur modèle individuel (Champion)
        self.best_model_name_ = min(brier_scores, key=brier_scores.get)

        # 3. Optimisation des poids de Blending (convexe sur Brier)
        X_oof_matrix = np.column_stack([oof_preds[name][first_val_idx:] for name in base_models])

        def brier_objective(weights):
            w = np.array(weights)
            w = w / np.sum(w)
            pred = sum(w[i] * X_oof_matrix[:, i] for i in range(len(w)))
            return brier_score_loss(y_val_oof, pred)

        n_models = len(base_models)
        init_w = [1.0 / n_models] * n_models
        bounds = [(0, 1) for _ in range(n_models)]
        cons = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0})
        opt_res = minimize(brier_objective, init_w, bounds=bounds, constraints=cons)
        self.weights_ = opt_res.x / np.sum(opt_res.x)

        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Prédit les probabilités [P(0), P(1)] selon le mode choisi."""
        if self.mode == "champion" and self.best_model_name_:
            # Utilise le meilleur modèle calibré
            p1 = self.calibrated_models_[self.best_model_name_].predict_proba(X)[:, 1]
        else:
            # Mode 'ensemble' : combinaison pondérée des prédictions calibrées
            p1 = np.zeros(len(X))
            for i, (name, model) in enumerate(self.calibrated_models_.items()):
                p1 += self.weights_[i] * model.predict_proba(X)[:, 1]

        # Garantir le clipping [0.01, 0.99] pour éviter division par zéro dans Kelly
        p1 = np.clip(p1, 0.005, 0.995)
        p0 = 1.0 - p1
        return np.column_stack([p0, p1])

    def predict(self, X: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        """Prédit la classe binaire selon le seuil."""
        probas = self.predict_proba(X)[:, 1]
        return (probas >= threshold).astype(int)
