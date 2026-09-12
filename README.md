# BetEngine â Plateforme Multi-Sport de Paris Quantitatifs

> Bot autonome de paris sportifs basÃ© sur l'Expected Value (EV > 5%), le Kelly Criterion, et les probabilitÃ©s bayÃ©siennes. Multi-sport, modulaire, dÃ©ployÃ© sur VPS avec supervision intelligente.

---

## Sports Actifs

| Sport | Status | Marchés | Modèle & Méthode |
|-------|--------|---------|------------------|
| 🏒 **NHL** | ✅ **Production V20** | Buteur, Passeur | Ensemble Multi-Boosting Calibré (CatBoost/LGBM/XGB) sur ère moderne 2018-2026 + Priors 2008-2018 (Holdout OOS Buteurs AUC 0.69, Walk-Forward ROI +19.8%) |
| ⚾ **MLB** | ✅ **Production V2** | Strikeouts pitcher | XGBoost Statcast (ROI +21.4%) |
| 🏀 **NBA** | 📋 Planifié | Combinés PRA | Points + Rebounds + Assists |
| ⚽ **Foot** | 💤 Futur | Marchés de niche | Corners, cartons, tirs cadrés |

---

## Architecture

```text
bet2/
├── shared/                  # Code commun à tous les sports
│   ├── telegram_hub.py      # Envoi centralisé Telegram (POST HTTP)
│   ├── odds_api.py          # Client unifié The Odds API avec Line Shopping
│   ├── base_bot.py          # Classe abstraite BaseSportBot
│   ├── portfolio.py         # Portefeuille simulé (100 U, SQLite)
│   └── kelly.py             # Calculateur du Kelly dynamique (1/6ème & 1/8ème)
│
├── nhl/                     # 🏒 Bot NHL (Production V20)
│   ├── config/              # settings.toml, optimal_hyperparams.json
│   ├── core/                # bot_logic, market_filter, parlay_engine, ensemble_model...
│   ├── data/                # Super-dataset Parquet (307k matchs), bot_database.db
│   ├── models/              # ml_model_but.pkl, ml_model_ast.pkl
│   ├── scripts/             # build_historical_dataset, train_models, walk_forward...
│   └── main_bot.py          # Point d'entrée NHL
│
├── mlb/                     # ⚾ Bot MLB (Production V2)
│   ├── core/                # bot_logic, market_filter, database...
│   ├── scripts/             # build_dataset, train_models, ab_test_features
│   └── main_bot.py          # Point d'entrée MLB
│
└── vps/                     # Scripts VPS
    ├── watchdog.py          # Superviseur intelligent multi-sport
    └── backup_manager.py    # Sauvegarde auto DB par Email
```

---

## Pipeline de Paris Quantitatif (Cycle NHL V20)

```
UPDATE STATS (NHL API) → SCAN LINEUPS (Top 9 Forwards) → INFERENCE ML (CatBoost/LGBM/XGB)
     → SCRAPE ODDS & LINE SHOPPING (The Odds API : Winamax, Betclic, Unibet, Pinnacle)
     → VALIDATION EV ADAPTATIVE (8% <2.00, 5% [2.00-3.50], 10% >3.50)
     → KELLY STAKING DYNAMIQUE (1/6ème Passeurs EV+, 1/8ème Buteurs)
     → GÉNÉRATEUR COMBINÉS SYNERGIQUES (Same-Game PP1 & Cross-Match)
     → ENVOI TELEGRAM → LOG DB & DATA LAKE → RÉSOLUTION AUTO BOXSCORES
```

---

## Installation

```bash
git clone https://github.com/MilanM-V/Analyse-Nhl.git
cd Analyse-Nhl

python -m venv venv
# Windows
venv\Scripts\activate
# Linux
source venv/bin/activate

pip install -r requirements.txt
```

> **PrÃ©requis** : Python 3.12+, Brave Browser (Selenium).

CrÃ©er un fichier `.env` Ã  la racine :
```env
TELEGRAM_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
BRAVE_PATH=C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe
api_odds=your_odds_api_key
```

---

## Utilisation

### Local

```bash
# Bot NHL complet
python nhl/main_bot.py

# Dashboard Streamlit NHL
streamlit run nhl/dashboard.py

# Bot MLB (harvester uniquement)
python mlb/main_bot.py
```

### VPS (Production)

```bash
# DÃ©ployer via git push puis sur le VPS :
systemctl daemon-reload
systemctl restart watchdog-betengine

# Le watchdog gÃ¨re automatiquement :
# - DÃ©marrage de tous les bots sport configurÃ©s
# - RedÃ©marrage ciblÃ© aprÃ¨s chaque git push (par dossier modifiÃ©)
# - Restart auto si un bot crash
```

#### Service systemd (`/etc/systemd/system/watchdog-betengine.service`)

```ini
[Unit]
Description=BetEngine Multi-Sport Watchdog
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/BetEngine
ExecStart=/opt/BetEngine/venv/bin/python3 vps/watchdog.py
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
# Installer le service
sudo cp watchdog-betengine.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable watchdog-betengine
sudo systemctl start watchdog-betengine

# VÃ©rifier
sudo systemctl status watchdog-betengine
journalctl -u watchdog-betengine -f
```

> **Important** : Le watchdog lance et supervise tous les bots. Tu n'as plus besoin de services systemd sÃ©parÃ©s pour chaque bot. Un seul service (`watchdog-betengine`) suffit.

---

## Documentation

| Document | Contenu |
|----------|---------|
| [PROJECT_VISION.md](PROJECT_VISION.md) | Vision complÃ¨te, stratÃ©gies par sport, architecture cible, roadmap |
| [VPS_WATCHDOG.md](VPS_WATCHDOG.md) | SpÃ©cification technique du watchdog VPS |

---

## Licence

Ce projet est sous licence MIT â voir le fichier [LICENSE](LICENSE) pour plus de dÃ©tails.

## Mises à jour récentes
- Nettoyage du code et corrections Flake8.

- Ajout d'un script d'évaluation des modèles (evaluate_models.py) pour la NHL.

- V19: Bot propulsé par des modèles Machine Learning dynamiques (XGBoost & Logistic Regression) avec générateur de combinés (Double Passeurs).

- Mise à jour du bot NHL (bot_logic.py) pour exploiter l'inférence asynchrone des modèles Scikit-Learn et XGBoost en production.

- Audit statistique des algorithmes (LightGBM vs XGBoost) et des stratégies de combinés ajouté dans optimization_report.md.

- Intégration de combinés synergiques Passeur-Passeur via combo_analysis.py après un test massif sur l'historique de la NHL (+123% ROI).


## 2026-05-31 - Bug Fixes
- Fixed ModuleNotFoundError by replacing local imports (from core, data, config) with absolute imports (from nhl.core, etc.).
- Fixed AssertionError in test_bot_logic (BUTEUR cap to 1.5).
- Fixed SessionNotCreatedException in test_dfo by forcing webdriver version_main=148.
- Updated test fixtures to use correct monkeypatch targets.

## 2026-09-07 - V20: ML Refactoring & Multi-Boosting Ensemble
- **P1/P2**: Correction data leakage â holdout temporel strict + scale_pos_weight dynamique + calibration isotonique.
- **P3/P6**: Scripts d'analyse statistique avancee (clv_analysis.py, significance_tests.py).
- **P4**: Walk-Forward Backtest 100% Out-of-Sample jour par jour avec re-entrainement periodique.
- **P5**: Features cles implied_prob et goalie_weakness.
- **P8 (Multi-Boosting Ensemble)**: Benchmark comparatif de XGBoost, LightGBM et CatBoost sous TimeSeriesSplit.
  - Buteurs : CatBoost champion absolu (AUC 0.6678, Brier 0.1509).
  - Passeurs : LightGBM champion (Brier 0.2352).
  - Architecture d'Ensemble deployee (NHLEnsembleClassifier dans nhl/core/ensemble_model.py) combinant les 3 algorithmes avec calibration isotonique.
- **P7 (Optuna Tuning)**: nhl/scripts/tune_hyperparams.py pour l'optimisation bayesienne des hyperparametres.
- **P9 (Seuils EV Adaptatifs)**: Seuils dynamiques selon la cote dans shared/kelly.py et settings.toml.
- **P10 (Features Trios & On-Ice)**: is_top6, linemate_synergy et team_scoring_env deployes.
- **Resultat Walk-Forward Final**: +26.06 U (+32.4% ROI global), Max Drawdown -9.52 U.

## 2026-09-08 - Forensic Audit & Profit Maximization Engine
- **Forensic Data Audit** : Détection et élimination de 453 doublons de logs dans la DB et correction de l'infiltration des défenseurs dans le backtest des buteurs. P&L corrigé Walk-Forward réel : **+6.53 U (+11.3% ROI)**, rendement journalier vérifié : **+0.82 U / jour actif** (+0.33 U / jour calendaire).
- **Débridage Top 9 (`market_filter.py`)** : Extension de la détection à l'ensemble du Top 9 et unités PP1/PP2 sans surcoût d'API (requêtes au niveau match).
- **Spécialisation Winamax (`shared/odds_api.py`, `formatter.py`)** : Priorisation absolue des cotes Winamax dans le scanner live et habillage Telegram dédié (`WINAMAX MYMATCH` pour les synergies intra-match et `WINAMAX COMBINÉ` pour les doubles passes).
- **Combinés Synergiques (`parlay_engine.py`)** : Génération des combinés corrélés Same-Game PP1 (+30% de synergie conjointe) et Cross-Match Double Passeurs.
- **Staking Kelly Dynamique (`shared/kelly.py`)** : Kelly 1/6ème sur les passes à fort Edge ($EV \ge 12\%$) et 1/8ème sur les buts (cap hard à 2.5 U).
- **Modèle Empirique Winamax sur 7 Saisons (`simulate_historical_odds.py`)** : Calibrage par régression sur les 235 cotes réelles de `nhl/bot_database.db` (MAE 0.40 buts, 0.15 passes). Bilan sur 19 167 paris : **+2 246.34 U (+2 246.34 €)** de profit net cumulé (**+13.2% ROI global net**, soit **+320.91 U / saison**).


## R�sultats du Backtest (2023-2025)
L'algorithme NHL a �t� test� avec l'API The-Odds-API sur plus de 5000 paris virtuels. ROI Global valid� en Out-of-Sample: **+37.9%**. Les Assists performent � +54.5% de ROI.

