"""
core/logger_csv.py — Logging des picks et joueurs en SQL et CSV.

Extrait de bot_logic.py pour séparation des responsabilités.
"""
import os
import csv
import logging
from typing import Dict, List, Any

from nhl.core.database import insert_pick, insert_player
from nhl.config.settings import cfg

logger = logging.getLogger("NHL.LoggerCSV")


def log_picks_to_db(
    buts: List[Dict[str, Any]],
    asts: List[Dict[str, Any]],
    pts: List[Dict[str, Any]],
    all_players: List[Dict[str, Any]],
    wave_label: str,
    today: str,
    ds: Any,
) -> None:
    """Insère les picks et les joueurs évalués dans la base SQLite.

    Args:
        buts: Picks buteurs sélectionnés.
        asts: Picks passeurs sélectionnés.
        pts: Picks pointeurs sélectionnés.
        all_players: Tous les joueurs évalués (picks + non-picks).
        wave_label: Label de la vague.
        today: Date de la session NHL (YYYY-MM-DD).
        ds: DataStore pour accéder aux form_data, v5_data, matchups.
    """
    for p in buts:
        f = ds.form_data.get(p["Joueur"], {})
        v5 = ds.v5_data.get(p["Joueur"], {})
        adv = ds.matchups.get(p["Adversaire"], {})
        insert_pick("picks", {
            "date": today, "vague": wave_label, "joueur": p["Joueur"], "equipe": p["Equipe"],
            "adversaire": p["Adversaire"], "score": p.get("Proba", 0), "verdict": p["Categorie"],
            "pp1": bool(p["PP1"]), "backup": p["Backup"], "b2b": p["B2B"], "is_home": p["IsHome"],
            "ixg": f.get("L10_ixG_G", 0), "hdcf": f.get("L10_iHDCF_G", 0), "sog": f.get("L10_SOG_G", 0),
            "atoi": f.get("ATOI", 0), "l10_g": f.get("L10_G_G", 0), "season_g": v5.get("G_GP", 0),
            "pdo": v5.get("PDO", 100), "ga_g": adv.get("GA_G", 0),
            "cf_pct": adv.get("CF_pct", 50), "hdca_g": adv.get("HDCA_G", 0),
            "pk_pct": adv.get("PK%", 80), "rebounds": f.get("L10_Rebounds_G", 0),
            "rush": f.get("L10_Rush_G", 0), "opp_b2b": adv.get("B2B", False),
            "consec_goals": f.get("ConsecGoals", 0), "cote": p.get("Cote"),
            "mise": p.get("MiseNum"), "game_mode": cfg.api.mode
        })

    for p in asts:
        f = ds.form_data.get(p["Joueur"], {})
        v5 = ds.v5_data.get(p["Joueur"], {})
        adv = ds.matchups.get(p["Adversaire"], {})
        insert_pick("picks_assists", {
            "date": today, "vague": wave_label, "joueur": p["Joueur"], "equipe": p["Equipe"],
            "adversaire": p["Adversaire"], "score": p.get("Proba", 0), "verdict": p["Categorie"],
            "pp1": bool(p["PP1"]), "backup": p["Backup"], "b2b": p["B2B"], "is_home": p["IsHome"],
            "atoi": f.get("ATOI", 0), "l10_a": f.get("L10_A_G", 0), "season_a": v5.get("A_GP", 0),
            "pdo": v5.get("PDO", 100), "ga_g": adv.get("GA_G", 0),
            "cf_pct": adv.get("CF_pct", 50), "pk_pct": adv.get("PK%", 80),
            "opp_b2b": adv.get("B2B", False), "cote": p.get("Cote"),
            "mise": p.get("MiseNum"), "game_mode": cfg.api.mode
        })

    for p in pts:
        f = ds.form_data.get(p["Joueur"], {})
        v5 = ds.v5_data.get(p["Joueur"], {})
        adv = ds.matchups.get(p["Adversaire"], {})
        insert_pick("picks_points", {
            "date": today, "vague": wave_label, "joueur": p["Joueur"], "equipe": p["Equipe"],
            "adversaire": p["Adversaire"], "score": p.get("Proba", 0), "verdict": p["Categorie"],
            "pp1": bool(p["PP1"]), "backup": p["Backup"], "b2b": p["B2B"], "is_home": p["IsHome"],
            "atoi": f.get("ATOI", 0), "l10_pts": f.get("L10_Pts_G", 0), "season_pts": v5.get("Pts_GP", 0),
            "pdo": v5.get("PDO", 100), "ga_g": adv.get("GA_G", 0),
            "cf_pct": adv.get("CF_pct", 50),
            "opp_b2b": adv.get("B2B", False), "cote": p.get("Cote"),
            "mise": p.get("MiseNum"), "game_mode": cfg.api.mode
        })

    # Unified Player SQL Log
    for p in all_players:
        f, v5, adv = p["p_form"], p["p_v5"], p["adv_stats"]
        insert_player({
            "date": today, "vague": wave_label, "joueur": p["Joueur"], "equipe": p["Equipe"], "adversaire": p["Adversaire"],
            "score_but": p["Score_But"], "score_assist": p["Score_Assist"], "score_point": p["Score_Point"],
            "picked_but": p["Picked_But"], "picked_assist": p["Picked_Assist"], "picked_point": p["Picked_Point"],
            "pp1": "⭐" in f.get("PP1", ""), "backup": p["Backup"], "b2b": p["B2B"], "is_home": p["IsHome"],
            "ixg": f.get("L10_ixG_G", 0), "hdcf": f.get("L10_iHDCF_G", 0), "sog": f.get("L10_SOG_G", 0),
            "atoi": f.get("ATOI", 0), "l10_g": f.get("L10_G_G", 0), "l10_a": f.get("L10_A_G", 0), "l10_pts": f.get("L10_Pts_G", 0),
            "season_g": v5.get("G_GP", 0), "season_a": v5.get("A_GP", 0), "season_pts": v5.get("Pts_GP", 0),
            "pdo": v5.get("PDO", 100), "ga_g": adv.get("GA_G", 0) if adv else 0,
            "cf_pct": adv.get("CF_pct", 50) if adv else 50, "hdca_g": adv.get("HDCA_G", 0) if adv else 0,
            "pk_pct": adv.get("PK%", 80) if adv else 80,
            "consec_goals": f.get("ConsecGoals", 0), "game_mode": cfg.api.mode
        })


def log_picks_to_csv(
    buts: List[Dict[str, Any]],
    asts: List[Dict[str, Any]],
    pts: List[Dict[str, Any]],
    all_players: List[Dict[str, Any]],
    wave_label: str,
    today: str,
    log_path: str,
    players_log_path: str,
) -> None:
    """Écrit les picks et joueurs dans les fichiers CSV de suivi.

    Args:
        buts: Picks buteurs.
        asts: Picks passeurs.
        pts: Picks pointeurs.
        all_players: Tous les joueurs évalués.
        wave_label: Label de la vague.
        today: Date de la session NHL.
        log_path: Chemin du CSV picks.
        players_log_path: Chemin du CSV joueurs.
    """
    def format_csv(val: Any) -> Any:
        return str(val).replace('.', cfg.csv.decimal_separator) if isinstance(val, float) else val

    # Picks CSV
    file_exists = os.path.exists(log_path)
    try:
        with open(log_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['date', 'vague', 'joueur', 'type', 'score', 'cote', 'but'])
            if not file_exists:
                writer.writeheader()
            for p in buts:
                writer.writerow({k: format_csv(v) for k, v in {"date": today, "vague": wave_label, "joueur": p["Joueur"], "type": "BUT", "score": p.get("Proba", 0), "cote": p.get("Cote", ""), "but": ""}.items()})
            for p in asts:
                writer.writerow({k: format_csv(v) for k, v in {"date": today, "vague": wave_label, "joueur": p["Joueur"], "type": "ASSIST", "score": p.get("Proba", 0), "cote": p.get("Cote", ""), "but": ""}.items()})
            for p in pts:
                writer.writerow({k: format_csv(v) for k, v in {"date": today, "vague": wave_label, "joueur": p["Joueur"], "type": "POINT", "score": p.get("Proba", 0), "cote": p.get("Cote", ""), "but": ""}.items()})
    except Exception as e:
        logger.error(f"Error writing to picks_log.csv: {e}")

    # Players CSV
    pl_exists = os.path.exists(players_log_path)
    try:
        with open(players_log_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['date', 'vague', 'joueur', 'score_but', 'score_ast', 'score_pts'])
            if not pl_exists:
                writer.writeheader()
            for p in all_players:
                writer.writerow({k: format_csv(v) for k, v in {"date": today, "vague": wave_label, "joueur": p["Joueur"], "score_but": p["Score_But"], "score_ast": p["Score_Assist"], "score_pts": p["Score_Point"]}.items()})
    except Exception as e:
        logger.error(f"Error writing to players_log.csv: {e}")
