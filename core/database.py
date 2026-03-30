import sqlite3
import logging
from datetime import datetime
import os
from typing import Dict, Any, Optional, List

logger = logging.getLogger("NHL_Bot")

DB_PATH = "./bot_database.db"

def get_connection() -> sqlite3.Connection:
    """Returns a connection to the SQLite database."""
    return sqlite3.connect(DB_PATH)

def init_db() -> None:
    """Initializes the SQL database schema if it doesn't exist."""
    logger.info("Initialisation de la base SQLite V14...")
    conn = get_connection()
    c = conn.cursor()

    # Table des picks BUTS
    c.execute('''
        CREATE TABLE IF NOT EXISTS picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, vague TEXT, joueur TEXT, equipe TEXT, adversaire TEXT,
            score REAL, verdict TEXT, pp1 BOOLEAN, backup BOOLEAN, b2b BOOLEAN,
            ixg REAL, hdcf REAL, sog REAL, atoi REAL, l10_g REAL, season_g REAL,
            pdo REAL, ga_g REAL, cf_pct REAL, hdca_g REAL, pk_pct REAL,
            rebounds REAL, rush REAL, is_home BOOLEAN, opp_b2b BOOLEAN,
            consec_goals INTEGER, but INTEGER DEFAULT NULL
        )
    ''')

    # Table des picks ASSISTS
    c.execute('''
        CREATE TABLE IF NOT EXISTS picks_assists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, vague TEXT, joueur TEXT, equipe TEXT, adversaire TEXT,
            score REAL, verdict TEXT, pp1 BOOLEAN, backup BOOLEAN, b2b BOOLEAN,
            atoi REAL, l10_a REAL, season_a REAL, pdo REAL, ga_g REAL, 
            cf_pct REAL, pk_pct REAL, is_home BOOLEAN, opp_b2b BOOLEAN,
            assist INTEGER DEFAULT NULL
        )
    ''')

    # Table des picks POINTS
    c.execute('''
        CREATE TABLE IF NOT EXISTS picks_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, vague TEXT, joueur TEXT, equipe TEXT, adversaire TEXT,
            score REAL, verdict TEXT, pp1 BOOLEAN, backup BOOLEAN, b2b BOOLEAN,
            atoi REAL, l10_pts REAL, season_pts REAL, pdo REAL, ga_g REAL, 
            cf_pct REAL, is_home BOOLEAN, opp_b2b BOOLEAN,
            point INTEGER DEFAULT NULL
        )
    ''')

    # Table unique pour tous les joueurs évalués (log global)
    c.execute('''
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, vague TEXT, joueur TEXT, equipe TEXT, adversaire TEXT,
            score_but REAL, score_assist REAL, score_point REAL,
            picked_but BOOLEAN, picked_assist BOOLEAN, picked_point BOOLEAN,
            pp1 BOOLEAN, backup BOOLEAN, b2b BOOLEAN, is_home BOOLEAN,
            ixg REAL, hdcf REAL, sog REAL, atoi REAL,
            l10_g REAL, l10_a REAL, l10_pts REAL,
            season_g REAL, season_a REAL, season_pts REAL,
            pdo REAL, ga_g REAL, cf_pct REAL, hdca_g REAL, pk_pct REAL,
            consec_goals INTEGER DEFAULT 0,
            but INTEGER DEFAULT NULL, assist INTEGER DEFAULT NULL, point INTEGER DEFAULT NULL
        )
    ''')

    conn.commit()
    
    # Upgrade existing tables if necessary (V14 Migration)
    # On vérifie chaque table pour les colonnes manquantes
    tables_to_fix = ["picks", "picks_assists", "picks_points", "players"]
    columns_to_add = [
        ("is_home", "BOOLEAN DEFAULT 0"),
        ("opp_b2b", "BOOLEAN DEFAULT 0"),
        ("consec_goals", "INTEGER DEFAULT 0")
    ]
    
    for table in tables_to_fix:
        for col_name, col_type in columns_to_add:
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                logger.info(f"Migration V14 : Colonne '{col_name}' ajoutée à la table '{table}'.")
            except sqlite3.OperationalError:
                # La colonne existe déjà, on passe
                pass
    
    conn.commit()
    conn.close()

def insert_pick(table: str, pick_data: Dict[str, Any], conn: Optional[sqlite3.Connection] = None) -> None:
    """
    Inserts a selected pick into the specified table.

    Args:
        table: Table name ('picks', 'picks_assists', 'picks_points').
        pick_data: Dictionary containing pick statistics.
        conn: Optional existing database connection.
    """
    auto_close = conn is None
    if auto_close:
        conn = get_connection()
    c = conn.cursor()

    cols = ', '.join(pick_data.keys())
    placeholders = ', '.join(['?'] * len(pick_data))

    sql = f'INSERT INTO {table} ({cols}) VALUES ({placeholders})'
    c.execute(sql, list(pick_data.values()))

    if auto_close:
        conn.commit()
        conn.close()

def insert_player(player_data: Dict[str, Any], conn: Optional[sqlite3.Connection] = None) -> None:
    """
    Inserts an evaluated player log into the 'players' table.

    Args:
        player_data: Dictionary containing player evaluation data.
        conn: Optional existing database connection.
    """
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

def reset_db() -> None:
    """Clears all content from all relevant tables."""
    conn = get_connection()
    c = conn.cursor()
    for table in ['picks', 'picks_assists', 'picks_points', 'players']:
        c.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()

def get_roi_stats(table: str = "picks", target_col: str = "but") -> str:
    """
    Calculates and returns ROI statistics for a specific market.

    Args:
        table: The table to query.
        target_col: The column representing the result (but, assist, point).

    Returns:
        A formatted HTML string with ROI stats.
    """
    conn = get_connection()
    c = conn.cursor()

    c.execute(f"SELECT COUNT(*), SUM({target_col}) FROM {table} WHERE {target_col} IS NOT NULL AND {target_col} != ''")
    res = c.fetchone()
    total_played = res[0] or 0
    total_won = res[1] or 0

    if total_played == 0:
        conn.close()
        return f"Pas assez de données pour {table}."

    c.execute(f"SELECT verdict, COUNT(*), SUM({target_col}) FROM {table} WHERE {target_col} IS NOT NULL AND {target_col} != '' GROUP BY verdict")
    cats = c.fetchall()
    conn.close()

    total_lost = total_played - total_won
    global_units = total_won - total_lost
    global_sign = "+" if global_units > 0 else ""

    winrate_global = (total_won / total_played) * 100
    msg = f"<b>📊 STATS {table.upper()} : {global_sign}{global_units} U</b>\n"
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
else:
    # Trigger upgrade to V14 if tables missing
    init_db()
