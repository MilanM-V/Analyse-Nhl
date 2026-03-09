"""
NHL BETTING BOT V10 - Serveur Autonome par "Vagues Horaires"
- Met à jour NST automatiquement (1x/jour)
- Garde en mémoire TOUTES les compos des matchs qui n'ont pas encore commencé
- Envoie UN message Telegram PAR VAGUE (matchs espacés de moins de 15 min = même vague)
- Force l'envoi 5 min avant le 1er match si des compos manquent encore
"""
import time
from datetime import datetime, timedelta
import os
import sys
import subprocess
import requests

import scraper
import predictor_v8
import logging
from logging.handlers import RotatingFileHandler

# Configuration du logging
logger = logging.getLogger("NHL_Bot")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = RotatingFileHandler('bot.log', maxBytes=5*1024*1024, backupCount=5)
file_handler.setFormatter(formatter)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

# ==========================================
# CONFIGURATION TELEGRAM
# ==========================================
import os
from dotenv import load_dotenv

# Charge les variables du fichier .env
load_dotenv()

# Récupère les variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BRAVE_PATH = os.getenv("BRAVE_PATH")

def send_telegram_message(message):
    if TELEGRAM_BOT_TOKEN == "TELEGRAM_BOT_TOKEN" or not TELEGRAM_BOT_TOKEN:
        logger.info("Message non envoyé : Identifiants Telegram manquants.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            logger.info(f"Erreur d'envoi Telegram : {response.text}")
        else:
            logger.info("Alerte Telegram envoyée avec succès !")
    except Exception as e:
        logger.info(f"Exception lors de l'envoi Telegram : {e}")

# ==========================================
# MÉMOIRE GLOBALE
# ==========================================
MATCHS_TRAITES = set()       # IDs déjà scrappés (compo trouvée ou pas)
COMPOS_EN_MEMOIRE = {}       # { match_id: {"match_info": {...}, "compo": {...}} }
VAGUES_ENVOYEES = set()      # Clés de vagues déjà envoyées sur Telegram
FICHIER_COMPOS_TEMPORAIRE = "compos_live.txt"
LAST_STATS_UPDATE = None

# ==========================================
# LOGIQUE DE VAGUES PAR CLUSTERING (15 MIN)
# ==========================================

ECART_MAX_VAGUE_MIN = 15      # 2 matchs espacés de moins de 15 min = même vague
FORCE_ENVOI_MIN_AVANT = 5     # On force l'envoi 5 min avant le 1er match de la vague

def parse_match_datetime(time_str):
    """
    Convertit "07.03. 01:00" en objet datetime (année courante).
    Gère le passage minuit (ex: match à 01:00 le lendemain).
    """
    now = datetime.now()
    try:
        dt = datetime.strptime(f"{time_str} {now.year}", "%d.%m. %H:%M %Y")
        # Si le match semble dans le passé lointain (>12h), c'est qu'il est le lendemain
        if dt < now - timedelta(hours=12):
            dt += timedelta(days=1)
        return dt
    except:
        return None

def build_waves(match_ids_in_memory):
    """
    Regroupe les match_ids par vague :
    - On trie par heure de match
    - Si l'écart entre deux matchs consécutifs est < 15 min   même vague
    - Sinon   nouvelle vague
    
    Retourne une liste de listes : [ [id1, id2], [id3], [id4, id5, id6] ]
    Chaque sous-liste = une vague.
    """
    if not match_ids_in_memory:
        return []

    # Trier les matchs par heure
    sorted_matches = sorted(
        match_ids_in_memory,
        key=lambda mid: parse_match_datetime(COMPOS_EN_MEMOIRE[mid]["match_info"]["time"]) or datetime.max
    )

    waves = []
    current_wave = [sorted_matches[0]]

    for i in range(1, len(sorted_matches)):
        prev_dt = parse_match_datetime(COMPOS_EN_MEMOIRE[sorted_matches[i-1]]["match_info"]["time"])
        curr_dt = parse_match_datetime(COMPOS_EN_MEMOIRE[sorted_matches[i]]["match_info"]["time"])

        if prev_dt and curr_dt:
            ecart = (curr_dt - prev_dt).total_seconds() / 60
        else:
            ecart = 999  # Sécurité : si on ne peut pas parser, on sépare

        if ecart <= ECART_MAX_VAGUE_MIN:
            current_wave.append(sorted_matches[i])
        else:
            waves.append(current_wave)
            current_wave = [sorted_matches[i]]

    waves.append(current_wave)
    return waves

def get_wave_key(wave_match_ids):
    """
    Clé unique pour identifier une vague = heure du 1er match de la vague.
    Ex: "01:00_07.03."
    """
    first_time = COMPOS_EN_MEMOIRE[wave_match_ids[0]]["match_info"]["time"]
    return first_time

def is_wave_complete(wave_match_ids, all_scheduled_matches):
    """
    Vérifie si TOUS les matchs schedulés appartenant à cette vague ont leur compo en mémoire.
    On détermine l'appartenance à la vague en regardant si l'heure du match schedulé
    est dans la fenêtre temporelle de la vague (entre premier et dernier match ± 15 min).
    """
    first_dt = parse_match_datetime(COMPOS_EN_MEMOIRE[wave_match_ids[0]]["match_info"]["time"])
    last_dt  = parse_match_datetime(COMPOS_EN_MEMOIRE[wave_match_ids[-1]]["match_info"]["time"])

    if not first_dt or not last_dt:
        return True  # Sécurité

    window_start = first_dt - timedelta(minutes=1)
    window_end   = last_dt  + timedelta(minutes=ECART_MAX_VAGUE_MIN)

    for m in all_scheduled_matches:
        m_dt = parse_match_datetime(m["time"])
        if not m_dt:
            continue
        # Ce match schedulé fait-il partie de la fenêtre de la vague ?
        if window_start <= m_dt <= window_end:
            # A-t-il sa compo en mémoire ?
            if m["id"] not in COMPOS_EN_MEMOIRE:
                return False  # Compo manquante   vague incomplète

    return True  # Toutes les compos sont là !

def should_force_send(wave_match_ids):
    """
    Retourne True si on est à moins de FORCE_ENVOI_MIN_AVANT minutes
    du 1er match de la vague   on envoie même si des compos manquent.
    """
    first_dt = parse_match_datetime(COMPOS_EN_MEMOIRE[wave_match_ids[0]]["match_info"]["time"])
    if not first_dt:
        return False
    now = datetime.now()
    minutes_before_match = (first_dt - now).total_seconds() / 60
    return minutes_before_match <= FORCE_ENVOI_MIN_AVANT

# ==========================================
# FONCTIONS UTILITAIRES EXISTANTES
# ==========================================

def is_active_hours():
    now = datetime.now()
    hour = now.hour
    return hour >= 17 or hour <= 4

def update_daily_stats():
    global LAST_STATS_UPDATE
    now = datetime.now()
    nhl_date = (now - timedelta(hours=12)).strftime("%Y-%m-%d")
    if LAST_STATS_UPDATE != nhl_date:
        logger.info(f"\n[{now.strftime('%H:%M:%S')}] MISE À JOUR AUTOMATIQUE NST EN COURS...")
        try:
            subprocess.run([sys.executable, "fichier.py"], check=True)
            LAST_STATS_UPDATE = nhl_date
            logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Fichiers NST mis à jour avec succès !")
        except Exception as e:
            logger.info(f"Erreur critique sur fichier.py : {e}")

def purge_old_matches():
    """Supprime de la mémoire les matchs qui ont déjà commencé."""
    global COMPOS_EN_MEMOIRE
    now = datetime.now()
    matchs_a_supprimer = []
    for match_id, data in COMPOS_EN_MEMOIRE.items():
        match_dt = parse_match_datetime(data["match_info"]["time"])
        if match_dt and now > match_dt + timedelta(minutes=5):
            matchs_a_supprimer.append(match_id)
    for m_id in matchs_a_supprimer:
        del COMPOS_EN_MEMOIRE[m_id]
        logger.info(f"   Match {m_id} purgé de la mémoire (match commencé).")

# ==========================================
# MOTEUR DE CALCUL (inchangé)
# ==========================================

def run_analysis_and_send(match_ids_for_wave, wave_label):
    """
    Lance l'analyse predictor_v8 sur un ensemble de matchs et envoie le Telegram.
    Paramètres :
      - match_ids_for_wave : liste des match_ids de la vague
      - wave_label         : label lisible pour les logs (ex: "01:00   01:10 (3 matchs)")
    """
    nb_matchs = len(match_ids_for_wave)
    logger.info(f"\n---  ANALYSE VAGUE {wave_label} ({nb_matchs} matchs) ---")

    # Écriture du fichier temporaire uniquement avec les matchs de cette vague
    with open(FICHIER_COMPOS_TEMPORAIRE, "w", encoding="utf-8") as f:
        for mid in match_ids_for_wave:
            data = COMPOS_EN_MEMOIRE[mid]
            m = data["match_info"]
            compo = data["compo"]
            txt_block = (
                f"Match : {m['home']} - {m['away']} ({m['time']})\n"
                f"  goal dom: {compo['goalDom']}\n"
                f"  goal ext: {compo['goalext']}\n"
                f"  f1 dom: {compo['f1_dom']}\n"
                f"  f1 ext: {compo['f1_ext']}\n"
                f"  f2 dom: {compo['f2_dom']}\n"
                f"  f2 ext: {compo['f2_ext']}\n"
                f"{'-'*40}\n"
            )
            f.write(txt_block)

    TODAY_DATE = datetime.now().strftime("%Y-%m-%d")

    v5_data    = predictor_v8.load_v5_base_stats('./stats/Player Season Totals.csv')
    form_data  = predictor_v8.load_recent_form('./stats/last 10.csv')
    matchups   = predictor_v8.load_matchup_data('./stats/team.csv')
    pp_stats   = predictor_v8.load_powerplay_stats('./stats/power play.csv')

    known_players = list(form_data.keys()) + list(v5_data.keys())

    MATCHS_DU_SOIR, COMPOS_DU_SOIR_BRUTES, STARTING_GOALIES = predictor_v8.parse_flashscore_file(
        FICHIER_COMPOS_TEMPORAIRE, known_players
    )
    COMPOS_DU_SOIR = [p for p in COMPOS_DU_SOIR_BRUTES if p in form_data]
    HOME_TEAMS = [mt[0] for mt in MATCHS_DU_SOIR]

    opponents_tonight = {t1: t2 for t1, t2 in MATCHS_DU_SOIR}
    opponents_tonight.update({t2: t1 for t1, t2 in MATCHS_DU_SOIR})

    B2B_TEAMS  = [t for t in predictor_v8.get_b2b_teams('./stats/match.csv', TODAY_DATE) if t in opponents_tonight]
    PP1_PLAYERS = predictor_v8.get_auto_pp1_players(form_data, pp_stats, opponents_tonight.keys())

    active_superstars_by_team = {t: [] for t in predictor_v8.TEAM_MAPPING.values()}
    for p in COMPOS_DU_SOIR:
        if p in predictor_v8.SUPERSTARS_PLAYMAKERS and p in form_data:
            team_clean = predictor_v8.clean_team_name(form_data[p]['Team'])
            if team_clean in active_superstars_by_team:
                active_superstars_by_team[team_clean].append(p)

    results = []
    for player, p_form in form_data.items():
        if player not in COMPOS_DU_SOIR: continue
        team = predictor_v8.clean_team_name(p_form['Team'])
        if p_form['ATOI'] < 13.0: continue

        if team in opponents_tonight:
            adversaire   = opponents_tonight[team]
            adv_stats    = matchups.get(adversaire)
            p_v5_stats   = v5_data.get(player, {})

            is_pp1            = player in PP1_PLAYERS
            is_home           = team in HOME_TEAMS
            stars_in_team     = active_superstars_by_team.get(team, [])
            has_star_linemate = len([s for s in stars_in_team if s != player]) > 0
            is_b2b            = team in B2B_TEAMS and adversaire not in B2B_TEAMS
            adv_goalie        = STARTING_GOALIES.get(adversaire, "")
            is_backup         = predictor_v8.check_if_backup_goalie(adv_goalie, v5_data, form_data)

            base_qs = predictor_v8.calculate_base_qs(p_v5_stats, p_form, adv_stats, is_pp1, is_home, has_star_linemate)
            if base_qs <= -90: continue

            final_qs = base_qs
            if is_backup: final_qs += 2.5
            if is_b2b:    final_qs -= 1.5

            context_tag = []
            if is_home:           context_tag.append("🏠")
            if has_star_linemate: context_tag.append("🤝")
            if is_b2b:            context_tag.append("😴")
            if is_backup:         context_tag.append("🥅")

            results.append({
                "Joueur":    player,
                "Equipe":    team,
                "Adversaire": adversaire,
                "Score":     round(final_qs, 1),
                "Base":      round(base_qs, 1),
                "PP1":       "⭐" if is_pp1 else "",
                "Tag":       " ".join(context_tag)
            })

    results = sorted(results, key=lambda x: x["Score"], reverse=True)

    # Filtre Diversité
    final_top10 = []
    team_counts  = {}
    match_counts = {}
    for r in results:
        equipe   = r['Equipe']
        match_key = frozenset([r['Equipe'], r['Adversaire']])
        if team_counts.get(equipe, 0) < 1 and match_counts.get(match_key, 0) < 2:
            final_top10.append(r)
            team_counts[equipe] = 1
            match_counts[match_key] = match_counts.get(match_key, 0) + 1
        if len(final_top10) >= 10: break

    # Formatage et envoi Telegram
    logger.info(f"\n=== RÉSULTATS VAGUE {wave_label} ===")

    if not final_top10:
        logger.info("Aucun joueur n'a passé les filtres sur cette vague.")
        return

    tg_message = f"🎯 <b>VAGUE {wave_label} — {nb_matchs} match(s) NHL</b> 🎯\n\n"

    for i, r in enumerate(final_top10):
        if   r["Score"] >= 9.0: reco = "🔥 <b>ELITE</b>"
        elif r["Score"] >= 7.0: reco = "✅ <b>JOUABLE</b>"
        elif r["Score"] > 5.5: reco = "☑️ <i> JOUABLE MAIS AVEC RISQUE</i>"
        elif r["Score"] >= 5.0: reco = "⚠️ <i>RISQUÉ</i>"
        else:                   reco = "❌ À ÉVITER"

        team_full = predictor_v8.REVERSE_TEAM_MAPPING.get(r['Equipe'], r['Equipe'])
        adv_full  = predictor_v8.REVERSE_TEAM_MAPPING.get(r['Adversaire'], r['Adversaire'])


        tg_message += f"<b>{i+1}. {r['Joueur']}</b> {r['PP1']} {r['Tag']}\n"
        tg_message += f"🏒 <i>{team_full} vs {adv_full}</i>\n"
        tg_message += f"📊 Score: <b>{r['Score']}</b> | {reco}\n\n"

    send_telegram_message(tg_message)

# ==========================================
# ROUTINE PRINCIPALE
# ==========================================

def bot_routine():
    global MATCHS_TRAITES, COMPOS_EN_MEMOIRE, VAGUES_ENVOYEES

    logger.info(f"\n[{datetime.now().strftime('%H:%M:%S')}]  Lancement de la routine de scan Flashscore...")

    # 1. Nettoyage des matchs passés
    purge_old_matches()

    # 2. Récupération des matchs du soir
    matches_du_jour = scraper.get_scheduled_matches("https://www.flashscore.fr/hockey/usa/nhl/calendrier/")
    nouvelles_compos_trouvees = False

    for m in matches_du_jour:
        match_id = m['id']

        if match_id in MATCHS_TRAITES:
            continue

        logger.info(f"   Vérification compo : {m['home']} - {m['away']}...")
        compo = scraper.get_lineups(match_id)

        if isinstance(compo, dict):
            logger.info(f"    COMPO TROUVÉE ! Mise en mémoire.")
            COMPOS_EN_MEMOIRE[match_id] = {"match_info": m, "compo": compo}
            MATCHS_TRAITES.add(match_id)
            nouvelles_compos_trouvees = True
        else:
            logger.info(f"   {compo} — On réessaiera au prochain cycle.")

    # 3. Pas de compos en mémoire   rien à faire
    if not COMPOS_EN_MEMOIRE:
        logger.info("   Aucune compo en mémoire. En attente...")
        return

    # 4. Construction des vagues par clustering
    waves = build_waves(list(COMPOS_EN_MEMOIRE.keys()))

    logger.info(f"   {len(waves)} vague(s) détectée(s) pour ce soir.")

    for wave in waves:
        wave_key = get_wave_key(wave)

        # Déjà envoyée   on skip
        if wave_key in VAGUES_ENVOYEES:
            continue

        # Infos lisibles pour les logs
        heures = [COMPOS_EN_MEMOIRE[mid]["match_info"]["time"].split(" ")[1] for mid in wave]
        wave_label = f"{heures[0]}" if len(heures) == 1 else f"{heures[0]}   {heures[-1]} ({len(wave)} matchs)"

        complete  = is_wave_complete(wave, matches_du_jour)
        force_now = should_force_send(wave)

        if complete:
            logger.info(f"   Vague {wave_label} : toutes les compos sont là   ENVOI !")
            run_analysis_and_send(wave, wave_label)
            VAGUES_ENVOYEES.add(wave_key)

        elif force_now:
            # Combien de matchs manquent ?
            matchs_manquants = [
                m for m in matches_du_jour
                if m["id"] not in COMPOS_EN_MEMOIRE
                and is_wave_complete(wave, [m]) is False  # approximation
            ]
            logger.info(
                f"   Vague {wave_label} : compo(s) manquante(s) mais "
                f"<{FORCE_ENVOI_MIN_AVANT} min avant le match   ENVOI FORCÉ !"
            )
            run_analysis_and_send(wave, wave_label + " ⚠️forcé")
            VAGUES_ENVOYEES.add(wave_key)

        else:
            # On compte combien il manque pour le log
            nb_ok      = len(wave)
            nb_total   = sum(
                1 for m in matches_du_jour
                if parse_match_datetime(m["time"]) is not None
                and abs(
                    (parse_match_datetime(m["time"]) -
                     parse_match_datetime(COMPOS_EN_MEMOIRE[wave[0]]["match_info"]["time"])).total_seconds()
                ) <= ECART_MAX_VAGUE_MIN * 60 * 2
            )
            first_dt   = parse_match_datetime(COMPOS_EN_MEMOIRE[wave[0]]["match_info"]["time"])
            mins_left  = int((first_dt - datetime.now()).total_seconds() / 60) if first_dt else "?"
            logger.info(
                f"   Vague {wave_label} : {nb_ok}/{nb_total} compo(s) — "
                f"premier match dans ~{mins_left} min. On attend..."
            )

# ==========================================
# POINT D'ENTRÉE
# ==========================================

if __name__ == "__main__":
    logger.info("=====================================================")
    logger.info("  DÉMARRAGE DU ROBOT NHL VALUE BETS V10 (VAGUES)  ")
    logger.info(" Scan toutes les 15 min — envoi par vague horaire  ")
    logger.info(" Écart max dans une vague : 15 min                 ")
    logger.info(" Force envoi si < 5 min avant le 1er match        ")
    logger.info("=====================================================")

    while True:
        try:
            if is_active_hours():
                update_daily_stats()
                bot_routine()
            else:
                if MATCHS_TRAITES:
                    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Fin de journée — nettoyage global.")
                    MATCHS_TRAITES.clear()
                    COMPOS_EN_MEMOIRE.clear()
                    VAGUES_ENVOYEES.clear()
                else:
                    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Hors horaires (05h-17h). En veille...")

            time.sleep(900)  # 15 minutes

        except Exception as e:
            logger.info(f"ERREUR CRITIQUE : {e}")
            logger.info("Redémarrage dans 5 minutes...")
            time.sleep(300)