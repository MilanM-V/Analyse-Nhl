# Analyse-Nhl

[![GitHub stars](https://img.shields.io/github/stars/MilanM-V/Analyse-Nhl?style=social)](https://github.com/MilanM-V/Analyse-Nhl)

**Analyse-Nhl** est un bot quantitatif de paris sportifs NHL spécialisé sur les marchés **Passeurs** et **Pointeurs**. Il utilise des modèles XGBoost entraînés avec validation croisée temporelle (Time-Series Split) pour identifier les "Value Bets" avec un avantage mathématique réel (EV > 5%) sur les bookmakers.

---

## Performances Réelles (Audit V4 — Données Hors-Échantillon)

Résultats calculés **uniquement sur des cotes réelles** de bookmakers, sans aucune imputation ni overfitting :

### Paris Simples

| Marché | Volume | Winrate | ROI |
| :--- | :--- | :--- | :--- |
| **Passeurs** | 217 | ~55% | **+15.0%** |
| **Pointeurs** | 91 | ~65% | **+16.7%** |
| ~~Buteurs~~ | — | — | **Désactivé** (ROI -26%) |

### Combinés (Duo)

| Type de Combiné | Volume | Winrate | ROI |
| :--- | :--- | :--- | :--- |
| **Même Joueur (Passe+Point)** | 36 | 44.4% | **+56.8%** |
| **Intra-Match (Passeur+Pointeur)** | 108 | 46.3% | **+50.3%** |
| **Inter-Match (Passeur+Passeur)** | 3991 | 30.8% | **+22.6%** |
| Inter-Match (Passeur+Pointeur) | 965 | 37.6% | +13.4% |
| ~~Inter-Match (Pointeur+Pointeur)~~ | 208 | 37.0% | **-2.7%** ❌ |

> **Règle d'or** : Ne jamais combiner plus de 2 sélections. Les Trios (3 joueurs) ont un ROI de -6.6%.

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
