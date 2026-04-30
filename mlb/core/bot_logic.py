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
from mlb.core.odds_scraper import fetch_mlb_odds
from shared.telegram_hub import send_telegram
from shared.portfolio import Portfolio

logger = logging.getLogger("MLB-BotLogic")

class MlbBot(BaseSportBot):
    """
    Bot MLB : gère la récupération des données, filtres, cotes et envois.
    """
    
    def __init__(self):
        super().__init__("MLB")
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
            
            for pick in picks_strikeouts:
                joueur = pick["Joueur"]
                cote = odds_map.get(joueur, {}).get("STRIKEOUTS", 0)
                pick["Cote"] = cote
                
        # 4. Filtrer les picks sans cote ou avec une cote trop faible
        final_picks = [p for p in picks_strikeouts if p.get("Cote", 0) >= 1.50]
        
        # 5. Envoyer sur Telegram et Logger dans le portfolio
        if final_picks:
            msg = "⚾ <b>ALERTE MLB - STRIKEOUTS</b> ⚾\n\n"
            for p in final_picks:
                msg += f"🔥 <b>{p['Joueur']}</b> ({p['Equipe']}) vs {p['Adversaire']}\n"
                msg += f"🎯 Marché : OVER Strikeouts\n"
                msg += f"💰 Cote : <b>{p['Cote']}</b>\n"
                msg += f"🤖 Prédiction IA : <b>{p['Predicted_K']:.1f} K</b>\n"
                msg += f"📊 Moyenne récente : {p['Moyenne_K']:.1f} K/match\n\n"
                
                # Ajout fictif au portfolio (1U Flat pour l'instant)
                self.portfolio.log_bet(
                    bet_type="STRIKEOUTS",
                    sport="mlb",
                    player_name=p["Joueur"],
                    odds=p["Cote"],
                    stake_u=1.0
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
        from mlb.core.harvester import run_harvester_loop
        run_harvester_loop()
        self.scanned_today = False
