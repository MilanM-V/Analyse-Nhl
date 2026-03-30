import sqlite3
import logging
from datetime import datetime
import os

logger = logging.getLogger("NHL_Bot")

DB_PATH = "./bot_database.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    """Initialise le schéma de la base de données SQL si elle n'existe pas."""
    logger.info("Initialisation de la base SQLite...")
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            vague TEXT,
            joueur TEXT,
            equipe TEXT,
            adversaire TEXT,
            score REAL,
            verdict TEXT,
            pp1 BOOLEAN,
            backup BOOLEAN,
            b2b BOOLEAN,
            ixg REAL,
            hdcf REAL,
            sog REAL,
            atoi REAL,
            l10_g REAL,
            season_g REAL,
            pdo REAL,
            ga_g REAL,
            cf_pct REAL,
            hdca_g REAL,
            pk_pct REAL,
            rebounds REAL,
            rush REAL,
            but INTEGER DEFAULT NULL
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            vague TEXT,
            joueur TEXT,
            equipe TEXT,
            adversaire TEXT,
            score REAL,
            picked BOOLEAN,
            pp1 BOOLEAN,
            backup BOOLEAN,
            b2b BOOLEAN,
            ixg REAL,
            hdcf REAL,
            sog REAL,
            atoi REAL,
            l10_g REAL,
            season_g REAL,
            pdo REAL,
            ga_g REAL,
            cf_pct REAL,
            hdca_g REAL,
            pk_pct REAL,
            rebounds REAL,
            rush REAL,
            but INTEGER DEFAULT NULL
        )
    ''')
    
    # V14 : Ajout dynamique des colonnes XGBoost si elles n'existent pas
    for table in ["picks", "players"]:
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN is_home BOOLEAN DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN opp_b2b BOOLEAN DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN consec_goals INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()

def insert_pick(pick_data, conn=None):
    """Insère un pari sélectionné dans la table picks."""
    auto_close = conn is None
    if auto_close:
        conn = get_connection()
    c = conn.cursor()

    cols = ', '.join(pick_data.keys())
    placeholders = ', '.join(['?'] * len(pick_data))

    sql = f'INSERT INTO picks ({cols}) VALUES ({placeholders})'
    c.execute(sql, list(pick_data.values()))

    if auto_close:
        conn.commit()
        conn.close()

def insert_player(player_data, conn=None):
    """Insère le log d'un joueur évalué dans la table players."""
    auto_close = conn is None
    if auto_close:
        conn = get_connection()
    c = conn.cursor()

    cols = ', '.join(player_data.keys())
    placeholders = ', '.join(['?'] * len(player_data))

    sql = f'INSERT INTO players ({cols}) VALUES ({placeholders})'
    c.execute(sql, list(player_data.values()))

    if auto_close:
        conn.commit()
        conn.close()

def reset_db():
    """Supprime tout le contenu de la base de données (picks et players)."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM picks")
    c.execute("DELETE FROM players")
    conn.commit()
    conn.close()

def get_roi_stats():
    """Renvoie le ROI par catégories et le total depuis la BDD SQLite avec calcul des Unités."""
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT COUNT(*), SUM(but) FROM picks WHERE but IS NOT NULL AND but != ''")
    res = c.fetchone()
    total_played = res[0] or 0
    total_won = res[1] or 0

    if total_played == 0:
        conn.close()
        return "Pas assez de données résolues. Attendre la fin du match ou forcer l'update."

    c.execute("SELECT verdict, COUNT(*), SUM(but) FROM picks WHERE but IS NOT NULL AND but != '' GROUP BY verdict")
    cats = c.fetchall()
    conn.close()

    total_lost = total_played - total_won
    global_units = total_won - total_lost
    global_sign = "+" if global_units > 0 else ""

    winrate_global = (total_won / total_played) * 100
    msg = f"<b>🏆 TOTAL GLOBAL : {global_sign}{global_units} U</b>\n"
    msg += f"{total_won}✅ / {total_played} ({winrate_global:.1f}%)\n"
    msg += "──────────────────\n"

    for row in sorted(cats, key=lambda x: x[0] or ""):
        verdict = row[0]
        nb_joues = row[1]
        nb_gagnes = row[2]
        nb_perdus = nb_joues - nb_gagnes

        if nb_joues > 0:
            units_cat = nb_gagnes - nb_perdus
            cat_sign = "+" if units_cat > 0 else ""
            roi_cat = (nb_gagnes / nb_joues) * 100
            msg += f"<b>{verdict} [{cat_sign}{units_cat} U]</b> : {nb_gagnes}✅ / {nb_joues} ({roi_cat:.1f}%)\n"

    return msg

if not os.path.exists(DB_PATH):
    init_db()
