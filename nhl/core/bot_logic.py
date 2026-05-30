import os
import csv
import json
import logging
import threading
from datetime import datetime, timedelta
import subprocess
import sys
from typing import Dict, List, Any, Optional, Set, Tuple

# Ajout du dossier racine au sys.path pour permettre l'exécution standalone
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.loaders as loaders
import core.scraper as scraper

import asyncio
from nhl.core.datastore import DataStore
from nhl.core.services import TelegramNotifier
from nhl.config.settings import cfg

logger = logging.getLogger("NHL.BotLogic")

from shared.base_bot import BaseSportBot
from shared.portfolio import Portfolio

class NhlBot(BaseSportBot):
    """
    Main logic for the NHL Betting Bot.
    Handles scanning, wave management, analysis, and notification.
    """
    sport_name = "NHL"

    def __init__(self, datastore: DataStore, telegram_notifier: TelegramNotifier) -> None:
        """
        Initializes the NhlBot.

        Args:
            datastore: The DataStore instance for in-memory data access.
            telegram_notifier: The TelegramNotifier instance for sending alerts.
        """
        super().__init__()
        self.datastore = datastore
        self.telegram = telegram_notifier
        self.portfolio = Portfolio()

        self.matchs_traites: Set[str] = set()
        self.matches_du_jour: List[Dict[str, Any]] = []
        self.compos_en_memoire: Dict[str, Dict[str, Any]] = {}
        self.vagues_envoyees: Set[str] = set()
        self.matchs_envoyes: Set[str] = set()
        self._scan_lock = threading.Lock()

        self.ecart_max_vague_min: int = cfg.wave.ecart_max_min
        self.force_envoi_min_avant: int = cfg.wave.force_envoi_min_avant
        self.log_path: str = './stats/picks_log.csv'
        self.players_log_path: str = './stats/players_log.csv'
        self.fichier_compos_temp: str = "compos_live.txt"

    @staticmethod
    def get_nhl_session_date() -> str:
        """
        Returns the current NHL session date (J-1 if before 07:00 AM).
        
        Returns:
            Date string in YYYY-MM-DD format.
        """
        return (datetime.now() - timedelta(hours=14)).strftime("%Y-%m-%d")

    def is_active_hours(self) -> bool:
        """
        Checks if the current time is within active scanning hours.

        Returns:
            True if active, False otherwise.
        """
        now = datetime.now()
        hour = now.hour
        return (hour > 16 or (hour == 16 and datetime.now().minute >= 30)) or hour <= 4

    def update_daily_stats(self) -> bool:
        """
        Ensures daily CSV stats are updated and loaded into DataStore.

        Returns:
            True if successful, False otherwise.
        """
        now = datetime.now()
        nhl_date = self.get_nhl_session_date()

        ok, ko_files = self._check_csv_integrity()

        if self.datastore.last_load_date != nhl_date or not ok:
            if not ok and self.datastore.last_load_date == nhl_date:
                logger.warning(f"[{now.strftime('%H:%M:%S')}] CSV KO : {', '.join(ko_files)} — Re-extraction forcée...")
            else:
                logger.info(f"\n[{now.strftime('%H:%M:%S')}] MISE À JOUR API NHL EN COURS...")

            try:
                from nhl.data.fetcher import update_all_stats_sync
                update_all_stats_sync()
                
                ok2, ko2 = self._check_csv_integrity()
                if not ok2:
                    logger.error(f"ÉCHEC CRITIQUE: Fichiers manquants après mise à jour: {', '.join(ko2)}")
                    return False

                self.datastore.force_refresh()
                logger.info("Fichiers API NHL mis à jour avec succès et chargés en RAM.")
                return True
            except Exception as e:
                logger.error(f"Exception lors de la mise à jour des stats : {e}")
                import traceback
                logger.error(traceback.format_exc())
                return False

        return True

    def _check_csv_integrity(self) -> Tuple[bool, List[str]]:
        """
        Checks if all required CSV files exist and have minimum required lines.

        Returns:
            A tuple (is_ok, list_of_errors).
        """
        required_csv = {
            "last 10.csv": 50, "Player Season Totals.csv": 200, "team.csv": 10,
            "power play.csv": 50, "goalies.csv": 30, "on_ice.csv": 50, "pk.csv": 10,
        }
        ko = []
        for filename, min_lines in required_csv.items():
            path = f"./stats/{filename}"
            if not os.path.exists(path):
                ko.append(f"{filename} (manquant)")
                continue
            try:
                with open(path, encoding="utf-8-sig") as f:
                    nb = sum(1 for _ in f)
                if nb < min_lines:
                    ko.append(f"{filename} ({nb} lignes < {min_lines} attendues)")
            except Exception as e:
                ko.append(f"{filename} (erreur : {e})")
        return (len(ko) == 0, ko)

    def parse_match_datetime(self, time_str: str) -> Optional[datetime]:
        """Parses Flashscore time string into a datetime object."""
        now = datetime.now()
        try:
            dt = datetime.strptime(f"{time_str} {now.year}", "%d.%m. %H:%M %Y")
            if dt < now - timedelta(hours=12):
                dt += timedelta(days=1)
            return dt
        except Exception:
            return None

    def purge_old_matches(self) -> None:
        """Removes matches older than 5 minutes from memory."""
        now = datetime.now()
        a_supprimer = []
        for match_id, data in self.compos_en_memoire.items():
            dt = self.parse_match_datetime(data["match_info"]["time"])
            if dt and now > dt + timedelta(minutes=5):
                a_supprimer.append(match_id)
        for m_id in a_supprimer:
            del self.compos_en_memoire[m_id]
            logger.info(f"   Match {m_id} purgé de la mémoire.")

    def build_waves(self, match_ids: List[str]) -> List[List[str]]:
        """Groups matches into waves based on their start time proximity."""
        if not match_ids:
            return []
        sorted_matches = sorted(
            match_ids,
            key=lambda mid: self.parse_match_datetime(self.compos_en_memoire[mid]["match_info"]["time"]) or datetime.max
        )
        waves = []
        curr_wave = [sorted_matches[0]]
        for i in range(1, len(sorted_matches)):
            prev_dt = self.parse_match_datetime(self.compos_en_memoire[sorted_matches[i-1]]["match_info"]["time"])
            curr_dt = self.parse_match_datetime(self.compos_en_memoire[sorted_matches[i]]["match_info"]["time"])

            ecart = (curr_dt - prev_dt).total_seconds() / 60 if prev_dt and curr_dt else 999

            if ecart <= self.ecart_max_vague_min:
                curr_wave.append(sorted_matches[i])
            else:
                waves.append(curr_wave)
                curr_wave = [sorted_matches[i]]
        waves.append(curr_wave)
        return waves

    def is_wave_complete(self, wave_ids: List[str], all_matches: List[Dict[str, Any]]) -> bool:
        """Checks if all matches in a time window have lineups available."""
        first_dt = self.parse_match_datetime(self.compos_en_memoire[wave_ids[0]]["match_info"]["time"])
        last_dt = self.parse_match_datetime(self.compos_en_memoire[wave_ids[-1]]["match_info"]["time"])
        if not first_dt or not last_dt: return True

        window_start = first_dt - timedelta(minutes=1)
        window_end = last_dt + timedelta(minutes=self.ecart_max_vague_min)

        for m in all_matches:
            m_dt = self.parse_match_datetime(m["time"])
            if m_dt and window_start <= m_dt <= window_end:
                if m["id"] not in self.compos_en_memoire:
                    return False
        return True

    def should_force_send(self, wave_ids: List[str]) -> bool:
        """Checks if a wave should be sent regardless of completeness due to time limit."""
        first_dt = self.parse_match_datetime(self.compos_en_memoire[wave_ids[0]]["match_info"]["time"])
        if not first_dt: return False
        mins_before = (first_dt - datetime.now()).total_seconds() / 60
        return mins_before <= self.force_envoi_min_avant

    def run_scan_cycle(self) -> None:
        """Main periodic task: scans Flashscore, updates lineups, and triggers evaluation."""
        if not self._scan_lock.acquire(blocking=False):
            logger.warning("Un scan est déjà en cours. Ignoré pour éviter les lancements multiples.")
            return
        try:
            if not self.update_daily_stats():
                logger.warning("Analyse suspendue — CSV invalides.")
                return

            mode_icon = "🏆" if cfg.api.mode == "playoff" else "🏒"
            logger.info(f"\n[{datetime.now().strftime('%H:%M:%S')}] {mode_icon} Lancement du scan API / RotoWire (Mode: {cfg.api.mode})...")
            self.purge_old_matches()

            self.matches_du_jour = scraper.get_scheduled_matches()

            if not self.is_active_hours():
                logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Hors horaires (05h-17h). Scan des compos ignoré.")
                return

            for m in self.matches_du_jour:
                match_id = m['id']
                if match_id in self.matchs_traites:
                    continue

                logger.info(f"   Vérification compo : {m['home']} - {m['away']}...")
                compo = scraper.get_lineups(match_id, m['home'], m['away'])

                if isinstance(compo, dict):
                    logger.info("    COMPO TROUVÉE ! Mise en mémoire.")
                    self.compos_en_memoire[match_id] = {"match_info": m, "compo": compo}
                    self.matchs_traites.add(match_id)
                else:
                    logger.info(f"   {compo} — On réessaiera au prochain cycle.")

            self.evaluate_waves(self.matches_du_jour)
        except Exception as e:
            logger.error(f"ERREUR CRITIQUE lors du run_scan_cycle : {e}", exc_info=True)
            self.telegram.send_crash_alert(e, context="run_scan_cycle")
        finally:
            self._scan_lock.release()

    def evaluate_waves(self, matches_du_jour: List[Dict[str, Any]]) -> None:
        """Processes available lineups into waves and triggers analysis."""
        if not self.compos_en_memoire:
            return

        # Filtrer les matchs déjà envoyés pour éviter les doublons
        pending_ids = [mid for mid in self.compos_en_memoire if mid not in self.matchs_envoyes]
        if not pending_ids:
            return

        waves = self.build_waves(pending_ids)
        ready_ids = []
        
        for wave in waves:
            wave_key = self.compos_en_memoire[wave[0]]["match_info"]["time"]
            if wave_key in self.vagues_envoyees:
                continue

            if self.is_wave_complete(wave, matches_du_jour) or self.should_force_send(wave):
                self.vagues_envoyees.add(wave_key)
                for mid in wave:
                    self.matchs_envoyes.add(mid)
                    ready_ids.append(mid)
                    
        if ready_ids:
            wave_label = f"Matchs du Jour ({len(ready_ids)} matchs)"
            logger.info(f"   Vagues combinées {wave_label}   ENVOI !")
            self.run_analysis_and_send(ready_ids, wave_label)

    def run_analysis_and_send(self, wave_ids: List[str], wave_label: str) -> None:
        """Performs analysis on a wave of matches and sends results."""
        from nhl.core.market_filter import load_ml_models, prepare_features_for_player, evaluate_player_markets
        from nhl.core.kelly import is_cote_valid, apply_kelly_to_picks
        from nhl.core.formatter import format_telegram_v18
        from nhl.core.logger_csv import log_picks_to_db, log_picks_to_csv

        logger.info(f"\n--- ANALYSE VAGUE {wave_label} ---")

        with open(self.fichier_compos_temp, "w", encoding="utf-8") as f:
            for mid in wave_ids:
                data = self.compos_en_memoire[mid]
                m = data["match_info"]
                c = data["compo"]
                f.write(f"Match : {m['home']} - {m['away']} ({m['time']})\n"
                        f"  goal dom: {c['goalDom']}\n  goal ext: {c['goalext']}\n"
                        f"  f1 dom: {c['f1_dom']}\n  f1 ext: {c['f1_ext']}\n"
                        f"  f2 dom: {c['f2_dom']}\n  f2 ext: {c['f2_ext']}\n"
                        f"{'-'*40}\n")

        ds = self.datastore
        TODAY = datetime.now().strftime("%Y-%m-%d")

        matches_soir = []
        compos_brutes = []
        goalies = set()

        for mid in wave_ids:
            m = self.compos_en_memoire[mid]["match_info"]
            c = self.compos_en_memoire[mid]["compo"]
            
            home, away = m["home"], m["away"]
            matches_soir.append((home, away))
            
            if c.get("goalDom"): goalies.add(c["goalDom"])
            if c.get("goalext"): goalies.add(c["goalext"])
            
            for key in ["f1_dom", "f1_ext", "f2_dom", "f2_ext"]:
                if key in c and isinstance(c[key], list):
                    for player in c[key]:
                        if player in ds.known_players:
                            compos_brutes.append(player)
                        else:
                            from shared.utils import normalize_name
                            n_player = normalize_name(player)
                            matched = False
                            for known_p in ds.known_players:
                                if normalize_name(known_p) == n_player:
                                    compos_brutes.append(known_p)
                                    matched = True
                                    break
                            if not matched:
                                compos_brutes.append(player)

        compos_filtrees = [p for p in compos_brutes if p in ds.form_data]
        home_teams = [m[0] for m in matches_soir]
        opponents = {t1: t2 for t1, t2 in matches_soir}
        opponents.update({t2: t1 for t1, t2 in matches_soir})

        b2b_teams = [t for t in loaders.get_b2b_teams('./stats/match.csv', TODAY) if t in opponents]
        pp1_players = set(loaders.get_auto_pp1_players(ds.form_data, ds.pp_stats, list(opponents.keys())))
        seen_players: Set[str] = set()

        ml_models = load_ml_models()

        final_picks_but: List[Dict[str, Any]] = []
        final_picks_ast: List[Dict[str, Any]] = []
        all_evaluated_players: List[Dict[str, Any]] = []

        for player in compos_filtrees:
            if player in seen_players:
                continue
            seen_players.add(player)

            p_form = ds.form_data[player]
            team = loaders.clean_team_name(p_form['Team'])
            if p_form['ATOI'] < cfg.thresholds.general.atoi_min or team not in opponents:
                continue

            adv = opponents[team]
            adv_stats = ds.matchups.get(adv) or {}
            is_backup = loaders.check_if_backup_goalie(goalies.get(adv, ""), ds.goalie_stats)
            v5_p = ds.v5_data.get(player, {})
            is_home = team in home_teams

            cat_but, cat_ast = evaluate_player_markets(
                player, p_form, v5_p, adv_stats, is_home
            )

            is_pp1 = player in pp1_players
            is_b2b = team in b2b_teams and adv not in b2b_teams
            opp_is_b2b = adv in b2b_teams and team not in b2b_teams
            
            common_data = {
                "Joueur": player, "Equipe": team, "Adversaire": adv, "IsHome": is_home,
                "Pos": str(v5_p.get('Position', '')).strip() if v5_p else "",
                "PP1": "⭐" if is_pp1 else "",
                "Backup": is_backup, "B2B": is_b2b,
                "Synergie": False
            }

            proba_but, proba_ast = 0.0, 0.0

            if cat_but or cat_ast:
                consec = int(p_form.get('ConsecGoals', 0))
                feat_list = []
                if 'but' in ml_models: feat_list = ml_models['but'].get('features', [])
                elif 'ast' in ml_models: feat_list = ml_models['ast'].get('features', [])
                
                if feat_list:
                    X_player = prepare_features_for_player(
                        p_form, v5_p, adv_stats, is_home, 
                        is_b2b, opp_is_b2b, is_pp1, consec, feat_list
                    )
                    
                    if cat_but and 'but' in ml_models:
                        m_data = ml_models['but']
                        proba_but = float(m_data['model'].predict_proba(X_player)[0, 1])
                        p_but = common_data.copy()
                        p_but.update({"Proba": proba_but, "Categorie": cat_but})
                        final_picks_but.append(p_but)
                        
                    if cat_ast and 'ast' in ml_models:
                        m_data = ml_models['ast']
                        X_pred = X_player
                        if m_data.get('algo') == 'logreg' and 'scaler' in m_data:
                            X_pred = m_data['scaler'].transform(X_pred)
                        proba_ast = float(m_data['model'].predict_proba(X_pred)[0, 1])
                        p_ast = common_data.copy()
                        p_ast.update({"Proba": proba_ast, "Categorie": cat_ast})
                        final_picks_ast.append(p_ast)

            all_evaluated_players.append({
                "Joueur": player, "Equipe": team, "Adversaire": adv, "IsHome": is_home,
                "Score_But": proba_but, "Score_Assist": proba_ast, "Score_Point": 0.0,
                "Picked_But": bool(cat_but), "Picked_Assist": bool(cat_ast), "Picked_Point": False,
                "Backup": is_backup, "B2B": is_b2b,
                "p_form": p_form, "p_v5": ds.v5_data.get(player, {}), "adv_stats": adv_stats
            })

        players_to_fetch = {r["Joueur"]: r["Equipe"] for picks_list in (final_picks_but, final_picks_ast) for r in picks_list}
        odds_map = {}
        if players_to_fetch:
            logger.info(f"Récupération des cotes (API) pour {len(players_to_fetch)} joueurs...")
            from shared.odds_api import fetch_nhl_odds
            odds_map = asyncio.run(fetch_nhl_odds(players_to_fetch))
            
            any_odds_found = any(
                (data.get('BUTS') is not None) or (data.get('ASSISTS') is not None)
                for data in odds_map.values()
            )
            if not any_odds_found:
                logger.error("ALERTE CRITIQUE : AUCUNE COTE TROUVÉE POUR AUCUN JOUEUR DE LA VAGUE !")
                self.telegram.send_message(f"🚨 <b>ALERTE CRITIQUE SCRAPER</b> 🚨\nLe scraper de cotes n'a trouvé absolument <b>aucune cote</b> pour l'ensemble des {len(players_to_fetch)} joueurs de la vague {wave_label}.\nThe Odds API n'a renvoyé aucune cote ou la vérification des noms d'équipe a échoué.")

            for p in final_picks_but:
                odds_data = odds_map.get(p["Joueur"], {}).get("BUTS", {})
                if isinstance(odds_data, dict):
                    p["Cote"] = odds_data.get("price")
                    p["Bookmaker"] = odds_data.get("bookmaker", "Inconnu")
                else:
                    p["Cote"] = None
                    p["Bookmaker"] = "Inconnu"
            for p in final_picks_ast:
                odds_data = odds_map.get(p["Joueur"], {}).get("ASSISTS", {})
                if isinstance(odds_data, dict):
                    p["Cote"] = odds_data.get("price")
                    p["Bookmaker"] = odds_data.get("bookmaker", "Inconnu")
                else:
                    p["Cote"] = None
                    p["Bookmaker"] = "Inconnu"

        final_picks_but = [p for p in final_picks_but if is_cote_valid(p, cfg.thresholds.buteurs.cote_min)]
        final_picks_ast = [p for p in final_picks_ast if is_cote_valid(p, cfg.thresholds.passeurs.cote_min)]

        current_exposure = self.portfolio.get_pending_exposure()
        max_exposure = 15.0
        
        for picks_list in [final_picks_but, final_picks_ast]:
            current_exposure = apply_kelly_to_picks(picks_list, current_exposure, max_exposure)
            
        msg = format_telegram_v18(
            final_picks_but, final_picks_ast, [],
            wave_label, wave_ids, self.compos_en_memoire
        )
        self.telegram.send_message(msg)

        session_date = self.get_nhl_session_date()
        log_picks_to_db(final_picks_but, final_picks_ast, [], all_evaluated_players, wave_label, session_date, ds)
        log_picks_to_csv(final_picks_but, final_picks_ast, [], all_evaluated_players, wave_label, session_date, self.log_path, self.players_log_path)

    # Plafonds exposés pour les tests (délègue au module kelly)
    from nhl.core.kelly import CATEGORY_CAPS

    def _calculate_quarter_kelly(self, proba: float, cote: float, categorie: str = "") -> str:
        """Proxy vers core.kelly.calculate_quarter_kelly pour compatibilité."""
        from nhl.core.kelly import calculate_quarter_kelly
        return calculate_quarter_kelly(proba, cote, categorie)

    def end_of_day_cleanup(self) -> None:
        """Resolves pending picks and cleans up session data."""
        try:
            from nhl.core.updater import update_pending_picks
            logger.info("🔄 Auto-résolution des résultats dans la DB avant le rapport final...")
            update_pending_picks()
        except Exception as e:
            logger.error(f"Erreur auto-résolution : {e}")

        if self.matchs_traites:

            self.matchs_traites.clear()
            self.compos_en_memoire.clear()
            self.vagues_envoyees.clear()
            self.matchs_envoyes.clear()
            logger.info("Nettoyage de fin de journée terminé.")

