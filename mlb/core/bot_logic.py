"""
mlb/core/bot_logic.py — Logique d'orchestration pour le bot MLB.
"""

import sys
import os
import logging
import asyncio
from datetime import datetime
import pandas as pd

# Ajout du dossier racine
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.base_bot import BaseSportBot
from mlb.data.fetcher import get_todays_probables, get_pitcher_historical_stats, get_team_strikeout_rate
from mlb.core.market_filter import evaluate_pitcher_strikeouts
from shared.odds_api import fetch_mlb_odds
from shared.telegram_hub import send_telegram
from shared.portfolio import Portfolio

logger = logging.getLogger("MLB.BotLogic")

class MlbBot(BaseSportBot):
    """
    Bot MLB : gère la récupération des données, filtres, cotes et envois.
    """
    sport_name = "MLB"
    
    def __init__(self):
        super().__init__()
        self.portfolio = Portfolio()
        self.scanned_today = False
        
    def run_scan_cycle(self) -> None:
        """
        Cycle de scan principal, exécuté 1-2 fois par jour.
        """
        logger.info(f"\n--- ⚾ SCAN MLB DÉMARRÉ ({datetime.now().strftime('%H:%M:%S')}) ---")
        
        # 1. Récupérer les Probables Pitchers du jour
        df_probables = get_todays_probables()
        if df_probables.empty:
            logger.info("Aucun match ou probables pitchers trouvés aujourd'hui.")
            return
            
        picks_strikeouts = []
        players_to_fetch_odds = {}
        
        # 2. Analyser chaque lanceur
        for _, row in df_probables.iterrows():
            pitcher = row.get("Pitcher")
            team = row.get("Team")
            opp = row.get("Opp")
            
            if pd.isna(pitcher) or not pitcher:
                continue
                
            # Déterminer si le lanceur est à domicile
            # Dans pybaseball, si l'adversaire commence par '@', le lanceur est AWAY.
            is_home = True
            if str(opp).startswith('@'):
                is_home = False
                opp = opp[1:] # Retirer le '@' pour la recherche DB
            
            logger.info(f"Analyse de {pitcher} ({team}) {'HOME' if is_home else 'AWAY'} vs {opp}...")
            
            # Récupérer l'historique DB du lanceur et le K% de l'équipe adverse
            p_stats = get_pitcher_historical_stats(pitcher)
            adv_k_rate = get_team_strikeout_rate(opp)
            
            # Appliquer le filtre mathématique (XGBoost)
            pick_k = evaluate_pitcher_strikeouts(pitcher, p_stats, adv_k_rate, is_home=is_home)
            
            
            if pick_k:
                pick_k["Equipe"] = team
                pick_k["Adversaire"] = opp
                picks_strikeouts.append(pick_k)
                players_to_fetch_odds[pitcher] = team
                
        # 3. Récupérer les cotes pour les picks qualifiés
        if players_to_fetch_odds:
            logger.info(f"Récupération des cotes pour {len(players_to_fetch_odds)} lanceurs...")
            odds_map = asyncio.run(fetch_mlb_odds(players_to_fetch_odds))
            logger.info(f"Cotes récupérées pour {len(odds_map)} joueurs sur {len(players_to_fetch_odds)} demandés.")
            
            for pick in picks_strikeouts:
                joueur = pick["Joueur"]
                odds_data = odds_map.get(joueur, {}).get("STRIKEOUTS", {})
                
                if isinstance(odds_data, dict):
                    pick["Cote"] = odds_data.get("price", 0.0)
                    pick["Bookmaker"] = odds_data.get("bookmaker", "Inconnu")
                else:
                    pick["Cote"] = 0.0
                    pick["Bookmaker"] = "Inconnu"
                
        # 4. Filtrer les picks sans cote ou avec une cote trop faible
        final_picks = [p for p in picks_strikeouts if p.get("Cote", 0) >= 1.50]
        
        # 5. Calcul du Kelly Criterion et filtre EV (avec Money Management Global)
        from shared.portfolio import Portfolio
        pf = Portfolio()
        current_exposure = pf.get_pending_exposure()
        max_exposure = 15.0  # Plafond maximal de la bankroll

        validated_picks = []
        for p in final_picks:
            cote = p["Cote"]
            proba = p.get("Proba", 0.50)
            
            # Calcul de l'Expected Value (EV)
            ev = (proba * cote) - 1.0
            p["EV"] = round(ev * 100, 1)  # EV en pourcentage
            
            # Filtre EV strict : on ne mise que si l'avantage mathématique > 5%
            if ev < 0.05:
                logger.info(f"❌ {p['Joueur']} rejeté (EV: {p['EV']}% < 5%)")
                continue
            
            # Quarter Kelly Criterion pour le sizing
            b = cote - 1.0
            q = 1.0 - proba
            f_kelly = (proba * b - q) / b
            
            if f_kelly > 0:
                # 1/8ème de Kelly (très prudent) — même formule que NHL
                eighth_kelly = f_kelly / 8.0
                mise = round(eighth_kelly * 100 * 2) / 2  # Arrondi à 0.5 U
                # Plafonds MLB : min 0.5 U, max 3.0 U
                mise = max(0.5, min(mise, 3.0))
                
                # Money Management Global
                if current_exposure + mise > max_exposure:
                    remaining_capacity = max(0.0, max_exposure - current_exposure)
                    remaining_capacity = round(remaining_capacity * 2) / 2
                    mise = min(mise, remaining_capacity)
                    
                    if mise <= 0:
                        logger.warning(f"❌ {p['Joueur']} ignoré : Plafond d'exposition globale atteint.")
                        continue
                    else:
                        logger.warning(f"⚠️ {p['Joueur']} : Mise réduite à {mise}U pour respecter le plafond global.")
                
                current_exposure += mise
            else:
                mise = 0.0
                
            if mise > 0:
                p["Mise"] = mise
                validated_picks.append(p)
                logger.info(f"✅ {p['Joueur']} validé (EV: +{p['EV']}%, Mise: {mise}U, Proba: {proba:.0%})")
        
        # 6. Envoyer sur Telegram et Logger dans le portfolio
        if validated_picks:
            msg = "⚾ <b>ALERTE MLB - STRIKEOUTS</b> ⚾\n\n"
            for p in validated_picks:
                confiance_emoji = "🔥" if p["Confiance"] == "ELITE" else "✅" if p["Confiance"] == "ELEVEE" else "📊"
                bookmaker = p.get("Bookmaker", "Inconnu")
                msg += f"{confiance_emoji} <b>{p['Joueur']}</b> ({p['Equipe']}) vs {p['Adversaire']}\n"
                msg += f"🎯 Marché : OVER Strikeouts\n"
                msg += f"💰 Cote : <b>{p['Cote']:.2f}</b> chez <b>{bookmaker}</b>\n"
                msg += f"🤖 Prédiction IA : <b>{p['Predicted_K']:.1f} K</b> (Proba: {p['Proba']:.0%})\n"
                msg += f"📈 Edge : <b>+{p['EV']}%</b>\n"
                msg += f"💵 Mise Kelly : <b>{p['Mise']} U</b>\n"
                msg += f"📊 Moyenne récente : {p['Moyenne_K']:.1f} K/match\n"
                msg += f"📉 K-Rate Adv : {p['Adv_K_Rate']*100:.1f}%\n\n"
                
                # Enregistrement dans le portfolio avec la mise Kelly
                self.portfolio.log_bet(
                    sport="mlb",
                    player=p["Joueur"],
                    market="STRIKEOUTS",
                    cote=p["Cote"],
                    mise=p["Mise"]
                )
                
            logger.info("Envoi Telegram MLB...")
            send_telegram(msg)
        else:
            logger.info("Aucun value bet MLB trouvé pour ce scan.")
            
    def end_of_day_cleanup(self) -> None:
        """
        Nettoyage de fin de journée, exécuté à 5h UTC.
        Lancement du harvester pour mettre à jour la BDD locale.
        """
        logger.info("🧹 Lancement du MLB Harvester pour mise à jour de la DB...")
        from mlb.core.harvester import run_harvester_once
        run_harvester_once()
        self.scanned_today = False

    def update_daily_stats(self) -> bool:
        """
        Met à jour les statistiques quotidiennes.
        Pour la MLB, cela est géré par l'end_of_day_cleanup (harvester).
        """
        logger.info("Mise à jour des stats quotidiennes MLB (déléguée au harvester).")
        return True
