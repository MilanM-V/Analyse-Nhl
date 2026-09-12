"""
shared/base_bot.py — Classe abstraite pour tous les bots sport.

Chaque sport (NHL, MLB, NBA...) implémente un bot qui hérite de BaseSportBot.
Cela garantit une interface commune pour le watchdog et le portfolio.

Usage:
    from shared.base_bot import BaseSportBot

    class NhlBot(BaseSportBot):
        sport_name = "nhl"
        ...
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseSportBot(ABC):
    """Classe abstraite que chaque bot sport doit implémenter."""

    sport_name: str = ""  # 'nhl', 'mlb', 'nba', etc.

    @abstractmethod
    def run_scan_cycle(self) -> None:
        """Exécute un cycle complet de scan.

        Inclut : mise à jour des stats, scan des compos/lineups,
        filtrage marché, odds, envoi Telegram, logging.
        """
        ...

    @abstractmethod
    def end_of_day_cleanup(self) -> None:
        """Nettoyage de fin de journée.

        Inclut : résolution des picks, rapport email, reset mémoire.
        """
        ...

    @abstractmethod
    def update_daily_stats(self) -> bool:
        """Met à jour les statistiques quotidiennes depuis les APIs.

        Returns:
            True si la mise à jour a réussi, False sinon.
        """
        ...

    def get_status(self) -> dict:
        """Retourne l'état courant du bot pour les commandes Telegram.

        Returns:
            Dict avec les infos de status (à surcharger par chaque sport).
        """
        return {
            "sport": self.sport_name,
            "status": "running",
        }
