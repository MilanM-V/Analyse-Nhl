import os
import csv
import logging
from datetime import datetime, timedelta
import subprocess
import sys

import core.scraper as scraper
import core.predictor_v12 as predictor_v11  # On garde l'alias pour limiter les modifs internes
from core.odds_api import enrich_picks_with_odds, get_api_usage

logger = logging.getLogger("NHL_Bot")

class NhlBot:
    def __init__(self, datastore, telegram_notifier):
        self.datastore = datastore
        self.telegram = telegram_notifier

        self.matchs_traites = set()
        self.compos_en_memoire = {}
        self.vagues_envoyees = set()
        self._is_scanning = False

        self.ecart_max_vague_min = 5
        self.force_envoi_min_avant = 17
        self.log_path = './stats/picks_log.csv'
        self.players_log_path = './stats/players_log.csv'
        self.fichier_compos_temp = "compos_live.txt"

    def is_active_hours(self):
        now = datetime.now()
        hour = now.hour
        return (hour > 16 or (hour == 16 and datetime.now().minute >= 30)) or hour <= 4

    def update_daily_stats(self):
        """Force l'update des fichiers CSV si pas fait aujourd'hui."""
        now = datetime.now()
        nhl_date = (now - timedelta(hours=12)).strftime("%Y-%m-%d")

        ok, ko_files = self._check_csv_integrity()

        if self.datastore.last_load_date != nhl_date or not ok:
            if not ok and self.datastore.last_load_date == nhl_date:
                logger.warning(f"[{now.strftime('%H:%M:%S')}] CSV KO : {', '.join(ko_files)} — Re-extraction forcée...")
            else:
                logger.info(f"\n[{now.strftime('%H:%M:%S')}] MISE À JOUR API NHL EN COURS...")

            try:
                subprocess.run([sys.executable, "fichier.py"], check=True)
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

    def _check_csv_integrity(self):
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

    def parse_match_datetime(self, time_str):
        now = datetime.now()
        try:
            dt = datetime.strptime(f"{time_str} {now.year}", "%d.%m. %H:%M %Y")
            if dt < now - timedelta(hours=12):
                dt += timedelta(days=1)
            return dt
        except:
            return None

    def purge_old_matches(self):
        now = datetime.now()
        a_supprimer = []
        for match_id, data in self.compos_en_memoire.items():
            dt = self.parse_match_datetime(data["match_info"]["time"])
            if dt and now > dt + timedelta(minutes=5):
                a_supprimer.append(match_id)
        for m_id in a_supprimer:
            del self.compos_en_memoire[m_id]
            logger.info(f"   Match {m_id} purgé de la mémoire.")

    def build_waves(self, match_ids):
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

    def is_wave_complete(self, wave_ids, all_matches):
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

    def should_force_send(self, wave_ids):
        first_dt = self.parse_match_datetime(self.compos_en_memoire[wave_ids[0]]["match_info"]["time"])
        if not first_dt: return False
        mins_before = (first_dt - datetime.now()).total_seconds() / 60
        return mins_before <= self.force_envoi_min_avant

    def run_scan_cycle(self):
        """Fonction principale de scan appelée par le scheduler toutes les 15 minutes."""
        if self._is_scanning:
            logger.warning("Un scan est déjà en cours. Ignoré pour éviter les lancements multiples.")
            return

        if not self.is_active_hours():
            logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Hors horaires (05h-17h). En veille...")
            return

        self._is_scanning = True
        try:

            if not self.update_daily_stats():
                logger.warning("Analyse suspendue — CSV invalides.")
                return

            logger.info(f"\n[{datetime.now().strftime('%H:%M:%S')}] Lancement du scan Flashscore...")
            self.purge_old_matches()

            with scraper.ScraperDriverContext() as driver:
                matches_du_jour = scraper.get_scheduled_matches("https://www.flashscore.fr/hockey/usa/nhl/calendrier/", driver=driver)

                for m in matches_du_jour:
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

            self.evaluate_waves(matches_du_jour)
        except Exception as e:
            logger.error(f"ERREUR CRITIQUE lors du run_scan_cycle : {e}")
        finally:
            self._is_scanning = False

    def evaluate_waves(self, matches_du_jour):
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

    def run_analysis_and_send(self, wave_ids, wave_label):
        """Réalise l'analyse algorithmique en se basant sur self.datastore au lieu de relire le disque."""
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

        matches_soir, compos_brutes, goalies = predictor_v11.parse_flashscore_file(
            self.fichier_compos_temp, ds.known_players, ds.form_data
        )

        compos_filtrees = [p for p in compos_brutes if p in ds.form_data]
        home_teams = [m[0] for m in matches_soir]
        opponents = {t1: t2 for t1, t2 in matches_soir}
        opponents.update({t2: t1 for t1, t2 in matches_soir})

        b2b_teams = [t for t in predictor_v11.get_b2b_teams('./stats/match.csv', TODAY) if t in opponents]
        pp1_players = predictor_v11.get_auto_pp1_players(ds.form_data, ds.pp_stats, opponents.keys())

        results = []
        for player in compos_filtrees:
            p_form = ds.form_data[player]
            team = predictor_v11.clean_team_name(p_form['Team'])
            if p_form['ATOI'] < 13.0 or team not in opponents: continue

            adv = opponents[team]
            adv_stats = ds.matchups.get(adv)
            is_backup = predictor_v11.check_if_backup_goalie(goalies.get(adv, ""), ds.goalie_stats)

            qs = predictor_v11.calculate_base_qs(
                ds.v5_data.get(player, {}), p_form, adv_stats,
                player in pp1_players, team in home_teams,
                False, is_backup, team in b2b_teams and adv not in b2b_teams
            )

            if qs >= 0:
                results.append({
                    "Joueur": player, "Equipe": team, "Adversaire": adv, "IsHome": team in home_teams,
                    "Score": round(qs, 1), "hdcf": round(p_form.get('L10_iHDCF_G', 0), 2),
                    "Categorie": self._get_categorie(qs, round(p_form.get('L10_iHDCF_G', 0), 2)),
                    "ixg": p_form.get('L10_ixG_G', 0), "sog": p_form.get('L10_SOG_G', 0), "PP1": "⭐" if player in pp1_players else "",
                    "Backup": is_backup,
                    "B2B": team in b2b_teams and adv not in b2b_teams,
                })

        final_picks = [r for r in sorted(results, key=lambda x: x["Score"], reverse=True) if r["Categorie"]]

        if not final_picks:
            logger.info("Aucun joueur n'a passé les filtres.")
            return

        # Enrichir les picks avec les cotes réelles (si API disponible)
        for match_key in {(r['Equipe'] if r['IsHome'] else r['Adversaire'], r['Adversaire'] if r['IsHome'] else r['Equipe']) for r in final_picks}:
            home_full = predictor_v11.REVERSE_TEAM_MAPPING.get(match_key[0], match_key[0])
            away_full = predictor_v11.REVERSE_TEAM_MAPPING.get(match_key[1], match_key[1])
            enrich_picks_with_odds(final_picks, home_full, away_full)

        self._send_telegram_recap(final_picks, wave_label)
        self._log_picks_and_players(final_picks, compos_brutes, wave_label, ds, opponents)

    def _get_categorie(self, score, hdcf):
        """Seuils calibrés sur 20 000 matchs (backtest V3)."""
        if score >= 11.5: return "ELITE"   # 41.6% WR validé
        if score >= 10.5: return "SAFE"    # 35.1% WR validé
        return None

    def _send_telegram_recap(self, picks, wave_label):
        msg = f"<b>🏒 NHL V12.9 CALIBRÉ - VAGUE {wave_label}</b>\n\n"
        picks_by_match = {}
        cat_emoji = {"ELITE": "🚀 ", "SAFE": "✅ "}
        for r in picks:
            if r['IsHome']:
                match_str = f"{r['Equipe']} vs {r['Adversaire']}"
            else:
                match_str = f"{r['Adversaire']} vs {r['Equipe']}"

            picks_by_match.setdefault(match_str, []).append(r)

        for match, lst in picks_by_match.items():
            msg += f"<b>Match {match} :</b>\n"
            for r in lst:
                icon = cat_emoji.get(r['Categorie'], "✅")
                side = "🏠" if r['IsHome'] else "✈️"
                msg += f"  • {side} <b>{r['Joueur']}</b> {icon} {r['Categorie']} ({float(r['Score']):.1f}/{float(r['hdcf']):.2f})"

                # Affichage des cotes et Value Bet si disponibles
                if r.get('Cote') is not None:
                    if r.get('ValueBet'):
                        msg += f" | 💰 @{r['Cote']} VALUE ({r['Kelly']:.1f}%)"
                    else:
                        msg += f" | @{r['Cote']} ❌"
                msg += "\n"
            msg += "\n"

        # Ajout du compteur API en bas du message
        try:
            usage = get_api_usage()
            msg += f"<i>📊 API Cotes : {usage}</i>\n"
        except Exception:
            pass

        self.telegram.send_message(msg)

    def _log_picks_and_players(self, picks, compos_brutes, wave_label, ds, opponents):
        from core.database import insert_pick, insert_player

        def format_row_for_european_csv(row_dict):
            formatted_row = {}
            for key, value in row_dict.items():
                if isinstance(value, float):
                    formatted_row[key] = str(value).replace('.', ',')
                else:
                    formatted_row[key] = value
            return formatted_row

        TODAY_DATE = datetime.now().strftime("%Y-%m-%d")

        file_exists = os.path.exists(self.log_path)
        try:
            with open(self.log_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=[
                    'date', 'vague', 'joueur', 'equipe', 'adversaire',
                    'score', 'verdict', 'pp1', 'backup', 'b2b',
                    'ixg', 'hdcf', 'sog', 'atoi', 'l10_g', 'season_g',
                    'pdo', 'ga_g', 'cf_pct', 'hdca_g', 'pk_pct',
                    'rebounds', 'rush', 'but'
                ])
                if not file_exists:
                    writer.writeheader()
                seen_picks = set()  
                for r in picks:
                    pick_key = (r['Joueur'], r['Equipe'])
                    if pick_key in seen_picks:
                        continue
                    seen_picks.add(pick_key)

                    p_form = ds.form_data.get(r['Joueur'], {})
                    p_v5 = ds.v5_data.get(r['Joueur'], {})
                    adv_stats = ds.matchups.get(r['Adversaire'], {})

                    row_data = {
                        'date':       TODAY_DATE,
                        'vague':      wave_label,
                        'joueur':     r['Joueur'],
                        'equipe':     r['Equipe'],
                        'adversaire': r['Adversaire'],
                        'score':      r['Score'],
                        'verdict':    r['Categorie'],
                        'pp1':        '⭐' in r.get('PP1', ''),
                        'backup':     r.get('Backup', False),
                        'b2b':        r.get('B2B', False),
                        'ixg':        r.get('ixg', 0),
                        'hdcf':       r.get('hdcf', 0),
                        'sog':        r.get('sog', 0),
                        'atoi':       round(p_form.get('ATOI', 0.0), 1),
                        'l10_g':      round(p_form.get('L10_G_G', 0.0), 3),
                        'season_g':   round(p_v5.get('G_GP', 0.0), 3),
                        'pdo':        round(p_v5.get('PDO', 100.0), 1),
                        'ga_g':       round(adv_stats.get('GA_G', 0.0), 2),
                        'cf_pct':     round(adv_stats.get('CF_pct', 50.0), 1),
                        'hdca_g':     round(adv_stats.get('HDCA_G', 0.0), 2),
                        'pk_pct':     round(adv_stats.get('PK%', 80.0), 1),
                        'rebounds':   round(p_form.get('L10_Rebounds_G', 0.0), 2),
                        'rush':       round(p_form.get('L10_Rush_G', 0.0), 2),
                        'but':        None
                    }

                    try:
                        insert_pick(row_data)
                    except Exception as err:
                        logger.error(f"SQL Insert Pick failed: {err}")

                    row_data['but'] = ''                                         
                    writer.writerow(format_row_for_european_csv(row_data))
        except Exception as e:
            logger.error(f"[WARN] Erreur écriture picks_log.csv : {e}")

        picked_names = {r['Joueur'] for r in picks}
        results_index = {r['Joueur']: r for r in picks}                                                                           

        pl_exists = os.path.exists(self.players_log_path)
        try:
            with open(self.players_log_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=[
                    'date', 'vague', 'joueur', 'equipe', 'adversaire',
                    'score', 'picked', 'pp1', 'backup', 'b2b',
                    'ixg', 'hdcf', 'sog', 'atoi', 'l10_g', 'season_g',
                    'pdo', 'ga_g', 'cf_pct', 'hdca_g', 'pk_pct',
                    'rebounds', 'rush', 'but'
                ])
                if not pl_exists:
                    writer.writeheader()
                seen_players = set()
                n_logged = 0
                pp1_set = set(predictor_v11.get_auto_pp1_players(ds.form_data, ds.pp_stats, opponents.keys()))
                for player in compos_brutes:
                    if player in seen_players:
                        continue
                    seen_players.add(player)

                    p_form = ds.form_data.get(player, {})
                    p_v5 = ds.v5_data.get(player, {})
                    team = predictor_v11.clean_team_name(p_form.get('Team', '')) if p_form else ''
                    adv = opponents.get(team, '')
                    adv_stats = ds.matchups.get(adv, {})

                    r = results_index.get(player, {})

                    row_data = {
                        'date':       TODAY_DATE,
                        'vague':      wave_label,
                        'joueur':     player,
                        'equipe':     team,
                        'adversaire': adv,
                        'score':      r.get('Score', 0.0) if isinstance(r.get('Score'), (int, float)) else 0.0,
                        'picked':     player in picked_names,
                        'pp1':        player in pp1_set,
                        'backup':     False,                  
                        'b2b':        False,                  
                        'ixg':        round(p_form.get('L10_ixG_G', 0.0), 3),
                        'hdcf':       round(p_form.get('L10_iHDCF_G', 0.0), 2),
                        'sog':        round(p_form.get('L10_SOG_G', 0.0), 2),
                        'atoi':       round(p_form.get('ATOI', 0.0), 1),
                        'l10_g':      round(p_form.get('L10_G_G', 0.0), 3),
                        'season_g':   round(p_v5.get('G_GP', 0.0), 3) if p_v5 else 0.0,
                        'pdo':        round(p_v5.get('PDO', 100.0), 1) if p_v5 else 0.0,
                        'ga_g':       round(adv_stats.get('GA_G', 0.0), 2) if adv_stats else 0.0,
                        'cf_pct':     round(adv_stats.get('CF_pct', 50.0), 1) if adv_stats else 0.0,
                        'hdca_g':     round(adv_stats.get('HDCA_G', 0.0), 2) if adv_stats else 0.0,
                        'pk_pct':     round(adv_stats.get('PK%', 80.0), 1) if adv_stats else 0.0,
                        'rebounds':   round(p_form.get('L10_Rebounds_G', 0.0), 2),
                        'rush':       round(p_form.get('L10_Rush_G', 0.0), 2),
                        'but':        None
                    }

                    try:
                        insert_player(row_data)
                    except Exception as err:
                        logger.error(f"SQL Insert Player failed: {err}")

                    row_data['score'] = r.get('Score', '')
                    row_data['season_g'] = round(p_v5.get('G_GP', 0.0), 3) if p_v5 else ''
                    row_data['pdo'] = round(p_v5.get('PDO', 100.0), 1) if p_v5 else ''
                    row_data['ga_g'] = round(adv_stats.get('GA_G', 0.0), 2) if adv_stats else ''
                    row_data['cf_pct'] = round(adv_stats.get('CF_pct', 50.0), 1) if adv_stats else ''
                    row_data['hdca_g'] = round(adv_stats.get('HDCA_G', 0.0), 2) if adv_stats else ''
                    row_data['pk_pct'] = round(adv_stats.get('PK%', 80.0), 1) if adv_stats else ''
                    row_data['but'] = ''

                    writer.writerow(format_row_for_european_csv(row_data))
                    n_logged += 1
            logger.info(f"[OK] players_log.csv : {n_logged} joueurs loggués ({len(picked_names)} picks)")
        except Exception as e:
            logger.error(f"[WARN] Erreur écriture players_log.csv : {e}")

    def end_of_day_cleanup(self):
        if self.matchs_traites:
            from core.services import EmailReporter
            EmailReporter.send_session_report(self.log_path, self.players_log_path)
            self.matchs_traites.clear()
            self.compos_en_memoire.clear()
            self.vagues_envoyees.clear()
            logger.info("Nettoyage de fin de journée terminé.")
