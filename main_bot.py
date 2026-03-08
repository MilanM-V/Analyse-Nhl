"""
NHL BETTING BOT V10 - Serveur Autonome par "Vagues Horaires"
- Met à jour NST automatiquement (1x/jour)
- Garde en mémoire TOUTES les compos des matchs qui n'ont pas encore commencé
- Compare les joueurs par "Pack" pour te donner un vrai Top 10 global du moment !
"""
import time
from datetime import datetime, timedelta
import os
import sys
import subprocess
import requests

import scraper
import predictor_v8  # Ton fichier V8.6 Masterclass

# ==========================================
# CONFIGURATION TELEGRAM
# ==========================================
TELEGRAM_BOT_TOKEN = "8798595273:AAFP4sn1ku4CLwaI0H0gJkn8ZLh2YYZimmw" 
TELEGRAM_CHAT_ID = "-1003823875034" 

def send_telegram_message(message):
    if TELEGRAM_BOT_TOKEN == "TELEGRAM_BOT_TOKEN" or not TELEGRAM_BOT_TOKEN:
        print("⚠️ Message non envoyé : Identifiants Telegram manquants.")
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
            print(f"⚠️ Erreur d'envoi Telegram : {response.text}")
        else:
            print("📲 Alerte Telegram envoyée avec succès !")
    except Exception as e:
        print(f"⚠️ Exception lors de l'envoi Telegram : {e}")

# ==========================================
# LE MOTEUR DU ROBOT (VAGUES HORAIRES)
# ==========================================
MATCHS_TRAITES = set() # Pour ne pas re-scraper Flashscore pour rien
COMPOS_EN_MEMOIRE = {} # Structure: { match_id : {"match_info": {...}, "compo": {...}} }
FICHIER_COMPOS_TEMPORAIRE = "compos_live.txt"
LAST_STATS_UPDATE = None  

def is_active_hours():
    now = datetime.now()
    hour = now.hour
    if hour >= 17 or hour <= 4:
        return True
    return False

def update_daily_stats():
    global LAST_STATS_UPDATE
    now = datetime.now()
    nhl_date = (now - timedelta(hours=12)).strftime("%Y-%m-%d")
    
    if LAST_STATS_UPDATE != nhl_date:
        print(f"\n[{now.strftime('%H:%M:%S')}] 🔄 MISE À JOUR AUTOMATIQUE NST EN COURS...")
        #send_telegram_message("🔄 <i>Début de session : Mise à jour automatique des statistiques NST en cours...</i>")
        try:
            subprocess.run([sys.executable, "fichier.py"], check=True)
            LAST_STATS_UPDATE = nhl_date
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Fichiers NST mis à jour avec succès !")
            #send_telegram_message("✅ <b>Statistiques NST à jour !</b> Le robot est prêt à scanner les compos de la nuit. 🏒")
        except Exception as e:
            print(f"❌ Erreur critique sur fichier.py : {e}")
            #send_telegram_message(f"⚠️ <b>Erreur de mise à jour NST :</b> Le téléchargement a échoué.")

def purge_old_matches():
    """ 🧹 Supprime de la mémoire les matchs qui ont déjà commencé """
    global COMPOS_EN_MEMOIRE
    now = datetime.now()
    matchs_a_supprimer = []
    
    for match_id, data in COMPOS_EN_MEMOIRE.items():
        time_str = data["match_info"]["time"] # format "07.03. 01:00"
        try:
            # On reconstruit l'heure exacte du match
            match_dt = datetime.strptime(f"{time_str} {now.year}", "%d.%m. %H:%M %Y")
            # Si on est en janvier/février mais que le match indique décembre (cas de fin d'année), on ajuste
            if match_dt.month == 12 and now.month == 1:
                match_dt = match_dt.replace(year=now.year - 1)
                
            # Si l'heure actuelle a dépassé l'heure du match + 5 minutes de marge, on vire !
            if now > (match_dt + timedelta(minutes=5)):
                matchs_a_supprimer.append(match_id)
        except Exception as e:
            print(f"Erreur parsing date pour purge: {e}")
            pass

    for m_id in matchs_a_supprimer:
        del COMPOS_EN_MEMOIRE[m_id]
        print(f"  🧹 Match {m_id} purgé de la mémoire (Le match a commencé).")

def bot_routine():
    global MATCHS_TRAITES, COMPOS_EN_MEMOIRE
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🤖 Lancement de la routine de scan Flashscore...")

    # 1. On nettoie le passé !
    purge_old_matches()

    # 2. On cherche les nouveaux matchs
    matches_du_jour = scraper.get_scheduled_matches("https://www.flashscore.fr/hockey/usa/nhl/calendrier/")
    nouvelles_compos_trouvees = False

    for m in matches_du_jour:
        match_id = m['id']
        
        if match_id in MATCHS_TRAITES:
            continue 

        print(f"  🔍 Vérification des compos pour: {m['home']} - {m['away']}...")
        compo = scraper.get_lineups(match_id)

        if isinstance(compo, dict):
            print(f"  ✅ COMPO TROUVÉE ! Mise en mémoire.")
            # On stocke dans la mémoire globale
            COMPOS_EN_MEMOIRE[match_id] = {"match_info": m, "compo": compo}
            MATCHS_TRAITES.add(match_id) 
            nouvelles_compos_trouvees = True
        else:
            print(f"  ⏳ {compo} - On réessaiera au prochain cycle.")

    # 3. SI on a trouvé au moins UNE nouvelle compo ce tour-ci, on re-calcule TOUT le futur
    if nouvelles_compos_trouvees and len(COMPOS_EN_MEMOIRE) > 0:
        nb_matchs_pack = len(COMPOS_EN_MEMOIRE)
        print(f"\n--- ⚡ CRÉATION DU PACK GLOBAL ({nb_matchs_pack} Matchs en attente) : LANCEMENT DU MOTEUR ---")
        
        # On écrit TOUS les matchs en mémoire dans le fichier texte pour l'analyse V8
        with open(FICHIER_COMPOS_TEMPORAIRE, "w", encoding="utf-8") as f:
            for data in COMPOS_EN_MEMOIRE.values():
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
        
        v5_data = predictor_v8.load_v5_base_stats('./stats/Player Season Totals.csv')
        form_data = predictor_v8.load_recent_form('./stats/last 10.csv')
        matchups = predictor_v8.load_matchup_data('./stats/team.csv')
        pp_stats = predictor_v8.load_powerplay_stats('./stats/power play.csv') 
        
        known_players = list(form_data.keys()) + list(v5_data.keys())
        
        MATCHS_DU_SOIR, COMPOS_DU_SOIR_BRUTES, STARTING_GOALIES = predictor_v8.parse_flashscore_file(FICHIER_COMPOS_TEMPORAIRE, known_players)
        COMPOS_DU_SOIR = [p for p in COMPOS_DU_SOIR_BRUTES if p in form_data]
        HOME_TEAMS = [mt[0] for mt in MATCHS_DU_SOIR]
        
        opponents_tonight = {t1: t2 for t1, t2 in MATCHS_DU_SOIR}
        opponents_tonight.update({t2: t1 for t1, t2 in MATCHS_DU_SOIR})
        B2B_TEAMS = [t for t in predictor_v8.get_b2b_teams('./stats/match.csv', TODAY_DATE) if t in opponents_tonight.keys()]
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
                adversaire = opponents_tonight[team]
                adv_stats = matchups.get(adversaire)
                p_v5_stats = v5_data.get(player, {}) 
                
                is_pp1 = player in PP1_PLAYERS
                is_home = team in HOME_TEAMS
                stars_in_team = active_superstars_by_team.get(team, [])
                has_star_linemate = len([s for s in stars_in_team if s != player]) > 0
                is_b2b = team in B2B_TEAMS and adversaire not in B2B_TEAMS
                both_b2b = team in B2B_TEAMS and adversaire in B2B_TEAMS
                adv_goalie = STARTING_GOALIES.get(adversaire, "")
                is_backup = predictor_v8.check_if_backup_goalie(adv_goalie, v5_data, form_data)
                
                base_qs = predictor_v8.calculate_base_qs(p_v5_stats, p_form, adv_stats, is_pp1, is_home, has_star_linemate)
                if base_qs <= -90: continue 
                
                final_qs = base_qs
                if is_backup: final_qs += 2.5
                if is_b2b: final_qs -= 1.5
                
                context_tag = []
                if is_home: context_tag.append("🏠")
                if has_star_linemate: context_tag.append("🤝")
                if is_b2b: context_tag.append("😴")
                if is_backup: context_tag.append("🥅")
                
                results.append({
                    "Joueur": player, "Equipe": team, "Adversaire": adversaire,
                    "Score": round(final_qs, 1), "Base": round(base_qs, 1),
                    "PP1": "⭐" if is_pp1 else "",
                    "Tag": " ".join(context_tag)
                })
            
        results = sorted(results, key=lambda x: x["Score"], reverse=True)
        
        # Filtre Diversité (Toujours actif !)
        final_top10 = []
        team_counts = {}
        match_counts = {}
        for r in results:
            equipe = r['Equipe']
            match_id = frozenset([r['Equipe'], r['Adversaire']])
            if team_counts.get(equipe, 0) < 1 and match_counts.get(match_id, 0) < 2:
                final_top10.append(r)
                team_counts[equipe] = 1
                match_counts[match_id] = match_counts.get(match_id, 0) + 1
            if len(final_top10) >= 10: break

        # ---------------------------------------------------------
        # FORMATAGE ET ENVOI DU MESSAGE TELEGRAM
        # ---------------------------------------------------------
        print(f"\n🚨 PACK GLOBAL - {nb_matchs_pack} MATCHS EN ATTENTE 🚨")
        
        if not final_top10:
            print("Aucun joueur n'a passé les filtres sur ce pack.")
        else:
            tg_message = f"🎯 <b>PACK GLOBAL : {nb_matchs_pack} Matchs NHL</b> 🎯\n\n"
            
            for i, r in enumerate(final_top10):
                if r["Score"] >= 7.5: reco = "🔥 <b>ELITE</b>"
                elif r["Score"] >= 5.5: reco = "✅ <b>JOUABLE</b>"
                elif r["Score"] >= 3.5: reco = "⚠️ <i>RISQUÉ</i>"
                else: reco = "❌ À ÉVITER"
                
                team_full = predictor_v8.REVERSE_TEAM_MAPPING.get(r['Equipe'], r['Equipe'])
                adv_full = predictor_v8.REVERSE_TEAM_MAPPING.get(r['Adversaire'], r['Adversaire'])
                
                print(f"{i+1:2d}. {r['Joueur']:<20} | {team_full} vs {adv_full} | Score: {r['Score']:>4} | {reco}")
                
                tg_message += f"<b>{i+1}. {r['Joueur']}</b> {r['PP1']} {r['Tag']}\n"
                tg_message += f"🏒 <i>{team_full} vs {adv_full}</i>\n"
                tg_message += f"📊 Score: <b>{r['Score']}</b> | {reco}\n\n"

            send_telegram_message(tg_message)

    else:
        print("  😴 Aucune nouvelle compo. On garde le même pack en mémoire.")

if __name__ == "__main__":
    print("=====================================================")
    print(" 🚀 DEMARRAGE DU ROBOT NHL VALUE BETS V10 (PACKS) 🚀 ")
    print(" Le script va tourner en boucle toutes les 20 mins.")
    print(" Il garde les matchs en mémoire jusqu'au coup d'envoi !")
    print("=====================================================")
    
    while True:
        try:
            if is_active_hours():
                update_daily_stats() 
                bot_routine()
            else:
                if len(MATCHS_TRAITES) > 0:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🧹 Fin de journée, nettoyage global de la mémoire.")
                    MATCHS_TRAITES.clear()
                    COMPOS_EN_MEMOIRE.clear()
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🌙 Hors horaires de match (05h-17h). En veille...")
            
            # Attente de 20 minutes (1200 secondes)
            time.sleep(900)
            
        except Exception as e:
            print(f"⚠️ ERREUR CRITIQUE DU ROBOT : {e}")
            print("Redémarrage de sécurité dans 5 minutes...")
            time.sleep(300)