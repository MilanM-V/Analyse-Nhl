"""
shared/portfolio.py — Simulation de portefeuille multi-sport.

Track la bankroll virtuelle (100 U par défaut) à travers tous les sports.
Chaque bot appelle log_bet() quand il recommande un pari,
et resolve_bet() quand le résultat est connu.

Usage:
    from shared.portfolio import Portfolio

    portfolio = Portfolio()
    bet_id = portfolio.log_bet("nhl", "McDavid", "PASSEUR", cote=2.40, mise=1.5)
    portfolio.resolve_bet(bet_id, won=True)
    print(portfolio.get_balance())  # 102.1
"""

import os
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger("Portfolio")

# La DB portfolio est à la racine du projet (partagée entre tous les sports)
_PORTFOLIO_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "portfolio.db",
)

INITIAL_BANKROLL = 100.0  # Unités


class Portfolio:
    """Gestionnaire de portefeuille simulé multi-sport."""

    def __init__(self, db_path: str = _PORTFOLIO_DB) -> None:
        """Initialise le portfolio et crée la table si nécessaire.

        Args:
            db_path: Chemin vers la base de données SQLite.
        """
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Retourne une connexion à la base portfolio."""
        return sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)

    def _init_db(self) -> None:
        """Crée la table portfolio si elle n'existe pas."""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                sport TEXT NOT NULL,
                pick_id INTEGER,
                player TEXT,
                market TEXT,
                cote REAL,
                mise REAL,
                gain REAL DEFAULT NULL,
                solde_apres REAL DEFAULT NULL,
                resolved INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()
        logger.info(f"[Portfolio] Base initialisée : {self.db_path}")

    def get_balance(self) -> float:
        """Calcule le solde actuel du portefeuille.

        Returns:
            Solde en Unités (bankroll initiale + somme des gains résolus).
        """
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT COALESCE(SUM(gain), 0) FROM portfolio WHERE resolved = 1")
        total_gain = c.fetchone()[0]
        conn.close()
        return INITIAL_BANKROLL + total_gain

    def get_pending_exposure(self) -> float:
        """Calcule l'exposition totale sur les paris en attente.

        Returns:
            Total des mises non résolues.
        """
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT COALESCE(SUM(mise), 0) FROM portfolio WHERE resolved = 0")
        exposure = c.fetchone()[0]
        conn.close()
        return exposure

    def log_bet(
        self,
        sport: str,
        player: str,
        market: str,
        cote: float,
        mise: float,
        pick_id: Optional[int] = None,
    ) -> int:
        """Enregistre un nouveau pari dans le portefeuille.

        Args:
            sport: Nom du sport ('nhl', 'mlb', 'nba').
            player: Nom du joueur.
            market: Type de marché ('PASSEUR', 'POINTEUR', 'STRIKEOUT', etc.).
            cote: Cote décimale du bookmaker.
            mise: Montant misé en Unités.
            pick_id: ID du pick dans la table du sport (optionnel).

        Returns:
            L'ID du pari inséré dans le portfolio.
        """
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            """INSERT INTO portfolio
               (timestamp, sport, pick_id, player, market, cote, mise, resolved)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                datetime.now().isoformat(),
                sport,
                pick_id,
                player,
                market,
                cote,
                mise,
            ),
        )
        bet_id = c.lastrowid
        conn.commit()
        conn.close()
        logger.info(
            f"[Portfolio] 📝 Pari enregistré : {sport.upper()} {player} "
            f"({market}) @ {cote:.2f} — {mise} U"
        )
        return bet_id

    def resolve_bet(self, bet_id: int, won: bool) -> float:
        """Résout un pari et calcule le gain/perte.

        Args:
            bet_id: ID du pari dans le portfolio.
            won: True si le pari est gagné.

        Returns:
            Le gain en Unités (positif si gagné, négatif si perdu).
        """
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT cote, mise FROM portfolio WHERE id = ?", (bet_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return 0.0

        cote, mise = row
        gain = (cote * mise - mise) if won else -mise
        solde = self.get_balance() + gain

        c.execute(
            "UPDATE portfolio SET gain = ?, solde_apres = ?, resolved = 1 WHERE id = ?",
            (round(gain, 2), round(solde, 2), bet_id),
        )
        conn.commit()
        conn.close()

        emoji = "✅" if won else "❌"
        logger.info(
            f"[Portfolio] {emoji} Pari #{bet_id} résolu : "
            f"{'GAGNÉ' if won else 'PERDU'} → {gain:+.2f} U (solde: {solde:.1f} U)"
        )
        return gain

    def get_daily_pnl(self, date: Optional[str] = None) -> Dict[str, Any]:
        """Calcule le P&L du jour (ou d'une date donnée).

        Args:
            date: Date au format YYYY-MM-DD (défaut: aujourd'hui).

        Returns:
            Dict avec 'total_gain', 'nb_bets', 'nb_won', 'nb_lost', 'by_sport'.
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            """SELECT sport, gain, mise FROM portfolio
               WHERE resolved = 1 AND timestamp LIKE ?""",
            (f"{date}%",),
        )
        rows = c.fetchall()
        conn.close()

        by_sport: Dict[str, float] = {}
        nb_won = 0
        nb_lost = 0
        total_gain = 0.0

        for sport, gain, mise in rows:
            total_gain += gain
            by_sport[sport] = by_sport.get(sport, 0.0) + gain
            if gain > 0:
                nb_won += 1
            else:
                nb_lost += 1

        return {
            "date": date,
            "total_gain": round(total_gain, 2),
            "nb_bets": len(rows),
            "nb_won": nb_won,
            "nb_lost": nb_lost,
            "by_sport": by_sport,
        }

    def format_telegram_summary(self) -> str:
        """Génère un résumé formaté pour Telegram.

        Returns:
            Message HTML avec le solde et P&L du jour.
        """
        balance = self.get_balance()
        pnl = self.get_daily_pnl()
        pending = self.get_pending_exposure()

        pnl_sign = "+" if pnl["total_gain"] >= 0 else ""
        balance_emoji = "📈" if balance >= INITIAL_BANKROLL else "📉"

        msg = (
            f"💰 <b>PORTFOLIO</b>\n\n"
            f"{balance_emoji} Solde : <b>{balance:.1f} U</b>\n"
            f"📊 P&L Jour : <b>{pnl_sign}{pnl['total_gain']:.1f} U</b> "
            f"({pnl['nb_won']}✅ / {pnl['nb_lost']}❌)\n"
            f"⏳ En attente : {pending:.1f} U\n"
        )

        if pnl["by_sport"]:
            msg += "\n<b>Par Sport :</b>\n"
            for sport, gain in sorted(pnl["by_sport"].items()):
                s = "+" if gain >= 0 else ""
                msg += f"  • {sport.upper()} : {s}{gain:.1f} U\n"

        return msg
