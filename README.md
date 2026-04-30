# Analyse-Nhl

[![GitHub stars](https://img.shields.io/github/stars/MilanM-V/Analyse-Nhl?style=social)](https://github.com/MilanM-V/Analyse-Nhl)

**Analyse-Nhl** est un bot quantitatif de paris sportifs NHL spécialisé sur les marchés **Passeurs** et **Pointeurs**. Il utilise des modèles XGBoost entraînés avec validation croisée temporelle (Time-Series Split) pour identifier les "Value Bets" avec un avantage mathématique réel (EV > 5%) sur les bookmakers.

---

## Performances Réelles (Audit Base de Données — Avril 2026)

Résultats calculés **strictement sur la base de données historique (`bot_database.db`) avec des cotes réelles** sans filtre EV trompeur. L'audit a révélé que les cotes des Passeurs et Pointeurs sont souvent trop basses pour compenser leur taux de réussite réel.

### Paris Simples (Flat Betting 1U)

| Marché | Winrate Réel | ROI Brut | Diagnostic |
| :--- | :--- | :--- | :--- |
| **Buteurs** | 32.5% | **+3.8%** | **Seul marché rentable sans filtre** (Cote moy: 3.20) |
| **Passeurs** | 47.0% | **-9.2%** | Cotes trop écrasées par les bookmakers (Cote moy: 1.96) |
| **Pointeurs** | 52.3% | **-15.8%** | Surévalué (Cote moy: 1.64). La proba (58%) surestime le WR réel (52%). |

> ⚠️ **Attention au biais de calibration** : Le dashboard simulait des ROI de >+40% sur les Passeurs/Pointeurs car le filtre "EV > 5%" se base sur des probabilités théoriques (ex: 58.8% de winrate pour les Pointeurs). Or l'audit prouve que le vrai winrate avec de réelles cotes n'est que de 52.3%. Le bot validait donc des paris à EV négatif en pensant qu'ils étaient rentables.

### Stratégie Recommandée suite à l'Audit

1. **Buteurs** : C'est paradoxalement le marché offrant le plus de "Value" (+3.8% ROI net) sans aucun filtre. Leurs cotes élevées compensent largement le faible winrate.
2. **Filtres EV** : Nécessite une recalibration complète des probabilités bayésiennes dans `probas.json` pour refléter la vraie performance des algorithmes.

---

## Architecture

```
core/
├── bot_logic.py      # Orchestration : scan → filtre → odds → Kelly → Telegram
├── market_filter.py  # Filtrage par marché (Passeurs/Pointeurs uniquement)
├── kelly.py          # Kelly Criterion fractionnaire (1/8) + filtre EV > 5%
├── formatter.py      # Messages Telegram (Singles + Top 3 Combinés)
├── odds_scraper.py   # Intégration The Odds API (chirurgicale par match)
├── scraper.py        # Scraping Flashscore/RotoWire pour les compos
├── database.py       # SQLite (picks, picks_assists, picks_points, parlays)
├── loaders.py        # Chargement CSV (stats NHL, form, PP1, B2B)
├── updater.py        # Résolution automatique des résultats
└── services.py       # Telegram & Email

scripts/
├── train_models.py   # Entraînement XGBoost (TimeSeriesSplit, anti-overfitting)
├── estimate_ev.py    # Simulation de profit réel (simples + combinés)
├── omega_audit_v4.py # Audit honnête complet (simples vs duos vs trios)
└── combo_analysis.py # Analyse exhaustive des types de combinés

config/
├── settings.toml     # Seuils de filtrage, Kelly caps, mode playoff
└── probas.json       # Probabilités bayésiennes dynamiques

models/
├── xg_model_but.pkl  # Modèle buteurs (désactivé)
├── xg_model_ast.pkl  # Modèle passeurs (actif)
└── xg_model_pts.pkl  # Modèle pointeurs (actif)
```

---

## Installation

```bash
git clone https://github.com/MilanM-V/Analyse-Nhl.git
cd Analyse-Nhl

python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

> **Prérequis** : Python 3.12+, navigateur Brave (Selenium).

---

## Utilisation

```bash
# Tableau de bord Streamlit
streamlit run dashboard.py

# Bot complet (scraping + prédictions + alertes Telegram)
python main_bot.py

# Ré-entraîner les modèles IA
python scripts/train_models.py

# Audit de rentabilité
python scripts/omega_audit_v4.py

# Analyse des combinés
python scripts/combo_analysis.py
```

---

## Licence

Ce projet est sous licence MIT – voir le fichier [LICENSE](LICENSE) pour plus de détails.
