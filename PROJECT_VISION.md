# 🎯 BetEngine — Vision Multi-Sport & Architecture

> **Dernière mise à jour** : 2026-04-30
> **Auteur** : Milan
> **Status** : Phase 1 — Restructuration en cours

---

## 1. Vision Globale

**BetEngine** est une plateforme de paris sportifs quantitative et modulaire.
L'objectif est de construire un moteur de paris intelligent, sport par sport, avec :

- Un **bot autonome par sport** (scan, filtrage, odds, sizing, envoi, résolution)
- Un **portefeuille simulé** global qui track la bankroll à travers tous les sports
- Une **centralisation Telegram** unique (un seul bot, un seul canal)
- Un **dashboard local** (Streamlit) pour visualiser la performance tous sports confondus
- Un **watchdog VPS intelligent** qui redémarre uniquement les bots impactés par un `git push`

---

## 2. Sports Supportés

| Sport | Status | Marchés Ciblés | API Source |
|-------|--------|----------------|------------|
| 🏒 **NHL** | ✅ Production (V18) | Passeur, Pointeur (Buteur désactivé) | NHL API + The Odds API |
| ⚾ **MLB** | 🔧 Harvester (collecte) | Strikeouts pitcher, Hits/HR batter | MLB Stats API + The Odds API |
| 🏀 **NBA** | 📋 Planifié | PRA Combinés (Points+Rebounds+Assists) | NBA API + The Odds API |
| ⚽ **Foot** | 💤 Idée future | Marchés de niche (corners, cartons, tirs cadrés) | À définir |
| 🎾 **Tennis** | 💤 Idée future | Match winner, Sets O/U | À définir |

> **Règle d'or** : On ne lance un nouveau sport en production que quand le précédent est **stable et backtesté**. Le NHL est le modèle de référence.

### Stratégies de Marché par Sport

#### 🏒 NHL — Player Props Classiques
Le moteur NHL cible les **player props individuels** : un joueur marquera-t-il un but, une passe, un point ? Le filtrage repose sur les stats avancées (HDCF, SOG, ATOI, CF%) et les matchups défensifs adverses. Marchés actifs : **Passeur** et **Pointeur**.

#### ⚾ MLB — Pitcher & Batter Props
Le MLB vise les **strikeouts pitcher** (le pitcher K-era-t-il plus de X joueurs ?) et les **batter props** (hits, home runs). L'avantage : les stats baseball sont extrêmement granulaires et les marchés player props sont encore sous-exploités.

#### 🏀 NBA — Combinés PRA (Points + Rebounds + Assists)
Le NBA ne vise **PAS** les props simples (trop efficients). La stratégie cible les **combinés PRA** — un joueur dépassera-t-il X points + Y rebounds + Z assists. Ces marchés multi-dimensionnels offrent des edges car les bookmakers peinent à pricer les corrélations entre les 3 métriques.

#### ⚽ Foot — Marchés de Niche & Petits Championnats
Le foot ne vise **PAS** les marchés mainstream (1X2, Over/Under buts). La stratégie cible les **marchés de niche** où les bookmakers sont moins affûtés :
- **Nombre de corners** par match ou par équipe
- **Cartons jaunes** (total ou par joueur)
- **Tirs cadrés** (shots on target)
- **Petits championnats** (Ligue 2, Eredivisie, ligues nordiques) où la modélisation des bookmakers est plus faible

L'avantage : moins de volume = moins d'attention des bookmakers = plus d'inefficiences.

---

## 3. Architecture Cible

```
bet2/
│
├── shared/                          # 🔧 Code commun à TOUS les sports
│   ├── __init__.py
│   ├── telegram_hub.py              # Point unique d'envoi Telegram (POST API)
│   ├── telegram_commands.py         # Polling unique pour /roi, /portfolio, /force_*
│   ├── portfolio.py                 # Bankroll tracker (100 U initial, SQLite)
│   ├── base_bot.py                  # Classe abstraite BaseSportBot
│   ├── base_odds.py                 # Interface commune pour The Odds API
│   ├── base_database.py             # Utilitaires DB communs
│   └── utils.py                     # Helpers partagés (retry, normalize, etc.)
│
├── nhl/                             # 🏒 Bot NHL (refactoré depuis l'existant)
│   ├── config/
│   │   ├── settings.toml            # Seuils et paramètres NHL
│   │   ├── settings.py              # Loader TOML → namespace
│   │   ├── constants.py             # Mappings équipes NHL
│   │   └── probas.json              # Probabilités bayésiennes NHL
│   ├── core/
│   │   ├── bot_logic.py             # NhlBot(BaseSportBot)
│   │   ├── market_filter.py         # Filtrage Buteur/Passeur/Pointeur
│   │   ├── scraper.py               # Flashscore + NHL API lineups
│   │   ├── odds_scraper.py          # The Odds API (NHL player props)
│   │   ├── database.py              # Schéma SQLite NHL
│   │   ├── updater.py               # Résolution résultats via Boxscore API
│   │   ├── kelly.py                 # Quarter Kelly NHL
│   │   ├── formatter.py             # Formatage Telegram NHL
│   │   ├── loaders.py               # Parseurs CSV (form, matchups, etc.)
│   │   ├── datastore.py             # Cache RAM des CSV
│   │   └── logger_csv.py            # Log picks CSV + DB
│   ├── data/
│   │   ├── fetcher.py               # Pipeline async NHL API → CSV
│   │   └── cache.py                 # Cache PBP et boxscores
│   ├── stats/                       # CSV générés (gitignored)
│   ├── scripts/                     # Utilitaires (recalc_probas, etc.)
│   ├── main_bot.py                  # Point d'entrée NHL
│   ├── dashboard.py                 # Dashboard Streamlit NHL
│   └── nhl_database.db              # Base SQLite NHL
│
├── mlb/                             # ⚾ Bot MLB (à construire)
│   ├── config/
│   │   ├── settings.toml
│   │   └── constants.py
│   ├── core/
│   │   ├── bot_logic.py             # MlbBot(BaseSportBot)
│   │   ├── harvester.py             # Collecte boxscores MLB
│   │   ├── market_filter.py         # Filtres MLB
│   │   ├── odds_scraper.py          # The Odds API (MLB player props)
│   │   ├── database.py              # Schéma SQLite MLB
│   │   └── updater.py               # Résolution résultats MLB
│   ├── main_bot.py
│   └── mlb_database.db
│
├── nba/                             # 🏀 Bot NBA (futur)
│   └── ...
│
├── vps/                             # 🖥️ Scripts VPS uniquement
│   └── watchdog.py                  # Superviseur intelligent (voir VPS_WATCHDOG.md)
│
├── portfolio_dashboard.py           # 📊 Dashboard global tous sports
├── requirements.txt                 # Dépendances Python
├── .env                             # Secrets (gitignored)
├── .gitignore
├── PROJECT_VISION.md                # CE FICHIER
├── VPS_WATCHDOG.md                  # Spec du watchdog VPS
└── README.md
```

---

## 4. Pipeline d'un Bot Sport (Cycle de Vie)

Chaque bot sport suit le même cycle, hérité de la NHL V18 :

```
┌─────────────────────────────────────────────────────────────────┐
│                    CYCLE DE SCAN (toutes les 15 min)             │
│                                                                 │
│  1. UPDATE STATS        Télécharger les stats fraîches (API)    │
│         ↓                                                       │
│  2. SCAN LINEUPS        Vérifier les compositions confirmées    │
│         ↓                                                       │
│  3. FILTRAGE MARCHÉ     Appliquer les seuils statistiques       │
│         ↓                                                       │
│  4. SCRAPE ODDS         Récupérer les cotes (The Odds API)      │
│         ↓                                                       │
│  5. VALIDATION EV       Edge > 5% ? Kelly sizing si oui         │
│         ↓                                                       │
│  6. ENVOI TELEGRAM      Via shared/telegram_hub.py              │
│         ↓                                                       │
│  7. LOG DB + CSV        Traçabilité complète                    │
│         ↓                                                       │
│  8. PORTFOLIO UPDATE    Enregistrer la mise dans le portfolio   │
│                                                                 │
│  ─── FIN DE JOURNÉE ───                                        │
│  9. RÉSOLUTION AUTO     API Boxscore → but=1/0, assist=1/0     │
│ 10. PORTFOLIO P&L       Calculer gain/perte, MAJ solde          │
│ 11. RAPPORT EMAIL       Envoi du bilan journalier               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Portefeuille Simulé

### Concept

Un portefeuille virtuel qui démarre à **100 Unités** et évolue en fonction de chaque pari recommandé par les bots. Ce n'est **pas** du pari automatique réel — c'est un tracker de performance.

### Fonctionnement

```
Portfolio (100 U au départ)
  │
  ├── NHL Bot recommande : Passeur McDavid @ 2.40, mise 1.5 U
  │     → portfolio.log_bet("nhl", pick_id=42, mise=1.5, cote=2.40)
  │     → solde courant: 98.5 U (mise déduite)
  │
  ├── Résolution auto : McDavid a fait 1 assist ✅
  │     → portfolio.resolve_bet(pick_id=42, won=True)
  │     → gain = 1.5 * 2.40 = 3.6 U
  │     → solde courant: 102.1 U
  │
  └── MLB Bot recommande : K pitcher Gerrit Cole @ 1.85, mise 1 U
        → portfolio.log_bet("mlb", pick_id=7, mise=1.0, cote=1.85)
        → ...
```

### Accès

- **Telegram** : `/portfolio` → solde, P&L jour, P&L semaine, ventilation par sport
- **Dashboard local** : Courbe de richesse, drawdown max, Sharpe ratio, ventilation

### Table SQLite (`shared/portfolio.db`)

```sql
CREATE TABLE portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    sport TEXT NOT NULL,          -- 'nhl', 'mlb', 'nba'
    pick_id INTEGER,             -- Référence vers la table picks du sport
    player TEXT,
    market TEXT,                  -- 'PASSEUR', 'POINTEUR', 'STRIKEOUT', etc.
    cote REAL,
    mise REAL,
    gain REAL DEFAULT NULL,       -- NULL = en attente, >0 = gagné, <0 = perdu
    solde_apres REAL DEFAULT NULL,
    resolved INTEGER DEFAULT 0    -- 0 = pending, 1 = résolu
);
```

---

## 6. Centralisation Telegram

### Pourquoi ?

Un seul token Telegram ne peut être utilisé en `polling` que par **un seul processus**. Si 2 bots font du polling → conflit `getUpdates` → crash.

### Solution

```
┌────────────────────────────────────────────────────────┐
│  telegram_commands.py (1 seul process, polling unique)  │
│                                                        │
│  Commandes :                                           │
│    /start         → Aide générale                      │
│    /status        → Status de tous les bots            │
│    /portfolio     → Solde et P&L                       │
│    /roi_nhl       → ROI détaillé NHL                   │
│    /roi_mlb       → ROI détaillé MLB                   │
│    /force_nhl     → Forcer un scan NHL                 │
│    /force_mlb     → Forcer un scan MLB                 │
│    /backup        → Télécharger les bases de données   │
└────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────┐
│  telegram_hub.py (bibliothèque, importée par les bots) │
│                                                        │
│  Chaque bot sport fait :                               │
│    from shared.telegram_hub import send_telegram       │
│    send_telegram(message_html)                         │
│                                                        │
│  → Simple POST vers api.telegram.org/sendMessage       │
│  → Pas de polling, pas de conflit                      │
└────────────────────────────────────────────────────────┘
```

### Règle

- **Envoi de messages** (picks, alertes, crashs) → `shared/telegram_hub.py` (POST HTTP simple)
- **Réception de commandes** (`/roi`, `/force`, `/portfolio`) → `shared/telegram_commands.py` (polling unique, processus séparé)

---

## 7. Money Management

### Quarter Kelly (actuel NHL, à généraliser)

```
mise = (p × b − q) / b × (1/8) × 100
```

Où :
- `p` = probabilité estimée (bayésienne, recalculée chaque lundi)
- `b` = cote − 1
- `q` = 1 − p
- Le diviseur `/8` est un choix de prudence (1/8ème de Kelly)

### Plafonds par marché (configurables par sport)

```toml
# NHL
[kelly]
buteur_cap = 2.0
passeur_cap = 3.0
pointeur_cap = 4.0

# MLB (futur)
[kelly]
strikeout_cap = 2.5
hr_cap = 1.5
```

### Validation EV

Un pari n'est recommandé que si :
1. `edge = (proba × cote) − 1.0 > 0.05` (EV > 5%)
2. La cote est disponible et > 1.05
3. Le joueur passe TOUS les filtres statistiques du sport

---

## 8. Stack Technique

| Composant | Technologie |
|-----------|-------------|
| Langage | Python 3.12+ |
| Données | Pandas, aiohttp (async) |
| Base de données | SQLite (une par sport + une portfolio) |
| Scraping lineups | Selenium (Brave) pour Flashscore, HTTP pour RotoWire |
| Scraping cotes | The Odds API (500 crédits/mois) |
| Notifications | python-telegram-bot + raw HTTP POST |
| Dashboard | Streamlit + Plotly |
| Déploiement | VPS Linux (Ubuntu), venv Python |
| CI/CD | Git push → watchdog.py détecte → restart ciblé |
| Scheduling | APScheduler (via Telegram JobQueue) ou schedule |

---

## 9. Données et APIs

### NHL (actif)
- **NHL API** (`api-web.nhle.com`) : Stats saison, PBP, boxscores, schedule
- **NHL Stats API** (`api.nhle.com/stats/rest`) : Stats avancées (CF%, HDCF, PDO)
- **The Odds API** : Cotes player props (anytime scorer, assists, points)
- **Flashscore** : Lineups confirmées (scraping Selenium)

### MLB (en cours)
- **MLB Stats API** (`statsapi.mlb.com`) : Schedule, boxscores, stats batting/pitching
- **The Odds API** : Cotes MLB player props (batter HR, pitcher strikeouts)

### NBA (futur)
- **NBA API** : Stats joueurs, schedule
- **The Odds API** : Cotes NBA player props

---

## 10. Workflow VPS

```
VPS (Ubuntu)
  │
  ├── vps/watchdog.py           ← Processus permanent #1
  │     Surveille GitHub toutes les 15 min
  │     git diff → détecte quels dossiers changent
  │     Relance uniquement les bots impactés
  │
  ├── shared/telegram_commands.py  ← Processus permanent #2
  │     Polling Telegram unique
  │     Dispatche les commandes vers les bons bots
  │
  ├── nhl/main_bot.py           ← Processus géré par watchdog
  │     Bot NHL autonome
  │     Scans toutes les 15 min, envoi Telegram via shared/
  │
  ├── mlb/main_bot.py           ← Processus géré par watchdog
  │     Bot MLB autonome
  │
  └── portfolio_dashboard.py    ← Streamlit (optionnel, sur demande)
```

Voir [VPS_WATCHDOG.md](VPS_WATCHDOG.md) pour la spec détaillée du watchdog.

---

## 11. Règles de Développement

1. **Un sport à la fois** : Ne pas commencer le NBA tant que le MLB n'est pas stable
2. **Backtesting obligatoire** : Aucun sport en production sans au moins 30 jours de données historiques
3. **Cotes réelles uniquement** : Le dashboard ne simule que sur les cotes scrappées (pas de cotes inventées)
4. **EV > 5% strict** : Aucun pari recommandé sans edge positif vérifié
5. **Probas bayésiennes** : Recalcul hebdomadaire automatique des probabilités de chaque marché
6. **Pas de pari automatique réel** : Le système recommande, l'humain décide de placer ou non

---

## 12. Objectifs Court Terme

### Phase 1 — Restructuration Architecture (en cours)
- [ ] Créer `shared/` avec les modules communs
- [ ] Déplacer le code NHL dans `nhl/`
- [ ] Créer `BaseSportBot` abstrait
- [ ] Nouveau watchdog multi-sport dans `vps/`
- [ ] Centraliser Telegram

### Phase 2 — Portfolio
- [ ] `shared/portfolio.py` + table SQLite
- [ ] Intégration dans le pipeline NHL
- [ ] Commande `/portfolio` Telegram
- [ ] Page portfolio dans le dashboard

### Phase 3 — MLB Bot
- [ ] Transformer le harvester en vrai bot
- [ ] Recherche des marchés profitables
- [ ] Backtesting historique
- [ ] Intégration portfolio + Telegram

### Phase 4 — Dashboard Unifié
- [ ] Dashboard Streamlit multi-tabs
- [ ] Courbe de richesse tous sports
- [ ] Configuration live

---

*Ce fichier est la source de vérité du projet. Toute décision architecturale majeure doit y être documentée.*
