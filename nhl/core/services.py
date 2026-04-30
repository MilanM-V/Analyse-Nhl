import os
import requests
import smtplib
import time
from functools import wraps
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import logging
from datetime import datetime
from typing import Optional, Any, Dict, List, Callable

from telegram import Bot, Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, Application, CallbackQueryHandler
import asyncio

logger = logging.getLogger("NHL_Bot")

def retry_request(max_retries: int = 3, base_delay: float = 2.0) -> Callable:
    """
    Decorator for exponential backoff on HTTP requests.
    
    Args:
        max_retries: Maximum number of retries.
        base_delay: Initial delay between retries in seconds.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except (requests.exceptions.RequestException, Exception) as e:
                    retries += 1
                    if retries == max_retries:
                        logger.error(f"Erreur HTTP persistante après {max_retries} tentatives : {e}")
                        raise
                    delay = base_delay * (2 ** (retries - 1))
                    logger.warning(f"Erreur HTTP ({e}). Tentative {retries}/{max_retries} dans {delay}s...")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator

@retry_request(max_retries=3, base_delay=2.0)
def safe_get(url: str, **kwargs) -> requests.Response:
    """Performs a GET request with retry logic."""
    resp = requests.get(url, **kwargs)
    resp.raise_for_status()
    return resp

@retry_request(max_retries=3, base_delay=2.0)
def safe_post(url: str, **kwargs) -> requests.Response:
    """Performs a POST request with retry logic."""
    resp = requests.post(url, **kwargs)
    resp.raise_for_status()
    return resp

class TelegramNotifier:
    """Service to handle Telegram notifications via python-telegram-bot."""
    def __init__(self) -> None:
        """Initializes the TelegramNotifier with environment variables."""
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if self.token == "TELEGRAM_BOT_TOKEN" or not self.token:
            logger.warning("[TelegramNotifier] Token non valide ou manquant.")
            self.enabled = False
        else:
            self.enabled = True

        self.bot = Bot(token=self.token) if self.enabled else None

    def send_message(self, message: str) -> None:
        """
        Sends an HTML formatted message synchronously using the underlying bot.

        Args:
            message: The HTML message string to send.
        """
        if not self.enabled:
            return

        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            safe_post(url, json=payload, timeout=10)
            logger.info("Alerte Telegram envoyée avec succès !")
        except Exception as e:
            logger.error(f"Exception lors de l'envoi Telegram : {e}")

    def send_crash_alert(self, error: Exception, context: str = "Bot Principal") -> None:
        """
        Sends an emergency crash notification via Telegram.
        Uses raw requests (no retry decorator) to maximize delivery chance.

        Args:
            error: The exception that caused the crash.
            context: Description of where the crash occurred.
        """
        if not self.enabled:
            return

        import traceback
        tb = traceback.format_exc()
        # Tronquer le traceback à 500 chars pour ne pas dépasser la limite Telegram
        tb_short = tb[-500:] if len(tb) > 500 else tb

        message = (
            f"🚨 <b>CRASH — {context}</b>\n\n"
            f"<b>Erreur:</b> {type(error).__name__}: {error}\n\n"
            f"<pre>{tb_short}</pre>"
        )

        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            # Utilise requests directement, pas safe_post, pour éviter les dépendances circulaires
            requests.post(url, json=payload, timeout=10)
            logger.info("🚨 Alerte crash envoyée sur Telegram.")
        except Exception as e:
            logger.error(f"Impossible d'envoyer l'alerte crash Telegram : {e}")

def create_telegram_app(nhl_bot: Any) -> Optional[Application]:
    """
    Factory to create the interactive telegram application with handlers.

    Args:
        nhl_bot: The NhlBot instance to interact with.

    Returns:
        A configured telegram Application or None if token is missing.
    """
    token = os.getenv("TELEGRAM_TOKEN")
    if not token or token == "TELEGRAM_BOT_TOKEN":
        return None

    app = ApplicationBuilder().token(token).build()

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /start command."""
        if update.message:
            await update.message.reply_text("🏒 NHL Bot V14 Actif ! Commandes:\n/status - État du bot\n/roi - Statistiques SQLite\n/portfolio - Solde du portefeuille\n/force - Lancer un scan")

    async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /status command."""
        n_match_total = len(nhl_bot.matches_du_jour)
        n_match_traites = len(nhl_bot.matchs_traites)
        compo_en_attente = 0
        for match_id, data in nhl_bot.compos_en_memoire.items():
            time_str = data["match_info"]["time"]
            if time_str not in nhl_bot.vagues_envoyees:
                compo_en_attente += 1

        if update.message:
            await update.message.reply_text(f"📊 Status:\nMatchs détectés aujourd'hui: {n_match_total}\nMatchs avec compos traitées: {n_match_traites}\nCompos en attente de vague: {compo_en_attente}")

    async def force_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /force command."""
        if update.message:
            await update.message.reply_text("⚡ Forçage du scan en cours (les logs vont s'afficher sur le serveur)...")

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, nhl_bot.run_scan_cycle)
        if update.message:
            await update.message.reply_text("✅ Fin du scan forcé.")

    async def roi_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /roi command."""
        keyboard = [
            [
                InlineKeyboardButton("1 Jour", callback_data='roi_1'),
                InlineKeyboardButton("1 Semaine", callback_data='roi_7')
            ],
            [
                InlineKeyboardButton("1 Mois", callback_data='roi_30'),
                InlineKeyboardButton("All Time", callback_data='roi_all')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.message:
            await update.message.reply_text("⏳ Sélectionnez la période pour le calcul du ROI :", reply_markup=reply_markup)

    async def roi_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()

        days = query.data.split('_')[1] # '1', '7', '30', 'all'
        label = f"{days} derniers jours" if days != "all" else "All Time"

        await query.edit_message_text(text=f"⏳ Calcul du ROI ({label})... Validation API en cours.")

        from core.updater import update_pending_picks
        loop = asyncio.get_running_loop()
        n_resolved = await loop.run_in_executor(None, update_pending_picks)

        from core.database import get_roi_stats
        
        msg = f"💰 <b>ROI ({label})</b> :\n\n"
        msg += get_roi_stats("picks", "but", days) + "\n"
        msg += get_roi_stats("picks_assists", "assist", days) + "\n"
        msg += get_roi_stats("picks_points", "point", days)
        
        await query.edit_message_text(text=msg, parse_mode="HTML")


    async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /backup command."""
        if update.message:
            await update.message.reply_text("📦 Préparation de l'archive...")
        db_path = "./bot_database.db"
        if os.path.exists(db_path):
            with open(db_path, "rb") as db_file:
                await context.bot.send_document(chat_id=update.effective_chat.id, document=db_file, filename="bot_database.db")
            if update.message:
                await update.message.reply_text("✅ Base de données sauvegardée avec succès.")
        elif update.message:
            await update.message.reply_text("❌ Base de données introuvable.")

    async def resetdb_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /resetdb command."""
        if update.message:
            await update.message.reply_text("⚠️ Suppression de la base de données SQLite en cours...")
        from core.database import reset_db
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, reset_db)
        if update.message:
            await update.message.reply_text("✅ La base de données a été réinitialisée à 0.")

    async def portfolio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /portfolio command."""
        import sys
        import os
        # Assurer l'accès à shared/ si non présent (bien que géré dans main_bot.py)
        if str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) not in sys.path:
            sys.path.append(str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            
        try:
            from shared.portfolio import Portfolio
            portfolio = Portfolio()
            balance = portfolio.get_balance()
            history = portfolio.get_history(limit=5)
            
            msg = f"💼 <b>Portefeuille (Simulé)</b>\n"
            msg += f"Solde Actuel : <b>{balance:.2f} U</b>\n\n"
            msg += "Derniers paris :\n"
            if not history:
                msg += "<i>Aucun pari enregistré.</i>"
            else:
                for row in history:
                    statut = "⏳" if row['status'] == "PENDING" else ("✅" if row['status'] == "WIN" else "❌")
                    msg += f"{statut} {row['date_bet']} | {row['sport'].upper()} | {row['player_name']} (@{row['odds']}) - {row['stake_u']}U\n"
        except ImportError as e:
            msg = f"❌ Erreur de chargement du module Portfolio : {e}"
            
        if update.message:
            await update.message.reply_text(msg, parse_mode="HTML")

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("force", force_cmd))
    app.add_handler(CommandHandler("roi", roi_cmd))
    app.add_handler(CallbackQueryHandler(roi_callback, pattern='^roi_'))
    app.add_handler(CommandHandler("backup", backup_cmd))
    app.add_handler(CommandHandler("resetdb", resetdb_cmd))
    app.add_handler(CommandHandler("portfolio", portfolio_cmd))

    async def job_scan_cycle(context: ContextTypes.DEFAULT_TYPE) -> None:
        """Periodic background job for scanning."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, nhl_bot.run_scan_cycle)

    async def job_end_of_day(context: ContextTypes.DEFAULT_TYPE) -> None:
        """Daily background job for cleanup."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, nhl_bot.end_of_day_cleanup)

    async def job_log_closing_lines(context: ContextTypes.DEFAULT_TYPE) -> None:
        """Tracks the closing lines (CLV) before evening matches start."""
        from core.updater import log_closing_lines
        await log_closing_lines()

    async def job_recalc_probas(context: ContextTypes.DEFAULT_TYPE) -> None:
        """Recalcule les probabilités de picks statiques tous les lundis matin."""
        import datetime as dt
        import subprocess
        import sys
        if dt.datetime.now(dt.timezone.utc).weekday() == 0:  # Lundi = 0
            logger.info("Lancement du script de recalcul des probabilités (Lundi).")
            try:
                subprocess.run([sys.executable, "scripts/recalc_probas.py"], check=False)
                nhl_bot.telegram.send_alert("✅ [Bilan Hebdo] Les probabilités bayésiennes du bot ont été recalculées automatiquement pour cette semaine.")
            except Exception as e:
                logger.error(f"Échec du recalcul des probabilités : {e}")

    app.job_queue.run_repeating(job_scan_cycle, interval=900, first=10)

    import datetime as dt
    # EOD Cleanup at 5:00 UTC (morning)
    target_time_eod = dt.time(hour=5, minute=0, tzinfo=dt.timezone.utc) 
    app.job_queue.run_daily(job_end_of_day, time=target_time_eod)
    
    # CLV Tracking around midnight UTC (before most matches)
    target_time_clv = dt.time(hour=23, minute=30, tzinfo=dt.timezone.utc)
    app.job_queue.run_daily(job_log_closing_lines, time=target_time_clv)

    # Recalcul hebdomadaire des probabilités à 6:00 UTC
    target_time_probas = dt.time(hour=6, minute=0, tzinfo=dt.timezone.utc)
    app.job_queue.run_daily(job_recalc_probas, time=target_time_probas)

    return app

class EmailReporter:
    """Service to handle sending the end-of-day stats report via email."""
    @staticmethod
    def send_session_report(log_path: str, players_log_path: str) -> None:
        """
        Sends session reports via email.

        Args:
            log_path: Path to the picks log CSV.
            players_log_path: Path to the all players log CSV.
        """
        logger.info("📧 Préparation de l'envoi du rapport par mail...")

        today_str = datetime.now().strftime('%Y-%m-%d')

        if not os.path.exists(log_path):
            logger.warning(f"Fichier {log_path} introuvable — rapport annulé.")
            return

        try:
            sender   = os.getenv("EMAIL_USER")
            password = os.getenv("EMAIL_PASS")
            receiver = os.getenv("EMAIL_RECEIVER")

            if not sender or not password or not receiver:
                logger.warning("Identifiants Email manquants dans le .env.")
                return

            msg = MIMEMultipart()
            msg['From']    = sender
            msg['To']      = receiver
            msg['Subject'] = f"🏒 Rapport NHL Session - {today_str}"

            body = (
                f"Bonjour,\n\n"
                f"Voici les fichiers de la session du {today_str} :\n"
                f"  • picks_{today_str}.csv   — joueurs sélectionnés (à compléter avec colonne 'but')\n"
                f"  • players_{today_str}.csv — tous les joueurs analysés (picks + non-picks)\n\n"
                f"Bonne analyse !"
            )
            msg.attach(MIMEText(body, 'plain'))

            def attach_file(filepath: str, filename: str) -> None:
                """Attaches a file to the email message."""
                with open(filepath, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f"attachment; filename={filename}")
                    msg.attach(part)

            attach_file(log_path, f"picks_{today_str}.csv")

            if os.path.exists(players_log_path):
                attach_file(players_log_path, f"players_{today_str}.csv")
            else:
                logger.warning("players_log.csv introuvable — envoyé sans ce fichier.")

            server = smtplib.SMTP('smtp.gmail.com', 587, timeout=15)
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
            server.quit()
            logger.info("✅ Mail envoyé avec succès (picks + players).")

        except Exception as e:
            logger.error(f"❌ Erreur lors du rapport de session : {e}")
