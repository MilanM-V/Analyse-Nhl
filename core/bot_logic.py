import os
import csv
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
import core.odds_scraper as odds_scraper
import asyncio
from core.datastore import DataStore
from core.services import TelegramNotifier
from config.settings import cfg

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
                cflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
                result = subprocess.run(
                    [sys.executable, "fichier.py"], 
                    check=False,  # On gère manuellement le retour
                    capture_output=True,
                    text=True,
                    creationflags=cflags
                )
                
                if result.returncode != 0:
                    logger.error(f"ÉCHEC CRITIQUE fichier.py (Code {result.returncode})")
                    logger.error(f"Traceback du script :\n{result.stderr}")
                    return False

                ok2, ko2 = self._check_csv_integrity()
                if ok2:
                    self.datastore.force_refresh()
                    logger.info("Fichiers API NHL mis à jour avec succès et chargés en RAM.")
                    return True
                else:
                    logger.warning(f"CSV toujours KO après extraction : {', '.join(ko2)}")
                    return False
            except Exception as e:
                logger.warning(f"Exception système lors du lancement de fichier.py : {e}")
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
                for mid in wave:
                    self.matchs_envoyes.add(mid)
            elif self.should_force_send(wave):
                logger.info(f"   Vague {wave_label} forçage < {self.force_envoi_min_avant} min   ENVOI !")
                self.run_analysis_and_send(wave, wave_label + " ⚠️forcé")
                self.vagues_envoyees.add(wave_key)
                for mid in wave:
                    self.matchs_envoyes.add(mid)

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

        matches_soir, compos_brutes, goalies = loaders.parse_flashscore_file(
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

        b2b_teams = [t for t in loaders.get_b2b_teams('./stats/match.csv', TODAY) if t in opponents]
        pp1_players = set(loaders.get_auto_pp1_players(ds.form_data, ds.pp_stats, list(opponents.keys())))
        seen_players = set()

        # Charger les probas dynamiques (V18)
        probas = {"buteurs": 0.35, "passeurs": 0.50, "pointeurs": 0.65}  # Defaults conservateurs
        try:
            import json
            probas_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "probas.json")
            if os.path.exists(probas_path):
                with open(probas_path, "r") as pf:
                    data = json.load(pf)
                for key in probas:
                    if key in data and "proba" in data[key]:
                        probas[key] = data[key]["proba"]
                logger.info(f"Probas dynamiques chargées : B={probas['buteurs']:.3f} A={probas['passeurs']:.3f} P={probas['pointeurs']:.3f}")
            else:
                logger.info("config/probas.json non trouvé, utilisation des probas par défaut.")
        except Exception as e:
            logger.warning(f"Erreur chargement probas.json : {e}")

        final_picks_but = []
        final_picks_ast = []
        final_picks_pts = []
        all_evaluated_players = []

        for player in compos_filtrees:
            if player in seen_players:
                continue
            seen_players.add(player)

            p_form = ds.form_data[player]
            team = loaders.clean_team_name(p_form['Team'])
            if p_form['ATOI'] < cfg.thresholds.general.atoi_min or team not in opponents: continue

            adv = opponents[team]
            adv_stats = ds.matchups.get(adv) or {}
            is_backup = loaders.check_if_backup_goalie(goalies.get(adv, ""), ds.goalie_stats)
            v5_p = ds.v5_data.get(player, {})

            # Extractions de métriques
            season_g = float(v5_p.get('G_GP', 0)) if v5_p else 0.0
            l10_sog = float(p_form.get('L10_SOG_G', 0))
            l10_hdcf = float(p_form.get('L10_iHDCF_G', 0))
            
            # Catégories PASSEURS & POINTEURS
            season_a = float(v5_p.get('A_GP', 0)) if v5_p else 0.0
            season_pts = float(v5_p.get('Pts_GP', 0)) if v5_p else 0.0

            opp_ga = float(adv_stats.get('GA_G', 0)) if adv_stats else 0.0
            l10_a = float(p_form.get('L10_A_G', 0))
            l10_pts = float(p_form.get('L10_Pts_G', 0))
            p_atoi = float(p_form.get('ATOI', 0))
            pos = str(v5_p.get('Position', '')).strip() if v5_p else ""
            is_home = team in home_teams

            # V18 Buteurs — Filtres stats simples (44.7% WR, +43% ROI)
            # QS n'est PLUS un filtre, seulement une métrique de tri
            cat_but = None
            if (is_home or not cfg.thresholds.buteurs.home_only) and \
               pos not in ('D', 'LD', 'RD') and \
               season_g >= cfg.thresholds.buteurs.season_g_min and \
               l10_sog >= cfg.thresholds.buteurs.l10_sog_min and \
               l10_hdcf >= cfg.thresholds.buteurs.l10_hdcf_min and \
               opp_ga >= cfg.thresholds.buteurs.opp_ga_min:
                cat_but = "BUTEUR"
            
            # V18 Passeurs — Filtres optimisés (58.5% WR, +13.6% ROI)
            cat_ast = None
            if (is_home or not cfg.thresholds.passeurs.home_only) and \
               season_a >= cfg.thresholds.passeurs.season_a_min and \
               l10_a >= cfg.thresholds.passeurs.l10_a_min and \
               p_atoi >= cfg.thresholds.passeurs.atoi_min and \
               opp_ga >= cfg.thresholds.passeurs.opp_ga_min:
                cat_ast = "PASSEUR"
            
            # V18 Pointeurs — Filtres optimisés (69.6% WR, +13.8% ROI combo)
            cat_pts = None
            if (is_home or not cfg.thresholds.pointeurs.home_only) and \
               season_pts >= cfg.thresholds.pointeurs.season_pts_min and \
               l10_pts >= cfg.thresholds.pointeurs.l10_pts_min and \
               p_atoi >= cfg.thresholds.pointeurs.atoi_min and \
               opp_ga >= cfg.thresholds.pointeurs.opp_ga_min:
                cat_pts = "POINTEUR"

            # Construction des dicts de picks
            common_data = {
                "Joueur": player, "Equipe": team, "Adversaire": adv, "IsHome": is_home,
                "Pos": pos,
                "PP1": "⭐" if player in pp1_players else "",
                "Backup": is_backup, "B2B": team in b2b_teams and adv not in b2b_teams,
                "Synergie": False
            }

            if cat_but:
                p_but = common_data.copy()
                p_but.update({"Proba": probas["buteurs"], "Categorie": cat_but})
                final_picks_but.append(p_but)
            
            if cat_ast:
                p_ast = common_data.copy()
                p_ast.update({"Proba": probas["passeurs"], "Categorie": cat_ast})
                final_picks_ast.append(p_ast)

            if cat_pts:
                p_pts = common_data.copy()
                p_pts.update({"Proba": probas["pointeurs"], "Categorie": cat_pts})
                final_picks_pts.append(p_pts)

            # Log global
            all_evaluated_players.append({
                "Joueur": player, "Equipe": team, "Adversaire": adv, "IsHome": team in home_teams,
                "Score_But": probas["buteurs"], "Score_Assist": probas["passeurs"], "Score_Point": probas["pointeurs"],
                "Picked_But": bool(cat_but), "Picked_Assist": bool(cat_ast), "Picked_Point": bool(cat_pts),
                "Backup": is_backup, "B2B": team in b2b_teams and adv not in b2b_teams,
                "p_form": p_form, "p_v5": ds.v5_data.get(player, {}), "adv_stats": adv_stats
            })

        # Odds enrichment & +EV Filtering
        players_to_fetch = list({r["Joueur"] for picks_list in (final_picks_but, final_picks_ast, final_picks_pts) for r in picks_list})
        odds_map = {}
        if players_to_fetch:
            logger.info(f"   Récupération asynchrone des cotes BettingPros pour {len(players_to_fetch)} joueur(s)...")
            odds_map = asyncio.run(odds_scraper.fetch_multiple_odds(players_to_fetch))
            
            # Vérification de panne totale du scraper de cotes
            if odds_map:
                # odds_map contient dicts avec 'player', 'BUTS', 'ASSISTS', 'POINTS'
                # On vérifie s'il y a au moins une cote trouvée parmi tous les joueurs testés
                any_odds_found = any(
                    (data.get('BUTS') is not None) or 
                    (data.get('ASSISTS') is not None) or 
                    (data.get('POINTS') is not None)
                    for data in odds_map.values()
                )
                if not any_odds_found:
                    logger.error("ALERTE CRITIQUE : AUCUNE COTE TROUVÉE POUR AUCUN JOUEUR DE LA VAGUE !")
                    self.telegram.send_message(f"🚨 <b>ALERTE CRITIQUE SCRAPER</b> 🚨\nLe scraper de cotes n'a trouvé absolument <b>aucune cote</b> pour l'ensemble des {len(players_to_fetch)} joueurs de la vague {wave_label}.\nBettingPros a probablement bloqué l'accès ou la structure HTML a changé.")
            
            for p in final_picks_but:
                p["Cote"] = odds_map.get(p["Joueur"], {}).get("BUTS")
            for p in final_picks_ast:
                p["Cote"] = odds_map.get(p["Joueur"], {}).get("ASSISTS")
            for p in final_picks_pts:
                p["Cote"] = odds_map.get(p["Joueur"], {}).get("POINTS")
                
        # 🛡️ FILTRE COTE MINIMUM + EV (V18)
        # Reject les paris dont la cote est trop basse pour être rentable
        def is_cote_valid(p: dict, cote_min: float) -> bool:
            """Vérifie que la cote existe et dépasse le minimum du marché."""
            if not p.get("Cote") or p["Cote"] <= 1.05:
                logger.debug(f"Pari Rejeté (Absence de Cote) : {p['Joueur']}")
                return False
            if cote_min > 0 and p["Cote"] < cote_min:
                logger.debug(f"Pari Rejeté (Cote {p['Cote']:.2f} < min {cote_min:.2f}) : {p['Joueur']}")
                return False
            ev = (p["Proba"] * p["Cote"]) - 1.0
            if ev < 0.02:
                logger.debug(f"Pari Rejeté (-EV) : {p['Joueur']} (EV: {ev*100:.1f}%)")
                return False
            return True

        final_picks_but = [p for p in final_picks_but if is_cote_valid(p, cfg.thresholds.buteurs.cote_min)]
        final_picks_ast = [p for p in final_picks_ast if is_cote_valid(p, cfg.thresholds.passeurs.cote_min)]
        # Points : pas de filtre cote_min (rentable en combiné)
        final_picks_pts = [p for p in final_picks_pts if is_cote_valid(p, cfg.thresholds.pointeurs.cote_min)]

        # Calculer la mise (Kelly) pour chaque pick AVANT envoi Telegram et DB
        for picks_list in [final_picks_but, final_picks_ast, final_picks_pts]:
            for p in picks_list:
                mise_str = self._calculate_quarter_kelly(
                    p.get('Proba', 0),
                    p.get('Cote'), p.get('Categorie', '')
                )
                p["Mise"] = mise_str
                # Extraire la valeur numérique pour la DB (ex: "1.5 U" -> 1.5)
                try:
                    p["MiseNum"] = float(mise_str.replace(" U", ""))
                except (ValueError, AttributeError):
                    p["MiseNum"] = 1.0

        # Telegram Recap (Multi-marchés)
        self._send_telegram_v18(final_picks_but, final_picks_ast, final_picks_pts, wave_label, wave_ids)
        
        # Logging unifié
        self._log_v18(final_picks_but, final_picks_ast, final_picks_pts, all_evaluated_players, wave_label, ds)

    # Plafonds de mise par catégorie (depuis config/settings.toml)
    CATEGORY_CAPS = {
        "BUTEUR": cfg.kelly.buteur_cap,
        "PASSEUR": cfg.kelly.passeur_cap,
        "POINTEUR": cfg.kelly.pointeur_cap,
    }

    def _calculate_quarter_kelly(self, proba: float, cote: float, categorie: str = "") -> str:
        """Calcule la recommandation de mise fractionnée Quarter Kelly.
        
        Args:
            proba: Probabilité IA calculée.
            cote: Cote du bookmaker.
            categorie: Catégorie du pick (BUTEUR, PASSEUR, POINTEUR).
        """
        if not cote or cote <= 1.05:
            return "1 U"
        
        b = cote - 1.0
        p = proba
        
        # Pénalité IA pour les défenseurs : leur taux de conversion réel
        # est bien inférieur à ce que l'XGBoost prédit (tirs lointains)
        if categorie == "DÉFENSEUR":
            p = p * 0.6
            
        q = 1.0 - p
        f = (p * b - q) / b
        
        # Plafond dynamique selon la catégorie
        cap = self.CATEGORY_CAPS.get(categorie, 2.0)
        
        if f > 0:
            quarter_f = f / 4.0
            units = round(quarter_f * 100 * 2) / 2  # arrondi à 0.5 près
            units = max(0.5, min(units, cap))
            return f"{units} U"
            
        return "0 U"  # Mathématiquement perdant. (Puisque filtré en amont, on ne devrait jamais l'atteindre)

    def _send_telegram_v18(self, buts: List[Dict[str, Any]], assists: List[Dict[str, Any]], points: List[Dict[str, Any]], wave_label: str, wave_ids: List[str]) -> None:
        """Formats and sends the V18.3 Telegram recap with pre-calculated mise and smart parlays."""
            
        msg = f"<b>\U0001f3d2 NHL V18.3 \u2014 VAGUE {wave_label}</b>\n\n"
        
        for mid in wave_ids:
            data = self.compos_en_memoire.get(mid)
            if not data: continue
            
            m = data["match_info"]
            t1_full = loaders.REVERSE_TEAM_MAPPING.get(m['home'], m['home'])
            t2_full = loaders.REVERSE_TEAM_MAPPING.get(m['away'], m['away'])
            
            h_abbr = loaders.TEAM_MAPPING.get(m['home'], m['home'])
            a_abbr = loaders.TEAM_MAPPING.get(m['away'], m['away'])
            
            msg += f"<b>Match {t1_full} vs {t2_full} :</b>\n"
            
            for emoji, label, picks_list in [
                ("\U0001f525", "Buteurs", buts), ("\U0001f170\ufe0f", "Passeurs", assists),
                ("\U0001f3c6", "Pointeurs", points)
            ]:
                m_picks = [r for r in picks_list if r['Equipe'] in (h_abbr, a_abbr)]
                # On trie maintenant par Valeur Attendue (EV) : (Proba * Cote - 1)
                m_picks.sort(key=lambda x: (x.get('Proba', 0) * (x.get('Cote') or 0)) - 1.0, reverse=True)
                if m_picks:
                    msg += f"  {emoji} <i>{label} :</i>\n"
                    for r in m_picks:
                        home_icon = '\U0001f3e0' if r['IsHome'] else '\u2708\ufe0f'
                        cote_str = f" @{r['Cote']} | Edge: {((r.get('Proba', 0) * (r.get('Cote', 1) or 1)) - 1)*100:.1f}% | Mise: {r.get('Mise', '1 U')}" if r.get('Cote') else ""
                        msg += f"  \u2022 {home_icon} <b>{r['Joueur']}</b>{cote_str}\n"

            m_all = [r for picks_list in [buts, assists, points]
                     for r in picks_list if r['Equipe'] in (h_abbr, a_abbr)]
            if not m_all:
                msg += "  <i>\u26a0\ufe0f Aucun pick sur ce match.</i>\n"
            msg += "\n"

        # --- COMBINÉS INTELLIGENTS (V18.3) ---
        def get_best_per_match(picks_list):
            best = {}
            for p in picks_list:
                if p.get('Cote') and p['Cote'] > 1.05:
                    m_key = f"{p['Equipe']}-{p.get('Adversaire', '')}"
                    if m_key not in best or (p.get('Proba', 0) * p['Cote']) > (best[m_key].get('Proba', 0) * best[m_key].get('Cote', 1)):
                        best[m_key] = p
            return list(best.values())

        best_pts = get_best_per_match(points)
        best_ast = get_best_per_match(assists)
        best_but = get_best_per_match(buts)
        
        # Sort by EV décroissante
        best_pts.sort(key=lambda x: -((x.get('Proba', 0) * x.get('Cote', 1)) - 1.0))
        best_ast.sort(key=lambda x: -((x.get('Proba', 0) * x.get('Cote', 1)) - 1.0))
        best_but.sort(key=lambda x: -((x.get('Proba', 0) * x.get('Cote', 1)) - 1.0))

        from core.database import insert_parlay
        from datetime import datetime
        today_str = datetime.now().strftime("%Y-%m-%d")

        def find_cross_duo(list1, list2):
            for p1 in list1:
                g1 = set([p1['Equipe'], p1.get('Adversaire', '')])
                for p2 in list2:
                    if p1['Joueur'] == p2['Joueur']: continue # Pas le même joueur
                    g2 = set([p2['Equipe'], p2.get('Adversaire', '')])
                    if not g1.intersection(g2): # Pas de même match
                        return (p1, p2)
            return None

        # Double Points & Triple Points
        if len(best_pts) >= 2:
            l1, l2 = best_pts[0], best_pts[1]
            c2 = round(l1['Cote'] * l2['Cote'], 2)
            msg += "<b>\U0001f3af DOUBLE POINTS :</b>\n"
            msg += f"  \u2022 {l1['Joueur']} @{l1['Cote']}\n"
            msg += f"  \u2022 {l2['Joueur']} @{l2['Cote']}\n"
            msg += f"  => <b>Cote Combo : @{c2}</b> | Mise: 0.5 U\n\n"
            insert_parlay({"date": today_str, "vague": wave_label, "type_combo": "DOUBLE_POINTS",
                           "leg1_joueur": l1['Joueur'], "leg2_joueur": l2['Joueur'], "leg3_joueur": None,
                           "cote_totale": c2, "mise": 0.5})
            
            if len(best_pts) >= 3:
                l3 = best_pts[2]
                c3 = round(l1['Cote'] * l2['Cote'] * l3['Cote'], 2)
                msg += "<b>\U0001f680 TRIPLE POINTS :</b>\n"
                msg += f"  \u2022 {l1['Joueur']} @{l1['Cote']}\n"
                msg += f"  \u2022 {l2['Joueur']} @{l2['Cote']}\n"
                msg += f"  \u2022 {l3['Joueur']} @{l3['Cote']}\n"
                msg += f"  => <b>Cote Combo : @{c3}</b> | Mise: 0.3 U\n\n"
                insert_parlay({"date": today_str, "vague": wave_label, "type_combo": "TRIPLE_POINTS",
                               "leg1_joueur": l1['Joueur'], "leg2_joueur": l2['Joueur'], "leg3_joueur": l3['Joueur'],
                               "cote_totale": c3, "mise": 0.3})

        # Duo Booster (Ast + Pts)
        booster = find_cross_duo(best_ast, best_pts)
        if booster:
            c2 = round(booster[0]['Cote'] * booster[1]['Cote'], 2)
            msg += "<b>\U0001f525 DUO BOOSTER (Passeur + Pointeur) :</b>\n"
            msg += f"  \u2022 {booster[0]['Joueur']} (Passes) @{booster[0]['Cote']}\n"
            msg += f"  \u2022 {booster[1]['Joueur']} (Points) @{booster[1]['Cote']}\n"
            msg += f"  => <b>Cote Combo : @{c2}</b> | Mise: 0.5 U\n\n"
            insert_parlay({"date": today_str, "vague": wave_label, "type_combo": "PASSEUR_POINTEUR",
                           "leg1_joueur": booster[0]['Joueur'], "leg2_joueur": booster[1]['Joueur'], "leg3_joueur": None,
                           "cote_totale": c2, "mise": 0.5})

        # Duo Offensif (But + Pts)
        offensif = find_cross_duo(best_but, best_pts)
        if offensif:
            c2 = round(offensif[0]['Cote'] * offensif[1]['Cote'], 2)
            msg += "<b>\U0001f4a3 DUO OFFENSIF (Buteur + Pointeur) :</b>\n"
            msg += f"  \u2022 {offensif[0]['Joueur']} (Buteur) @{offensif[0]['Cote']}\n"
            msg += f"  \u2022 {offensif[1]['Joueur']} (Points) @{offensif[1]['Cote']}\n"
            msg += f"  => <b>Cote Combo : @{c2}</b> | Mise: 0.5 U\n\n"
            insert_parlay({"date": today_str, "vague": wave_label, "type_combo": "BUTEUR_POINTEUR",
                           "leg1_joueur": offensif[0]['Joueur'], "leg2_joueur": offensif[1]['Joueur'], "leg3_joueur": None,
                           "cote_totale": c2, "mise": 0.5})

        # Double Buteur (But + But)
        dbut = find_cross_duo(best_but, best_but)
        if dbut:
            c2 = round(dbut[0]['Cote'] * dbut[1]['Cote'], 2)
            msg += "<b>\u2694\ufe0f DOUBLE BUTEUR :</b>\n"
            msg += f"  \u2022 {dbut[0]['Joueur']} @{dbut[0]['Cote']}\n"
            msg += f"  \u2022 {dbut[1]['Joueur']} @{dbut[1]['Cote']}\n"
            msg += f"  => <b>Cote Combo : @{c2}</b> | Mise: 0.3 U\n\n"
            insert_parlay({"date": today_str, "vague": wave_label, "type_combo": "DOUBLE_BUTEUR",
                           "leg1_joueur": dbut[0]['Joueur'], "leg2_joueur": dbut[1]['Joueur'], "leg3_joueur": None,
                           "cote_totale": c2, "mise": 0.3})

        self.telegram.send_message(msg)


    def _log_v18(self, buts, asts, pts, all_players, wave_label, ds):
        """Logs everything to SQL tables and CSV files (V18 with mise)."""
        from core.database import insert_pick, insert_player
        import csv
        TODAY = self.get_nhl_session_date()

        # SQL Logging
        for p in buts:
            f, v5, adv = ds.form_data.get(p["Joueur"], {}), ds.v5_data.get(p["Joueur"], {}), ds.matchups.get(p["Adversaire"], {})
            insert_pick("picks", {
                "date": TODAY, "vague": wave_label, "joueur": p["Joueur"], "equipe": p["Equipe"],
                "adversaire": p["Adversaire"], "score": p.get("Proba", 0), "verdict": p["Categorie"],
                "pp1": bool(p["PP1"]), "backup": p["Backup"], "b2b": p["B2B"], "is_home": p["IsHome"],
                "ixg": f.get("L10_ixG_G", 0), "hdcf": f.get("L10_iHDCF_G", 0), "sog": f.get("L10_SOG_G", 0),
                "atoi": f.get("ATOI", 0), "l10_g": f.get("L10_G_G", 0), "season_g": v5.get("G_GP", 0),
                "pdo": v5.get("PDO", 100), "ga_g": adv.get("GA_G", 0),
                "cf_pct": adv.get("CF_pct", 50), "hdca_g": adv.get("HDCA_G", 0),
                "pk_pct": adv.get("PK%", 80), "rebounds": f.get("L10_Rebounds_G", 0),
                "rush": f.get("L10_Rush_G", 0), "opp_b2b": adv.get("B2B", False),
                "consec_goals": f.get("ConsecGoals", 0), "cote": p.get("Cote"),
                "mise": p.get("MiseNum")
            })

        for p in asts:
            f, v5, adv = ds.form_data.get(p["Joueur"], {}), ds.v5_data.get(p["Joueur"], {}), ds.matchups.get(p["Adversaire"], {})
            insert_pick("picks_assists", {
                "date": TODAY, "vague": wave_label, "joueur": p["Joueur"], "equipe": p["Equipe"],
                "adversaire": p["Adversaire"], "score": p.get("Proba", 0), "verdict": p["Categorie"],
                "pp1": bool(p["PP1"]), "backup": p["Backup"], "b2b": p["B2B"], "is_home": p["IsHome"],
                "atoi": f.get("ATOI", 0), "l10_a": f.get("L10_A_G", 0), "season_a": v5.get("A_GP", 0),
                "pdo": v5.get("PDO", 100), "ga_g": adv.get("GA_G", 0),
                "cf_pct": adv.get("CF_pct", 50), "pk_pct": adv.get("PK%", 80),
                "opp_b2b": adv.get("B2B", False), "cote": p.get("Cote"),
                "mise": p.get("MiseNum")
            })

        for p in pts:
            f, v5, adv = ds.form_data.get(p["Joueur"], {}), ds.v5_data.get(p["Joueur"], {}), ds.matchups.get(p["Adversaire"], {})
            insert_pick("picks_points", {
                "date": TODAY, "vague": wave_label, "joueur": p["Joueur"], "equipe": p["Equipe"],
                "adversaire": p["Adversaire"], "score": p.get("Proba", 0), "verdict": p["Categorie"],
                "pp1": bool(p["PP1"]), "backup": p["Backup"], "b2b": p["B2B"], "is_home": p["IsHome"],
                "atoi": f.get("ATOI", 0), "l10_pts": f.get("L10_Pts_G", 0), "season_pts": v5.get("Pts_GP", 0),
                "pdo": v5.get("PDO", 100), "ga_g": adv.get("GA_G", 0),
                "cf_pct": adv.get("CF_pct", 50),
                "opp_b2b": adv.get("B2B", False), "cote": p.get("Cote"),
                "mise": p.get("MiseNum")
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
            return str(val).replace('.', cfg.csv.decimal_separator) if isinstance(val, float) else val

        # Picks CSV
        file_exists = os.path.exists(self.log_path)
        try:
            with open(self.log_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['date', 'vague', 'joueur', 'type', 'score', 'cote', 'but'])
                if not file_exists: writer.writeheader()
                for p in buts:
                    writer.writerow({k: format_csv(v) for k, v in {"date": TODAY, "vague": wave_label, "joueur": p["Joueur"], "type": "BUT", "score": p.get("Proba", 0), "cote": p.get("Cote", ""), "but": ""}.items()})
                for p in asts:
                    writer.writerow({k: format_csv(v) for k, v in {"date": TODAY, "vague": wave_label, "joueur": p["Joueur"], "type": "ASSIST", "score": p.get("Proba", 0), "cote": p.get("Cote", ""), "but": ""}.items()})
                for p in pts:
                    writer.writerow({k: format_csv(v) for k, v in {"date": TODAY, "vague": wave_label, "joueur": p["Joueur"], "type": "POINT", "score": p.get("Proba", 0), "cote": p.get("Cote", ""), "but": ""}.items()})
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
            self.matchs_envoyes.clear()
            logger.info("Nettoyage de fin de journée terminé.")
