# 🖥️ VPS Watchdog — Spécification Technique

> **Fichier** : `vps/watchdog.py`
> **Rôle** : Superviseur intelligent sur le VPS qui gère le déploiement continu et la santé des bots

---

## 1. Contexte

Le watchdog actuel (`watchdog_test.py`) est monolithique : il ne connaît que `main_bot.py` et `harvest.py`, et un changement dans n'importe quel fichier provoque le redémarrage de **tout**. Avec l'architecture multi-sport, on a besoin d'un watchdog qui :

1. Détecte **quels dossiers** ont changé dans un `git push`
2. Ne redémarre que les **bots impactés**
3. Gère les **crashs** avec redémarrage automatique
4. Redémarre **tous** les bots si `shared/` ou `requirements.txt` changent

---

## 2. Fonctionnement Détaillé

### 2.1 Cycle Principal

```
BOUCLE (toutes les 15 minutes) :
│
├── 1. git fetch origin
│
├── 2. Comparer le commit local vs remote
│     local  = git rev-parse HEAD
│     remote = git rev-parse origin/main
│
├── 3. Si local == remote → pas de changement
│     → Vérifier la santé des bots (section 2.3)
│     → Dormir 15 minutes
│
├── 4. Si local != remote → NOUVEAU COMMIT DÉTECTÉ
│     │
│     ├── 4a. Lister les fichiers modifiés :
│     │     git diff --name-only HEAD origin/main
│     │     → ['nhl/core/market_filter.py', 'shared/telegram_hub.py', ...]
│     │
│     ├── 4b. Déduire les dossiers sport impactés :
│     │     Extraire les préfixes de premier niveau :
│     │       'nhl/core/market_filter.py'    → 'nhl'
│     │       'shared/telegram_hub.py'       → 'shared'
│     │       'mlb/main_bot.py'              → 'mlb'
│     │       'requirements.txt'             → 'root'
│     │       'vps/watchdog.py'              → 'vps'
│     │
│     ├── 4c. Appliquer les règles de restart :
│     │     Si 'shared' ou 'root' dans les dossiers → RESTART TOUT
│     │     Si 'vps' dans les dossiers → Le watchdog se restart lui-même
│     │     Sinon → RESTART uniquement les sports dans la liste
│     │
│     ├── 4d. git pull origin main
│     │
│     ├── 4e. Si 'root' (requirements.txt modifié) :
│     │     pip install -r requirements.txt
│     │
│     ├── 4f. Stop les bots ciblés → Start les bots ciblés
│     │
│     └── 4g. Mettre à jour le commit de référence
│
└── 5. Retour au début de la boucle
```

### 2.2 Détection des Dossiers Impactés (Algorithme)

```python
def get_changed_sports(local_commit: str, remote_commit: str) -> set[str]:
    """Analyse le git diff pour déduire quels sports redémarrer.
    
    Args:
        local_commit: Hash du commit local actuel.
        remote_commit: Hash du commit remote.
        
    Returns:
        Set de noms de dossiers sport impactés.
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", local_commit, remote_commit],
        cwd=REPO_DIR, capture_output=True, text=True
    )
    
    changed_files = result.stdout.strip().split('\n')
    
    # Extraire les dossiers de premier niveau
    changed_dirs = set()
    for filepath in changed_files:
        parts = filepath.split('/')
        if len(parts) > 1:
            changed_dirs.add(parts[0])  # 'nhl', 'mlb', 'shared', 'vps'
        else:
            changed_dirs.add('root')    # fichiers à la racine
    
    return changed_dirs
```

### 2.3 Vérification de Santé (Health Check)

À chaque cycle, même sans changement Git, le watchdog vérifie que chaque bot est vivant :

```python
def health_check(processes: dict) -> None:
    """Vérifie que chaque bot tourne et le relance si crashé.
    
    Args:
        processes: Dict {sport_name: subprocess.Popen}.
    """
    for sport, proc in processes.items():
        if proc is not None and proc.poll() is not None:
            # Le process est mort
            exit_code = proc.returncode
            logger.warning(f"⚠️ Bot {sport} mort (code {exit_code}), redémarrage...")
            processes[sport] = start_bot(sport)
```

### 2.4 Self-Update du Watchdog

Si `vps/watchdog.py` est dans la liste des fichiers modifiés, le watchdog doit :
1. Faire le `git pull`
2. Relancer tous les bots
3. Se remplacer lui-même via `os.execv()` (re-exécution du script)

```python
if 'vps' in changed_dirs:
    logger.info("🔄 Le watchdog lui-même a été modifié. Auto-restart...")
    pull_latest()
    # Stop tous les bots proprement
    for sport in processes:
        stop_bot(processes[sport])
    # Re-exécuter le watchdog
    os.execv(sys.executable, [sys.executable] + sys.argv)
```

---

## 3. Configuration

```python
# ─── CONFIG ───────────────────────────────────────────────
REPO_DIR       = "/opt/BetEngine"
VENV_PYTHON    = f"{REPO_DIR}/venv/bin/python3"
GIT_BRANCH     = "main"
CHECK_INTERVAL = 900   # 15 minutes
LOG_FILE       = f"{REPO_DIR}/watchdog.log"

# Bots à gérer : {nom_sport: chemin_du_main relatif à REPO_DIR}
SPORT_BOTS = {
    "nhl": "nhl/main_bot.py",
    "mlb": "mlb/main_bot.py",
    # "nba": "nba/main_bot.py",  # Décommenter quand prêt
}

# Processus auxiliaires (non liés à un sport)
AUX_PROCESSES = {
    "telegram_commands": "shared/telegram_commands.py",
}
```

---

## 4. Règles de Restart

| Fichiers modifiés | Action |
|-------------------|--------|
| `nhl/**` | Restart `nhl/main_bot.py` uniquement |
| `mlb/**` | Restart `mlb/main_bot.py` uniquement |
| `shared/**` | Restart **TOUS** les bots + `telegram_commands.py` |
| `requirements.txt` | `pip install -r requirements.txt` + restart **TOUS** |
| `vps/watchdog.py` | `git pull` + restart tout + `os.execv()` self-restart |
| `.env` | Restart **TOUS** (les variables d'env sont relues au start) |
| `nhl/**` + `mlb/**` | Restart NHL + MLB (pas les autres) |
| `README.md`, `docs/**` | Aucun restart (fichiers non-exécutables) |

### Fichiers ignorés (pas de restart)

```python
IGNORED_PATTERNS = [
    '*.md', '*.txt', '*.gitignore', '.antigravity/**',
    'docs/**', 'tests/**', 'scripts/**', 'artifacts/**'
]
```

---

## 5. Gestion des Processus

### Start d'un Bot

```python
def start_bot(sport: str) -> subprocess.Popen:
    """Lance le main_bot.py d'un sport en subprocess non-bloquant.
    
    Args:
        sport: Nom du sport ('nhl', 'mlb', etc.).
        
    Returns:
        Le Popen du processus lancé.
    """
    script = SPORT_BOTS[sport]
    sport_dir = os.path.join(REPO_DIR, sport)
    
    stderr_log = open(os.path.join(REPO_DIR, f"{sport}_stderr.log"), "a")
    
    process = subprocess.Popen(
        [VENV_PYTHON, os.path.join(REPO_DIR, script)],
        cwd=sport_dir,       # Le CWD est le dossier du sport
        stdout=subprocess.DEVNULL,
        stderr=stderr_log,
        env={**os.environ, "SPORT_NAME": sport}  # Variable pour identifier le sport
    )
    
    logger.info(f"✅ Bot {sport.upper()} démarré (PID {process.pid})")
    return process
```

### Stop d'un Bot

```python
def stop_bot(process: subprocess.Popen, timeout: int = 20) -> None:
    """Arrête proprement un bot et attend sa mort effective.
    
    Args:
        process: Le Popen du processus à arrêter.
        timeout: Temps max d'attente avant kill forcé.
    """
    if process is None or process.poll() is not None:
        return
    
    logger.info(f"🛑 Arrêt du bot (PID {process.pid})...")
    process.terminate()
    
    try:
        process.wait(timeout=timeout)
        logger.info(f"   Bot PID {process.pid} arrêté proprement.")
    except subprocess.TimeoutExpired:
        logger.warning(f"   Timeout → kill forcé PID {process.pid}")
        process.kill()
        process.wait()
```

---

## 6. Logging

Le watchdog produit un fichier de log rotatif :

```
2026-04-30 20:15:00 - WATCHDOG - INFO - [20:15] Pas de changement (commit a3f2b7c1)
2026-04-30 20:30:00 - WATCHDOG - INFO - 🔄 NOUVEAU COMMIT DÉTECTÉ !
2026-04-30 20:30:00 - WATCHDOG - INFO -    Local  : a3f2b7c1
2026-04-30 20:30:00 - WATCHDOG - INFO -    Remote : e9d4f123
2026-04-30 20:30:01 - WATCHDOG - INFO -    Fichiers modifiés : nhl/core/market_filter.py, nhl/config/settings.toml
2026-04-30 20:30:01 - WATCHDOG - INFO -    Sports impactés : {'nhl'}
2026-04-30 20:30:01 - WATCHDOG - INFO - 🛑 Arrêt du bot NHL (PID 12345)...
2026-04-30 20:30:02 - WATCHDOG - INFO -    git pull : Already up to date.
2026-04-30 20:30:03 - WATCHDOG - INFO - ✅ Bot NHL démarré (PID 12389)
2026-04-30 20:30:03 - WATCHDOG - INFO -    Bot MLB non impacté, toujours actif (PID 12350)
```

---

## 7. Alerte Telegram en cas de problème

Le watchdog lui-même peut envoyer des alertes Telegram (via POST HTTP direct, pas de polling) :

```python
def send_watchdog_alert(message: str) -> None:
    """Envoie une alerte Telegram depuis le watchdog.
    
    Args:
        message: Message HTML à envoyer.
    """
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            },
            timeout=10
        )
    except Exception:
        pass  # Le watchdog ne doit jamais crasher à cause de Telegram
```

Alertes envoyées :
- `🔄 Mise à jour détectée : nhl, mlb → Restart en cours`
- `⚠️ Bot NHL crashé (code 1) — Redémarrage automatique`
- `✅ Tous les bots redémarrés après mise à jour`
- `❌ git pull échoué — les bots continuent avec le code actuel`

---

## 8. Séquence de Démarrage Initial

Au premier lancement (ou redémarrage du VPS) :

```
1. git pull origin main                    # S'assurer d'avoir le dernier code
2. pip install -r requirements.txt         # MAJ dépendances si nécessaire
3. Tuer tous les anciens processus         # pkill -f pattern
4. Démarrer telegram_commands.py           # Polling Telegram unique
5. Démarrer chaque bot sport configuré     # NHL, MLB, etc.
6. Mémoriser le commit local comme ref     # Point de départ pour les diffs
7. Entrer dans la boucle de surveillance   # Check toutes les 15 min
```

---

## 9. Différences avec l'ancien `watchdog_test.py`

| Aspect | Ancien (`watchdog_test.py`) | Nouveau (`vps/watchdog.py`) |
|--------|---------------------------|----------------------------|
| Scope | NHL uniquement | Multi-sport dynamique |
| Restart | Tout à chaque changement | Ciblé par dossier sport |
| Branche | `test` hardcodée | Configurable (`main`) |
| Processus gérés | 2 (main_bot + harvest) | N dynamique (config dict) |
| Self-update | Non | Oui (`os.execv`) |
| Alertes Telegram | Non | Oui (POST direct) |
| Fichiers ignorés | Non | Oui (*.md, docs, tests) |
| pip install auto | Non | Oui (si requirements.txt change) |
| CWD des bots | Racine du repo | Dossier du sport (`nhl/`, `mlb/`) |

---

## 10. Points d'Attention

1. **Le watchdog ne doit JAMAIS crasher** : Tout est dans un `try/except` global. En cas d'erreur, on log et on continue.

2. **Pas de race condition** : Si un bot est en train de s'arrêter, on attend sa mort effective (`process.wait()`) avant de lancer le nouveau.

3. **Git pull sécurisé** : On fait un `git reset --hard origin/main` avant le pull pour éviter les conflits locaux.

4. **Le CWD des bots** est le dossier du sport, pas la racine du repo. Les chemins relatifs dans le code sport (`./stats/`, `./config/`) fonctionnent correctement.

5. **Variables d'environnement** : Le `.env` est lu à chaque start de bot (via `load_dotenv()`). Si `.env` change, un restart suffit.

---

*Ce document est la spécification de référence pour implémenter `vps/watchdog.py`.*
