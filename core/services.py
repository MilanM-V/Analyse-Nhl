import os
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import logging
from datetime import datetime

logger = logging.getLogger("NHL_Bot")

from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import asyncio

class TelegramNotifier:
    """Service to handle Telegram notifications via python-telegram-bot."""
    def __init__(self):
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if self.token == "TELEGRAM_BOT_TOKEN" or not self.token:
            logger.warning("[TelegramNotifier] Token non valide ou manquant.")
            self.enabled = False
        else:
            self.enabled = True

        self.bot = Bot(token=self.token) if self.enabled else None

    def send_message(self, message):
        """Sends an HTML formatted message synchronously using the underlying bot."""
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
            requests.post(url, json=payload, timeout=10)
            logger.info("Alerte Telegram envoyée avec succès !")
        except Exception as e:
            logger.error(f"Exception lors de l'envoi Telegram : {e}")

def create_telegram_app(nhl_bot):
    """Factory to create the interactive telegram application with handlers."""
    token = os.getenv("TELEGRAM_TOKEN")
    if not token or token == "TELEGRAM_BOT_TOKEN":
        return None

    app = ApplicationBuilder().token(token).build()

    async def start_cmd(update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🏒 NHL Bot V12 Actif ! Commandes:\n/status - État du bot\n/roi - Statistiques SQLite\n/force - Lancer un scan\n/odds - Usage API cotes")

    async def status_cmd(update, context: ContextTypes.DEFAULT_TYPE):
        n_match = len(nhl_bot.matchs_traites)

        compo_en_attente = 0
        for match_id, data in nhl_bot.compos_en_memoire.items():
            time_str = data["match_info"]["time"]
            if time_str not in nhl_bot.vagues_envoyees:
                compo_en_attente += 1

        await update.message.reply_text(f"📊 Status:\nMatchs du jour (Flashscore): {n_match}\nCompos en attente de vague: {compo_en_attente}")

    async def force_cmd(update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("⚡ Forçage du scan en cours (les logs vont s'afficher sur le serveur)...")

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, nhl_bot.run_scan_cycle)
        await update.message.reply_text("✅ Fin du scan forcé.")

    async def roi_cmd(update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("⏳ Mise à jour de la base de données... Validation API en cours.")

        from core.updater import update_pending_picks
        loop = asyncio.get_running_loop()
        n_resolved = await loop.run_in_executor(None, update_pending_picks)

        if n_resolved > 0:
            await update.message.reply_text(f"✅ {n_resolved} résultat(s) récupéré(s) de la veille !")

        from core.database import get_roi_stats
        stats = get_roi_stats()
        await update.message.reply_text(f"💰 **ROI ACTUEL** :\n\n{stats}", parse_mode="HTML")

    async def odds_cmd(update, context: ContextTypes.DEFAULT_TYPE):
        from core.odds_api import get_api_usage
        usage = get_api_usage()
        await update.message.reply_text(f"📊 Odds API :\n{usage}")

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("force", force_cmd))
    app.add_handler(CommandHandler("roi", roi_cmd))
    app.add_handler(CommandHandler("odds", odds_cmd))

    async def job_scan_cycle(context: ContextTypes.DEFAULT_TYPE):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, nhl_bot.run_scan_cycle)

    async def job_end_of_day(context: ContextTypes.DEFAULT_TYPE):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, nhl_bot.end_of_day_cleanup)

    app.job_queue.run_repeating(job_scan_cycle, interval=900, first=900)

    import datetime as dt
    target_time = dt.time(hour=5, minute=0, tzinfo=dt.timezone.utc) 
    app.job_queue.run_daily(job_end_of_day, time=target_time)

    return app

class EmailReporter:
    """Service to handle sending the end-of-day stats report via email."""
    @staticmethod
    def send_session_report(log_path, players_log_path):
        """Envoie picks_log.csv + players_log.csv par mail puis les archive."""
        logger.info("📧 Préparation de l'envoi du rapport par mail...")

        today_str = datetime.now().strftime('%Y-%m-%d')
        archive_picks = f"./stats/archive_picks_{today_str}.csv"
        archive_players = f"./stats/archive_players_{today_str}.csv"

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

            def attach_file(filepath, filename):
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
        finally:
            if os.path.exists(log_path):
                os.rename(log_path, archive_picks)
                logger.info(f"📁 picks archivé : {archive_picks}")
            if os.path.exists(players_log_path):
                os.rename(players_log_path, archive_players)
                logger.info(f"📁 players archivé : {archive_players}")
