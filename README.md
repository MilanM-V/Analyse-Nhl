# BetEngine — Plateforme Multi-Sport de Paris Quantitatifs

> Bot autonome de paris sportifs basé sur l'Expected Value (EV > 5%), le Kelly Criterion, et les probabilités bayésiennes. Multi-sport, modulaire, déployé sur VPS avec supervision intelligente.

---

## Sports Actifs

| Sport | Status | Marchés |
|-------|--------|---------|
| 🏒 **NHL** | ✅ Production V18 | Passeur, Pointeur |
| ⚾ **MLB** | 🔧 Collecte de données | Strikeouts pitcher, Hits/HR batter |
| 🏀 **NBA** | 📋 Planifié | Combinés PRA (Points + Rebounds + Assists) |
| ⚽ **Foot** | 💤 Futur | Marchés de niche (corners, cartons, tirs cadrés) |

---

## Architecture

```
bet2/
├── shared/                  # Code commun à tous les sports
│   ├── telegram_hub.py      # Envoi centralisé Telegram (POST HTTP)
│   ├── base_bot.py          # Classe abstraite BaseSportBot
│   ├── portfolio.py         # Portefeuille simulé (100 U, SQLite)
│   └── utils.py             # Retry HTTP, normalisation noms
│
├── nhl/                     # 🏒 Bot NHL (Production)
│   ├── config/              # settings.toml, probas.json, constants.py
│   ├── core/                # bot_logic, market_filter, kelly, scraper, odds, updater...
│   ├── data/                # Pipeline async NHL API → CSV
│   ├── main_bot.py          # Point d'entrée NHL
│   └── dashboard.py         # Dashboard Streamlit NHL
│
├── mlb/                     # ⚾ Bot MLB (Harvester)
│   ├── core/harvester.py    # Collecte boxscores MLB API
│   └── main_bot.py          # Point d'entrée MLB
│
├── vps/                     # Scripts VPS
│   └── watchdog.py          # Superviseur intelligent multi-sport
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
