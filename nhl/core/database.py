import sqlite3
import logging
from datetime import datetime, timedelta
import os
from typing import Dict, Any, Optional, List

logger = logging.getLogger("NHL.Database")

DB_PATH = "./bot_database.db"

def get_connection() -> sqlite3.Connection:
    """Returns a connection to the SQLite database."""
    return sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15.0)

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

    # Table des paris combinés (V18.2)
    c.execute('''
        CREATE TABLE IF NOT EXISTS picks_parlays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, vague TEXT, type_combo TEXT,
            leg1_joueur TEXT, leg2_joueur TEXT, leg3_joueur TEXT,
            cote_totale REAL, mise REAL, resultat INTEGER DEFAULT NULL
        )
    ''')

    conn.commit()
    
    # Upgrade existing tables if necessary (V14-V19 Migration)
    logger.info("Vérification de l'intégrité de la base de données...")
    tables_to_fix = ["picks", "picks_assists", "picks_points", "players"]
    
    # Colonnes universelles (V14 à V19)
    # On s'assure que TOUTES les tables ont ces colonnes pour la cohérence des stats
    common_cols = [
        ("is_home", "BOOLEAN DEFAULT 0"),
        ("opp_b2b", "BOOLEAN DEFAULT 0"),
        ("consec_goals", "INTEGER DEFAULT 0"),
        ("cote", "REAL DEFAULT NULL"),
        ("mise", "REAL DEFAULT NULL"),
        ("closing_cote", "REAL DEFAULT NULL"),
        ("game_mode", "TEXT DEFAULT 'regular'"),
        ("ixg", "REAL DEFAULT 0"),
        ("hdcf", "REAL DEFAULT 0"),
        ("sog", "REAL DEFAULT 0"),
        ("atoi", "REAL DEFAULT 0"),
    ]
    
    for table in tables_to_fix:
        for col_name, col_type in common_cols:
            try:
                # Vérifier si la colonne existe déjà pour éviter des logs inutiles
                c.execute(f"SELECT {col_name} FROM {table} LIMIT 1")
            except sqlite3.OperationalError:
                # La colonne n'existe pas, on l'ajoute
                try:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                    logger.info(f"🛠️ Migration : Colonne '{col_name}' ajoutée à la table '{table}'.")
                except Exception as e:
                    logger.error(f"❌ Erreur migration {table}.{col_name}: {e}")

    # Colonnes spécifiques à la table 'players' (Transition V12 -> V14)
    player_cols = [
        ("score_but", "REAL"), ("score_assist", "REAL"), ("score_point", "REAL"),
        ("picked_but", "BOOLEAN"), ("picked_assist", "BOOLEAN"), ("picked_point", "BOOLEAN"),
        ("l10_a", "REAL"), ("l10_pts", "REAL"), ("season_a", "REAL"), ("season_pts", "REAL"),
        ("assist", "INTEGER DEFAULT NULL"), ("point", "INTEGER DEFAULT NULL")
    ]
    for col_name, col_type in player_cols:
        try:
            c.execute(f"ALTER TABLE players ADD COLUMN {col_name} {col_type}")
            logger.info(f"Migration V14 : Colonne '{col_name}' ajoutée à la table 'players'.")
        except sqlite3.OperationalError: pass
    
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

def insert_parlay(parlay_data: Dict[str, Any], conn: Optional[sqlite3.Connection] = None) -> None:
    """
    Inserts a generated parlay (combiné) into the picks_parlays table.
    """
    auto_close = conn is None
    if auto_close:
        conn = get_connection()
    c = conn.cursor()

    cols = ', '.join(parlay_data.keys())
    placeholders = ', '.join(['?'] * len(parlay_data))

    sql = f'INSERT INTO picks_parlays ({cols}) VALUES ({placeholders})'
    c.execute(sql, list(parlay_data.values()))

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

def get_roi_stats(table: str = "picks", target_col: str = "but", days: str = "all", game_mode: str = "all") -> str:
    """
    Calculates and returns ROI statistics for a specific market.
    Uses actual odds (cote) for profit calculation when available.

    Args:
        table: The table to query.
        target_col: The column representing the result (but, assist, point).
        days: 'all' or string number of days.
        game_mode: 'all', 'regular', or 'playoff' to filter by game mode.

    Returns:
        A formatted HTML string with ROI stats.
    """
    conn = get_connection()
    c = conn.cursor()

    query = f"SELECT {target_col}, cote, verdict FROM {table} WHERE {target_col} IS NOT NULL AND {target_col} != ''"
    if days != "all":
        try:
            days_int = int(days)
            cutoff = (datetime.now() - timedelta(days=days_int)).strftime('%Y-%m-%d')
            query += f" AND date >= '{cutoff}'"
        except ValueError:
            pass

    if game_mode in ("regular", "playoff"):
        query += f" AND game_mode = '{game_mode}'"

    c.execute(query)
    rows = c.fetchall()
    conn.close()

    if not rows:
        return f"Pas assez de données pour {table}."

    # Calculer la cote moyenne pour les cotes manquantes
    cotes_valides = [r[1] for r in rows if r[1] is not None and r[1] != '']
    mean_cote = round(sum(cotes_valides) / len(cotes_valides), 2) if cotes_valides else 1.85

    total_played = len(rows)
    total_won = 0
    global_units = 0.0
    cat_stats = {}

    for result, cote, verdict in rows:
        result = int(result) if result else 0
        cote = float(cote) if cote else mean_cote

        unit = (cote - 1) if result > 0 else -1.0
        if result > 0:
            total_won += 1
        global_units += unit

        if verdict not in cat_stats:
            cat_stats[verdict] = {"played": 0, "won": 0, "units": 0.0}
        cat_stats[verdict]["played"] += 1
        if result > 0:
            cat_stats[verdict]["won"] += 1
        cat_stats[verdict]["units"] += unit

    global_units = round(global_units, 1)
    global_sign = "+" if global_units > 0 else ""
    winrate_global = (total_won / total_played) * 100
    roi_pct = round((global_units / total_played) * 100, 1)

    msg = f"<b>📊 STATS {table.upper()} : {global_sign}{global_units} U (ROI {roi_pct}%)</b>\n"
    msg += f"{total_won}✅ / {total_played} ({winrate_global:.1f}%) | Cote moy: {mean_cote}\n"
    msg += "──────────────────\n"

    for verdict in sorted(cat_stats.keys()):
        s = cat_stats[verdict]
        if s["played"] > 0:
            units_cat = round(s["units"], 1)
            cat_sign = "+" if units_cat > 0 else ""
            roi_cat = (s["won"] / s["played"]) * 100
            msg += f"<b>{verdict} [{cat_sign}{units_cat} U]</b> : {s['won']}✅ / {s['played']} ({roi_cat:.1f}%)\n"

    return msg

if not os.path.exists(DB_PATH):
    init_db()
else:
    # Trigger upgrade to V14 if tables missing
    init_db()
