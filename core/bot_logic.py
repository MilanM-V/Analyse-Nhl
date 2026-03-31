import os
import csv
import logging
from datetime import datetime, timedelta
import subprocess
import sys
from typing import Dict, List, Any, Optional, Set, Tuple

import core.loaders as loaders
import core.scraper as scraper
import core.predictor_v14 as predictor_v14
from core.datastore import DataStore
from core.services import TelegramNotifier

logger = logging.getLogger("NHL_Bot")

class NhlBot:
    """
    Main logic for the NHL Betting Bot.
    Handles scanning, wave management, analysis, and notification.
    """
    def __init__(self, datastore: DataStore, telegram_notifier: TelegramNotifier) -> None:
        """
        Initializes the NhlBot.

        Args:
            datastore: The DataStore instance for in-memory data access.
            telegram_notifier: The TelegramNotifier instance for sending alerts.
        """
        self.datastore = datastore
        self.telegram = telegram_notifier

        self.matchs_traites: Set[str] = set()
        self.matches_du_jour: List[Dict[str, Any]] = []
        self.compos_en_memoire: Dict[str, Dict[str, Any]] = {}
        self.vagues_envoyees: Set[str] = set()
        self._is_scanning: bool = False

        self.ecart_max_vague_min: int = 5
        self.force_envoi_min_avant: int = 17
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
                cflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
                subprocess.run([sys.executable, "fichier.py"], check=True, creationflags=cflags)
                ok2, ko2 = self._check_csv_integrity()
                if ok2:
                    self.datastore.force_refresh()
                    logger.info("Fichiers API NHL mis à jour avec succès et chargés en RAM.")
                    return True
                else:
                    logger.warning(f"CSV toujours KO après extraction : {', '.join(ko2)}")
                    return False
            except Exception as e:
                logger.warning(f"Erreur fichier.py : {e}")
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
        if self._is_scanning:
            logger.warning("Un scan est déjà en cours. Ignoré pour éviter les lancements multiples.")
            return

        self._is_scanning = True
        try:
            if not self.update_daily_stats():
                logger.warning("Analyse suspendue — CSV invalides.")
                return

            logger.info(f"\n[{datetime.now().strftime('%H:%M:%S')}] Lancement du scan Flashscore...")
            self.purge_old_matches()

            with scraper.ScraperDriverContext() as driver:
                self.matches_du_jour = scraper.get_scheduled_matches("https://www.flashscore.fr/hockey/usa/nhl/calendrier/", driver=driver)

                if not self.is_active_hours():
                    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Hors horaires (05h-17h). Scan des compos ignoré.")
                    return

                for m in self.matches_du_jour:
                    match_id = m['id']
                    if match_id in self.matchs_traites:
                        continue

                    logger.info(f"   Vérification compo : {m['home']} - {m['away']}...")
                    compo = scraper.get_lineups(match_id, m['home'], m['away'], driver=driver)

                    if isinstance(compo, dict):
                        logger.info("    COMPO TROUVÉE ! Mise en mémoire.")
                        self.compos_en_memoire[match_id] = {"match_info": m, "compo": compo}
                        self.matchs_traites.add(match_id)
                    else:
                        logger.info(f"   {compo} — On réessaiera au prochain cycle.")

            self.evaluate_waves(self.matches_du_jour)
        except Exception as e:
            logger.error(f"ERREUR CRITIQUE lors du run_scan_cycle : {e}")
        finally:
            self._is_scanning = False

    def evaluate_waves(self, matches_du_jour: List[Dict[str, Any]]) -> None:
        """Processes available lineups into waves and triggers analysis."""
        if not self.compos_en_memoire:
            return

        waves = self.build_waves(list(self.compos_en_memoire.keys()))
        for wave in waves:
            wave_key = self.compos_en_memoire[wave[0]]["match_info"]["time"]
            if wave_key in self.vagues_envoyees:
                continue

            heures = [self.compos_en_memoire[mid]["match_info"]["time"].split(" ")[1] for mid in wave]
            wave_label = heures[0] if len(heures) == 1 else f"{heures[0]}   {heures[-1]} ({len(wave)} matchs)"

            if self.is_wave_complete(wave, matches_du_jour):
                logger.info(f"   Vague {wave_label} complète   ENVOI !")
                self.run_analysis_and_send(wave, wave_label)
                self.vagues_envoyees.add(wave_key)
            elif self.should_force_send(wave):
                logger.info(f"   Vague {wave_label} forçage < {self.force_envoi_min_avant} min   ENVOI !")
                self.run_analysis_and_send(wave, wave_label + " ⚠️forcé")
                self.vagues_envoyees.add(wave_key)

    def run_analysis_and_send(self, wave_ids: List[str], wave_label: str) -> None:
        """Performs ML analysis on a wave of matches and sends results."""
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

        matches_soir, compos_brutes, goalies = predictor_v14.parse_flashscore_file(
            self.fichier_compos_temp, ds.known_players, ds.form_data
        )

        lines_index = {}
        try:
            with open(self.fichier_compos_temp, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(('f1 ', 'f2 ')):
                        players_on_line = [p.strip() for p in line.split(':', 1)[1].split(',') if p.strip()]
                        for p in players_on_line:
                            lines_index.setdefault(p, set()).update(players_on_line)
        except Exception:
            pass

        compos_filtrees = [p for p in compos_brutes if p in ds.form_data]
        home_teams = [m[0] for m in matches_soir]
        opponents = {t1: t2 for t1, t2 in matches_soir}
        opponents.update({t2: t1 for t1, t2 in matches_soir})

        b2b_teams = [t for t in predictor_v14.get_b2b_teams('./stats/match.csv', TODAY) if t in opponents]
        pp1_players = set(predictor_v14.get_auto_pp1_players(ds.form_data, ds.pp_stats, list(opponents.keys())))
        seen_players = set()

        final_picks_but = []
        final_picks_ast = []
        final_picks_pts = []
        all_evaluated_players = []

        for player in compos_filtrees:
            if player in seen_players:
                continue
            seen_players.add(player)

            p_form = ds.form_data[player]
            team = predictor_v14.clean_team_name(p_form['Team'])
            if p_form['ATOI'] < 13.0 or team not in opponents: continue

            adv = opponents[team]
            adv_stats = ds.matchups.get(adv)
            is_backup = predictor_v14.check_if_backup_goalie(goalies.get(adv, ""), ds.goalie_stats)

            # Analyse BUTS
            qs_but = predictor_v14.calculate_base_qs(
                ds.v5_data.get(player, {}), p_form, adv_stats,
                player in pp1_players, team in home_teams,
                False, is_backup, team in b2b_teams and adv not in b2b_teams
            )

            # Analyse ASSISTS
            qs_ast = predictor_v14.calculate_assist_qs(
                ds.v5_data.get(player, {}), p_form, adv_stats,
                player in pp1_players, team in home_teams,
                False, is_backup, team in b2b_teams and adv not in b2b_teams
            )

            # Analyse POINTS
            qs_pts = predictor_v14.calculate_points_qs(
                ds.v5_data.get(player, {}), p_form, adv_stats,
                player in pp1_players, team in home_teams,
                False, is_backup, team in b2b_teams and adv not in b2b_teams
            )

            # XGBoost & Catégories
            xgb_proba = predictor_v14.evaluate_xgb_proba(
                ds.v5_data.get(player, {}), p_form, adv_stats,
                team in home_teams, team in b2b_teams, adv in b2b_teams, 
                player in pp1_players, qs_but
            ) if qs_but > 0 else 0.0

            # Analyse SOG (Tirs)
            sog_score = predictor_v14.calculate_sog_score(p_form, adv_stats, player in pp1_players, team in home_teams)
            sog_proba = predictor_v14.evaluate_sog_proba(p_form, adv_stats, player in pp1_players, team in home_teams, sog_score)

            cat_but = self._get_categorie(qs_but, p_form.get('L10_iHDCF_G', 0), 
                                         ds.v5_data.get(player, {}).get('Position', ''), xgb_proba,
                                         sog_score, sog_proba)
            
            # Catégories PASSEURS (Optimisé via simulation 716k opportunités)
            cat_ast = "ELITE_PASSEUR" if qs_ast >= 11.5 else "SAFE_PASSEUR" if qs_ast >= 10.0 else None
            
            # Catégories POINTEURS (Optimisé via simulation 716k opportunités)
            cat_pts = "ELITE_POINTEUR" if qs_pts >= 12.0 else "SAFE_POINTEUR" if qs_pts >= 11.0 else None

            # Construction des dicts de picks
            common_data = {
                "Joueur": player, "Equipe": team, "Adversaire": adv, "IsHome": team in home_teams,
                "Pos": ds.v5_data.get(player, {}).get('Position', ''),
                "PP1": "⭐" if player in pp1_players else "",
                "Backup": is_backup, "B2B": team in b2b_teams and adv not in b2b_teams,
                "Synergie": False
            }

            if cat_but:
                p_but = common_data.copy()
                p_but.update({"Score": qs_but, "Proba": xgb_proba, "Categorie": cat_but})
                final_picks_but.append(p_but)
            
            if cat_ast:
                p_ast = common_data.copy()
                p_ast.update({"Score": qs_ast, "Categorie": cat_ast})
                final_picks_ast.append(p_ast)

            if cat_pts:
                p_pts = common_data.copy()
                p_pts.update({"Score": qs_pts, "Categorie": cat_pts})
                final_picks_pts.append(p_pts)

            # Log global
            all_evaluated_players.append({
                "Joueur": player, "Equipe": team, "Adversaire": adv, "IsHome": team in home_teams,
                "Score_But": qs_but, "Score_Assist": qs_ast, "Score_Point": qs_pts,
                "Picked_But": bool(cat_but), "Picked_Assist": bool(cat_ast), "Picked_Point": bool(cat_pts),
                "Backup": is_backup, "B2B": team in b2b_teams and adv not in b2b_teams,
                "p_form": p_form, "p_v5": ds.v5_data.get(player, {}), "adv_stats": adv_stats
            })

        # Synergie (Elite Linemates)
        elite_players = {r["Joueur"] for r in final_picks_but if r["Categorie"] == "ELITE"}
        for picks_list in (final_picks_but, final_picks_ast, final_picks_pts):
            for r in picks_list:
                linemates = lines_index.get(r["Joueur"], set())
                if bool(linemates & elite_players - {r["Joueur"]}):
                    r["Score"] = round(r["Score"] + 0.3, 1)
                    r["Synergie"] = True

        # Odds enrichment
        # Odds enrichment removed (odds-free mode)

        # Telegram Recap (Multi-marchés)
        self._send_telegram_v14(final_picks_but, final_picks_ast, final_picks_pts, wave_label, wave_ids)
        
        # Logging unifié
        self._log_v14(final_picks_but, final_picks_ast, final_picks_pts, all_evaluated_players, wave_label, ds)

    def _get_categorie(self, score: float, hdcf: float, pos: str, xgb_proba: float, sog_score: float = 0, proba_sog: float = 0) -> Optional[str]:
        """Assigns a betting category based on various metrics."""
        cat = None
        if pos in ('D', 'LD', 'RD'):
            if score >= 9.5 and xgb_proba >= 0.35: cat = "DÉFENSEUR"
        else:
            if score >= 9.75 and xgb_proba >= 0.65: cat = "ELITE"
            elif score >= 6.72 and xgb_proba >= 0.585: cat = "SAFE"
            
        # Fallback TIREUR : gros volume de tirs sans être un buteur d'élite
        if not cat and sog_score >= 8.5 and proba_sog >= 0.65:
            cat = "TIREUR"
            
        return cat

    def _send_telegram_v14(self, buts: List[Dict[str, Any]], assists: List[Dict[str, Any]], points: List[Dict[str, Any]], wave_label: str, wave_ids: List[str]) -> None:
        """Formats and sends the Telegram recap message with all markets."""
        msg = f"<b>🏒 NHL V14.1 — VAGUE {wave_label}</b>\n\n"
        
        for mid in wave_ids:
            data = self.compos_en_memoire.get(mid)
            if not data: continue
            
            m = data["match_info"]
            t1_full = loaders.REVERSE_TEAM_MAPPING.get(m['home'], m['home'])
            t2_full = loaders.REVERSE_TEAM_MAPPING.get(m['away'], m['away'])
            
            h_abbr = loaders.TEAM_MAPPING.get(m['home'], m['home'])
            a_abbr = loaders.TEAM_MAPPING.get(m['away'], m['away'])
            match_key = f"{h_abbr} vs {a_abbr}"
            
            msg += f"<b>Match {t1_full} vs {t2_full} :</b>\n"
            
            # BUTEURS
            m_buts = [r for r in buts if (r['Equipe'] == h_abbr or r['Equipe'] == a_abbr)]
            if m_buts:
                msg += "  🔥 <i>Buteurs :</i>\n"
                for r in m_buts:
                    msg += f"  • {'🏠' if r['IsHome'] else '✈️'} <b>{r['Joueur']}</b> ({r['Categorie']})\n"
            
            # PASSEURS
            m_ast = [r for r in assists if (r['Equipe'] == h_abbr or r['Equipe'] == a_abbr)]
            if m_ast:
                msg += "  🅰️ <i>Passeurs :</i>\n"
                for r in m_ast:
                    label = r['Categorie'].replace("_PASSEUR", "")
                    msg += f"  • {'🏠' if r['IsHome'] else '✈️'} <b>{r['Joueur']}</b> ({label})\n"
            
            # POINTS
            m_pts = [r for r in points if (r['Equipe'] == h_abbr or r['Equipe'] == a_abbr)]
            if m_pts:
                msg += "  🏆 <i>Pointeurs :</i>\n"
                for r in m_pts:
                    label = r['Categorie'].replace("_POINTEUR", "")
                    msg += f"  • {'🏠' if r['IsHome'] else '✈️'} <b>{r['Joueur']}</b> ({label})\n"
            
            if not m_buts and not m_ast and not m_pts:
                msg += "  <i>⚠️ Aucun pick sur ce match.</i>\n"
            msg += "\n"

        self.telegram.send_message(msg)

    def _log_v14(self, buts, asts, pts, all_players, wave_label, ds):
        """Logs everything to SQL tables and CSV files."""
        from core.database import insert_pick, insert_player
        import csv
        TODAY = self.get_nhl_session_date()

        # SQL Logging
        for p in buts:
            f, v5, adv = ds.form_data.get(p["Joueur"], {}), ds.v5_data.get(p["Joueur"], {}), ds.matchups.get(p["Adversaire"], {})
            insert_pick("picks", {
                "date": TODAY, "vague": wave_label, "joueur": p["Joueur"], "equipe": p["Equipe"],
                "adversaire": p["Adversaire"], "score": p["Score"], "verdict": p["Categorie"],
                "pp1": bool(p["PP1"]), "backup": p["Backup"], "b2b": p["B2B"], "is_home": p["IsHome"],
                "ixg": f.get("L10_ixG_G", 0), "hdcf": f.get("L10_iHDCF_G", 0), "sog": f.get("L10_SOG_G", 0),
                "atoi": f.get("ATOI", 0), "l10_g": f.get("L10_G_G", 0), "season_g": v5.get("G_GP", 0),
                "pdo": v5.get("PDO", 100), "ga_g": adv.get("GA_G", 0),
                "cf_pct": adv.get("CF_pct", 50), "hdca_g": adv.get("HDCA_G", 0),
                "pk_pct": adv.get("PK%", 80), "rebounds": f.get("L10_Rebounds_G", 0),
                "rush": f.get("L10_Rush_G", 0), "opp_b2b": adv.get("B2B", False),
                "consec_goals": f.get("ConsecGoals", 0)
            })

        for p in asts:
            f, v5, adv = ds.form_data.get(p["Joueur"], {}), ds.v5_data.get(p["Joueur"], {}), ds.matchups.get(p["Adversaire"], {})
            insert_pick("picks_assists", {
                "date": TODAY, "vague": wave_label, "joueur": p["Joueur"], "equipe": p["Equipe"],
                "adversaire": p["Adversaire"], "score": p["Score"], "verdict": p["Categorie"],
                "pp1": bool(p["PP1"]), "backup": p["Backup"], "b2b": p["B2B"], "is_home": p["IsHome"],
                "atoi": f.get("ATOI", 0), "l10_a": f.get("L10_A_G", 0), "season_a": v5.get("A_GP", 0),
                "pdo": v5.get("PDO", 100), "ga_g": adv.get("GA_G", 0),
                "cf_pct": adv.get("CF_pct", 50), "pk_pct": adv.get("PK%", 80),
                "opp_b2b": adv.get("B2B", False)
            })

        for p in pts:
            f, v5, adv = ds.form_data.get(p["Joueur"], {}), ds.v5_data.get(p["Joueur"], {}), ds.matchups.get(p["Adversaire"], {})
            insert_pick("picks_points", {
                "date": TODAY, "vague": wave_label, "joueur": p["Joueur"], "equipe": p["Equipe"],
                "adversaire": p["Adversaire"], "score": p["Score"], "verdict": p["Categorie"],
                "pp1": bool(p["PP1"]), "backup": p["Backup"], "b2b": p["B2B"], "is_home": p["IsHome"],
                "atoi": f.get("ATOI", 0), "l10_pts": f.get("L10_Pts_G", 0), "season_pts": v5.get("Pts_GP", 0),
                "pdo": v5.get("PDO", 100), "ga_g": adv.get("GA_G", 0),
                "cf_pct": adv.get("CF_pct", 50),
                "opp_b2b": adv.get("B2B", False)
            })

        # Unified Player SQL Log
        for p in all_players:
            f, v5, adv = p["p_form"], p["p_v5"], p["adv_stats"]
            insert_player({
                "date": TODAY, "vague": wave_label, "joueur": p["Joueur"], "equipe": p["Equipe"], "adversaire": p["Adversaire"],
                "score_but": p["Score_But"], "score_assist": p["Score_Assist"], "score_point": p["Score_Point"],
                "picked_but": p["Picked_But"], "picked_assist": p["Picked_Assist"], "picked_point": p["Picked_Point"],
                "pp1": "⭐" in f.get("PP1", ""), "backup": p["Backup"], "b2b": p["B2B"], "is_home": p["IsHome"],
                "ixg": f.get("L10_ixG_G", 0), "hdcf": f.get("L10_iHDCF_G", 0), "sog": f.get("L10_SOG_G", 0),
                "atoi": f.get("ATOI", 0), "l10_g": f.get("L10_G_G", 0), "l10_a": f.get("L10_A_G", 0), "l10_pts": f.get("L10_Pts_G", 0),
                "season_g": v5.get("G_GP", 0), "season_a": v5.get("A_GP", 0), "season_pts": v5.get("Pts_GP", 0),
                "pdo": v5.get("PDO", 100), "ga_g": adv.get("GA_G", 0) if adv else 0,
                "cf_pct": adv.get("CF_pct", 50) if adv else 50, "hdca_g": adv.get("HDCA_G", 0) if adv else 0,
                "pk_pct": adv.get("PK%", 80) if adv else 80,
                "consec_goals": f.get("ConsecGoals", 0)
            })

        # CSV Logging (Backward compatibility & Analysis)
        def format_csv(val):
            return str(val).replace('.', ',') if isinstance(val, float) else val

        # Picks CSV
        file_exists = os.path.exists(self.log_path)
        try:
            with open(self.log_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['date', 'vague', 'joueur', 'type', 'score', 'cote', 'but'])
                if not file_exists: writer.writeheader()
                for p in buts:
                    writer.writerow({k: format_csv(v) for k, v in {"date": TODAY, "vague": wave_label, "joueur": p["Joueur"], "type": "BUT", "score": p["Score"], "cote": p.get("Cote", ""), "but": ""}.items()})
                for p in asts:
                    writer.writerow({k: format_csv(v) for k, v in {"date": TODAY, "vague": wave_label, "joueur": p["Joueur"], "type": "ASSIST", "score": p["Score"], "cote": p.get("Cote", ""), "but": ""}.items()})
                for p in pts:
                    writer.writerow({k: format_csv(v) for k, v in {"date": TODAY, "vague": wave_label, "joueur": p["Joueur"], "type": "POINT", "score": p["Score"], "cote": p.get("Cote", ""), "but": ""}.items()})
        except Exception as e:
            logger.error(f"Error writing to picks_log.csv: {e}")

        # Players CSV
        pl_exists = os.path.exists(self.players_log_path)
        try:
            with open(self.players_log_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['date', 'vague', 'joueur', 'score_but', 'score_ast', 'score_pts'])
                if not pl_exists: writer.writeheader()
                for p in all_players:
                    writer.writerow({k: format_csv(v) for k, v in {"date": TODAY, "vague": wave_label, "joueur": p["Joueur"], "score_but": p["Score_But"], "score_ast": p["Score_Assist"], "score_pts": p["Score_Point"]}.items()})
        except Exception as e:
            logger.error(f"Error writing to players_log.csv: {e}")

    def end_of_day_cleanup(self) -> None:
        """Resolves pending picks and cleans up session data."""
        try:
            from core.updater import update_pending_picks
            logger.info("🔄 Auto-résolution des résultats dans la DB avant le rapport final...")
            update_pending_picks()
        except Exception as e:
            logger.error(f"Erreur auto-résolution : {e}")

        if self.matchs_traites:
            from core.services import EmailReporter
            EmailReporter.send_session_report(self.log_path, self.players_log_path)
            self.matchs_traites.clear()
            self.compos_en_memoire.clear()
            self.vagues_envoyees.clear()
            logger.info("Nettoyage de fin de journée terminé.")
