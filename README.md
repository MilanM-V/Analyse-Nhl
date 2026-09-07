# BetEngine — Plateforme Multi-Sport de Paris Quantitatifs

> Bot autonome de paris sportifs basé sur l'Expected Value (EV > 5%), le Kelly Criterion, et les probabilités bayésiennes. Multi-sport, modulaire, déployé sur VPS avec supervision intelligente.

---

## Sports Actifs

| Sport | Status | Marchés |
|-------|--------|---------|
| 🏒 **NHL** | ✅ Production V18 | Passeur, Pointeur |
| ⚾ **MLB** | ✅ **Production V2** | Strikeouts pitcher (XGBoost Statcast) |
| 🏀 **NBA** | 📋 Planifié | Combinés PRA (Points + Rebounds + Assists) |
| ⚽ **Foot** | 💤 Futur | Marchés de niche (corners, cartons, tirs cadrés) |

---

## Architecture

```text
bet2/
├── shared/                  # Code commun à tous les sports
│   ├── telegram_hub.py      # Envoi centralisé Telegram (POST HTTP)
│   ├── odds_api.py          # Client unifié The Odds API (NHL/MLB)
│   ├── base_bot.py          # Classe abstraite BaseSportBot
│   ├── portfolio.py         # Portefeuille simulé (100 U, SQLite)
│   └── kelly.py             # Calculateur du Kelly Criterion fractionnel
│
├── nhl/                     # 🏒 Bot NHL (Production V18)
│   ├── config/              # settings.toml, probas.json, constants.py
│   ├── core/                # bot_logic, market_filter, services, loaders...
│   ├── data/                # Bases de données NHL
│   ├── main_bot.py          # Point d'entrée NHL
│   └── dashboard.py         # Dashboard Streamlit NHL
│
├── mlb/                     # ⚾ Bot MLB (Beta V2)
│   ├── core/                # bot_logic, market_filter, database...
│   ├── scripts/             # build_dataset, train_models, ab_test_features
│   ├── data/                # Base SQLite MLB (Statcast)
│   ├── main_bot.py          # Point d'entrée MLB
│   └── dashboard.py         # Dashboard Streamlit MLB
│
├── vps/                     # Scripts VPS
│   ├── watchdog.py          # Superviseur intelligent multi-sport
│   └── backup_manager.py    # Sauvegarde auto DB par Email
│
├── PROJECT_VISION.md        # Vision complète du projet
└── VPS_WATCHDOG.md          # Spec technique du watchdog
```

---

## Pipeline de Paris (Cycle NHL)

```
UPDATE STATS (NHL API) → SCAN LINEUPS (Flashscore) → FILTRAGE MARCHÉ (seuils stats)
     → SCRAPE ODDS (The Odds API) → VALIDATION EV > 5% → KELLY SIZING (1/8ème)
     → ENVOI TELEGRAM → LOG DB + CSV → RÉSOLUTION AUTO (Boxscore API)
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

> **Prérequis** : Python 3.12+, Brave Browser (Selenium).

Créer un fichier `.env` à la racine :
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
# Déployer via git push puis sur le VPS :
systemctl daemon-reload
systemctl restart watchdog-betengine

# Le watchdog gère automatiquement :
# - Démarrage de tous les bots sport configurés
# - Redémarrage ciblé après chaque git push (par dossier modifié)
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

# Vérifier
sudo systemctl status watchdog-betengine
journalctl -u watchdog-betengine -f
```

> **Important** : Le watchdog lance et supervise tous les bots. Tu n'as plus besoin de services systemd séparés pour chaque bot. Un seul service (`watchdog-betengine`) suffit.

---

## Documentation

| Document | Contenu |
|----------|---------|
| [PROJECT_VISION.md](PROJECT_VISION.md) | Vision complète, stratégies par sport, architecture cible, roadmap |
| [VPS_WATCHDOG.md](VPS_WATCHDOG.md) | Spécification technique du watchdog VPS |

---

## Licence

Ce projet est sous licence MIT – voir le fichier [LICENSE](LICENSE) pour plus de détails.

## Mises � jour r�centes
- Nettoyage du code et corrections Flake8.

- Ajout d'un script d'�valuation des mod�les (evaluate_models.py) pour la NHL.

- V19: Bot propuls� par des mod�les Machine Learning dynamiques (XGBoost & Logistic Regression) avec g�n�rateur de combin�s (Double Passeurs).

- Mise � jour du bot NHL (bot_logic.py) pour exploiter l'inf�rence asynchrone des mod�les Scikit-Learn et XGBoost en production.

- Audit statistique des algorithmes (LightGBM vs XGBoost) et des strat�gies de combin�s ajout� dans optimization_report.md.

- Int�gration de combin�s synergiques Passeur-Passeur via combo_analysis.py apr�s un test massif sur l'historique de la NHL (+123% ROI).


## 2026-05-31 - Bug Fixes
- Fixed ModuleNotFoundError by replacing local imports (from core, data, config) with absolute imports (from nhl.core, etc.).
- Fixed AssertionError in test_bot_logic (BUTEUR cap to 1.5).
- Fixed SessionNotCreatedException in test_dfo by forcing webdriver version_main=148.
- Updated test fixtures to use correct monkeypatch targets.

## 2026-09-07 - V20: ML Refactoring & Multi-Boosting Ensemble
- **P1/P2**: Correction data leakage — holdout temporel strict + scale_pos_weight dynamique + calibration isotonique.
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
