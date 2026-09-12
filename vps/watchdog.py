"""
vps/watchdog.py — Superviseur intelligent multi-sport pour le VPS.

Fonctionnement :
- Pull au démarrage pour toujours partir sur le dernier code
- Vérification GitHub toutes les 15 min
- Si nouveau commit → git diff pour détecter quels sports ont changé
- Relance uniquement les bots impactés
- Redémarre les bots crashés automatiquement
- Se restart lui-même si vps/ est modifié

Voir VPS_WATCHDOG.md pour la spécification complète.
"""

import subprocess
import time
import os
import sys
import logging
import fnmatch
from logging.handlers import RotatingFileHandler
from datetime import datetime
from typing import Dict, Set, Optional

# Charger .env s'il existe pour la configuration du Watchdog
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ[key.strip()] = value.strip()

# ==========================================
# CONFIG
# ==========================================
REPO_DIR = os.environ.get("REPO_DIR", "/opt/Analyse-Nhl-test")
VENV_PYTHON = os.environ.get("VENV_PYTHON", f"{REPO_DIR}/venv/bin/python3")
GIT_BRANCH = os.environ.get("GIT_BRANCH", "main")  # "main" par défaut sur le serveur de prod
CHECK_INTERVAL = 900  # 15 minutes
LOG_FILE = f"{REPO_DIR}/watchdog.log"

# Bots à gérer : {nom_sport: chemin du script relatif à REPO_DIR}
SPORT_BOTS: Dict[str, str] = {
    "nhl": "nhl/main_bot.py",
    "mlb": "mlb/main_bot.py",
    # "nba": "nba/main_bot.py",  # Décommenter quand prêt
}

# Fichiers/patterns qui ne déclenchent PAS de restart
IGNORED_PATTERNS = [
    "*.md", ".antigravity/*", "docs/*", "artifacts/*",
]

# ==========================================
# LOGGING
# ==========================================
logger = logging.getLogger("Watchdog")
logger.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s - WATCHDOG - %(levelname)s - %(message)s")

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
fh = RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3)
fh.setFormatter(fmt)
sh_handler = logging.StreamHandler()
sh_handler.setFormatter(fmt)
logger.addHandler(fh)
logger.addHandler(sh_handler)


# ==========================================
# GIT OPERATIONS
# ==========================================

def get_local_commit() -> Optional[str]:
    """Retourne le hash du commit local actuel."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_DIR, capture_output=True, text=True,
        )
        return r.stdout.strip()
    except Exception as e:
        logger.error(f"Erreur get_local_commit : {e}")
        return None


def get_remote_commit() -> Optional[str]:
    """Fetch silencieux puis retourne le hash du commit distant."""
    try:
        subprocess.run(
            ["git", "fetch", "origin"],
            cwd=REPO_DIR, capture_output=True, text=True, timeout=30,
        )
        r = subprocess.run(
            ["git", "rev-parse", f"origin/{GIT_BRANCH}"],
            cwd=REPO_DIR, capture_output=True, text=True,
        )
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning("git fetch timeout (réseau lent ?)")
        return None
    except Exception as e:
        logger.error(f"Erreur get_remote_commit : {e}")
        return None


def pull_latest() -> bool:
    """Force un git reset --hard + pull pour s'aligner sur le remote."""
    try:
        reset = subprocess.run(
            ["git", "reset", "--hard", f"origin/{GIT_BRANCH}"],
            cwd=REPO_DIR, capture_output=True, text=True, timeout=30,
        )
        logger.info(f"git reset : {reset.stdout.strip()}")
        if reset.returncode != 0:
            logger.error(f"git reset échoué : {reset.stderr.strip()}")
            return False

        r = subprocess.run(
            ["git", "pull", "origin", GIT_BRANCH],
            cwd=REPO_DIR, capture_output=True, text=True, timeout=60,
        )
        logger.info(f"git pull : {r.stdout.strip()}")
        if r.returncode != 0:
            logger.error(f"git pull échoué : {r.stderr.strip()}")
            return False
        return True
    except Exception as e:
        logger.error(f"Erreur git pull : {e}")
        return False


def get_changed_dirs(local_commit: str, remote_commit: str) -> Set[str]:
    """Analyse le git diff pour déduire quels dossiers ont changé.

    Args:
        local_commit: Hash du commit local.
        remote_commit: Hash du commit remote.

    Returns:
        Set de noms de dossiers impactés ('nhl', 'mlb', 'shared', 'root', 'vps').
    """
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", local_commit, remote_commit],
            cwd=REPO_DIR, capture_output=True, text=True,
        )
        changed_files = [f for f in r.stdout.strip().split("\n") if f]
    except Exception as e:
        logger.error(f"Erreur git diff : {e}")
        return {"all"}  # En cas d'erreur, on relance tout par sécurité

    changed_dirs: Set[str] = set()
    for filepath in changed_files:
        # Ignorer les fichiers non-exécutables
        if any(fnmatch.fnmatch(filepath, pat) for pat in IGNORED_PATTERNS):
            continue

        parts = filepath.split("/")
        if len(parts) > 1:
            changed_dirs.add(parts[0])  # 'nhl', 'mlb', 'shared', 'vps'
        else:
            changed_dirs.add("root")  # fichiers à la racine (requirements.txt, etc.)

    return changed_dirs


def get_sports_to_restart(changed_dirs: Set[str]) -> Set[str]:
    """Détermine quels bots sport redémarrer en fonction des dossiers modifiés.

    Args:
        changed_dirs: Set de dossiers modifiés.

    Returns:
        Set de noms de sport à redémarrer.
    """
    # Si shared/ ou root (requirements.txt, .env) → TOUT redémarrer
    if "shared" in changed_dirs or "root" in changed_dirs or "all" in changed_dirs:
        return set(SPORT_BOTS.keys())

    # Sinon, ne redémarrer que les sports concernés
    return {d for d in changed_dirs if d in SPORT_BOTS}


# ==========================================
# PROCESS MANAGEMENT
# ==========================================

def stop_bot(process: Optional[subprocess.Popen], name: str = "") -> None:
    """Arrête proprement un bot et attend sa mort effective.

    Args:
        process: Le Popen du processus.
        name: Nom du sport pour les logs.
    """
    if process is None or process.poll() is not None:
        return

    logger.info(f"🛑 Arrêt du bot {name.upper()} (PID {process.pid})...")
    process.terminate()
    try:
        process.wait(timeout=20)
        logger.info(f"   Bot {name.upper()} PID {process.pid} arrêté proprement.")
    except subprocess.TimeoutExpired:
        logger.warning(f"   Timeout → kill forcé PID {process.pid}")
        process.kill()
        process.wait()


def start_bot(sport: str) -> subprocess.Popen:
    """Lance le main_bot.py d'un sport en subprocess.

    Args:
        sport: Nom du sport ('nhl', 'mlb', etc.).

    Returns:
        Le Popen du processus lancé.
    """
    script = SPORT_BOTS[sport]
    logger.info(f"🚀 Démarrage de {sport.upper()} ({script})...")

    stderr_log = open(os.path.join(REPO_DIR, f"{sport}_stderr.log"), "a")
    process = subprocess.Popen(
        [VENV_PYTHON, os.path.join(REPO_DIR, script)],
        cwd=os.path.join(REPO_DIR, sport),  # CWD = dossier du sport
        stdout=subprocess.DEVNULL,
        stderr=stderr_log,
    )
    logger.info(f"✅ Bot {sport.upper()} démarré (PID {process.pid})")
    return process


def kill_existing_bots() -> None:
    """Tue tous les anciens processus de bot par pattern matching."""
    for sport, script in SPORT_BOTS.items():
        pattern = f"{VENV_PYTHON} {os.path.join(REPO_DIR, script)}"
        subprocess.run(["pkill", "-f", pattern], capture_output=True)
    time.sleep(2)
    logger.info("Anciens processus de bot tués.")


def install_requirements() -> None:
    """Met à jour les dépendances Python si requirements.txt a changé."""
    req_path = os.path.join(REPO_DIR, "requirements.txt")
    if os.path.exists(req_path):
        logger.info("📦 Installation des dépendances (pip install)...")
        subprocess.run(
            [VENV_PYTHON, "-m", "pip", "install", "-r", req_path, "-q"],
            cwd=REPO_DIR, capture_output=True,
        )


# ==========================================
# TELEGRAM ALERTS
# ==========================================

def send_watchdog_alert(message: str) -> None:
    """Envoie une alerte Telegram depuis le watchdog (POST direct).

    Args:
        message: Message HTML à envoyer.
    """
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass  # Le watchdog ne doit jamais crasher à cause de Telegram


# ==========================================
# HEALTH CHECK
# ==========================================

def health_check(processes: Dict[str, Optional[subprocess.Popen]]) -> None:
    """Vérifie que chaque bot tourne et le relance si crashé.

    Args:
        processes: Dict {sport_name: subprocess.Popen ou None}.
    """
    for sport in SPORT_BOTS:
        proc = processes.get(sport)
        if proc is not None and proc.poll() is not None:
            exit_code = proc.returncode
            logger.warning(
                f"⚠️ Bot {sport.upper()} mort (code {exit_code}), redémarrage..."
            )
            send_watchdog_alert(
                f"⚠️ Bot <b>{sport.upper()}</b> crashé (code {exit_code}) — "
                f"Redémarrage automatique"
            )
            processes[sport] = start_bot(sport)


# ==========================================
# MAIN LOOP
# ==========================================

def main() -> None:
    """Boucle principale du watchdog multi-sport."""
    logger.info("=" * 55)
    logger.info(f"  WATCHDOG MULTI-SPORT DÉMARRÉ (branche: {GIT_BRANCH})")
    logger.info(f"  Sports configurés : {list(SPORT_BOTS.keys())}")
    logger.info("=" * 55)

    # ── ÉTAPE 0 : pull initial ────────────────────────────────────
    logger.info("📥 Pull initial pour partir sur le dernier code...")
    pull_latest()

    last_commit = get_local_commit()
    logger.info(
        f"Commit de départ : {last_commit[:8] if last_commit else 'inconnu'}"
    )

    # ── ÉTAPE 1 : démarrer tous les bots ──────────────────────────
    kill_existing_bots()
    processes: Dict[str, Optional[subprocess.Popen]] = {}
    for sport in SPORT_BOTS:
        processes[sport] = start_bot(sport)

    send_watchdog_alert(
        f"🟢 <b>Watchdog Multi-Sport démarré</b>\n"
        f"Sports : {', '.join(s.upper() for s in SPORT_BOTS)}\n"
        f"Commit : {last_commit[:8] if last_commit else '?'}"
    )

    # ── BOUCLE DE SURVEILLANCE ────────────────────────────────────
    while True:
        try:
            time.sleep(CHECK_INTERVAL)

            # Health check (redémarrage des bots crashés)
            health_check(processes)

            # Vérifier les mises à jour GitHub
            remote_commit = get_remote_commit()
            if remote_commit is None:
                logger.warning(
                    "Impossible de joindre GitHub, on continue avec le code actuel."
                )
                continue

            if remote_commit == last_commit:
                logger.info(
                    f"[{datetime.now().strftime('%H:%M')}] "
                    f"Pas de changement (commit {last_commit[:8] if last_commit else '?'})"
                )
                continue

            # ── NOUVEAU COMMIT DÉTECTÉ ────────────────────────────
            logger.info("🔄 NOUVEAU COMMIT DÉTECTÉ !")
            logger.info(f"   Local  : {last_commit[:8] if last_commit else '?'}")
            logger.info(f"   Remote : {remote_commit[:8]}")

            # Analyser quels dossiers ont changé
            changed_dirs = get_changed_dirs(last_commit, remote_commit)
            logger.info(f"   Dossiers modifiés : {changed_dirs}")

            sports_to_restart = get_sports_to_restart(changed_dirs)
            logger.info(f"   Sports à redémarrer : {sports_to_restart}")

            # Self-update du watchdog
            if "vps" in changed_dirs:
                logger.info("🔄 Le watchdog lui-même a été modifié. Auto-restart...")
                for sport in processes:
                    stop_bot(processes[sport], sport)
                pull_latest()
                send_watchdog_alert(
                    "🔄 <b>Watchdog auto-restart</b> — vps/ modifié"
                )
                os.execv(sys.executable, [sys.executable] + sys.argv)

            # Stop les bots ciblés
            for sport in sports_to_restart:
                stop_bot(processes.get(sport), sport)

            # Git pull
            if pull_latest():
                logger.info("✅ Code mis à jour.")
                last_commit = remote_commit  # FIX: Empêche la boucle infinie !
            else:
                logger.error(
                    "❌ git pull échoué, redémarrage avec le code actuel."
                )

            # pip install si requirements.txt a changé
            if "root" in changed_dirs:
                install_requirements()

            # Restart les bots ciblés
            for sport in sports_to_restart:
                processes[sport] = start_bot(sport)

            # Log les bots non impactés
            non_impacted = set(SPORT_BOTS.keys()) - sports_to_restart
            for sport in non_impacted:
                proc = processes.get(sport)
                pid = proc.pid if proc and proc.poll() is None else "mort"
                logger.info(
                    f"   Bot {sport.upper()} non impacté, "
                    f"toujours actif (PID {pid})"
                )

            # Mise à jour de la référence
            last_commit = get_local_commit()
            logger.info(
                f"   Nouveau commit local : "
                f"{last_commit[:8] if last_commit else '?'}"
            )

            send_watchdog_alert(
                f"🔄 <b>Mise à jour déployée</b>\n"
                f"Sports redémarrés : {', '.join(s.upper() for s in sports_to_restart)}\n"
                f"Commit : {last_commit[:8] if last_commit else '?'}"
            )

        except Exception as e:
            logger.error(f"ERREUR WATCHDOG : {e}", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    main()
