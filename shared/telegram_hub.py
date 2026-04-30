"""
shared/telegram_hub.py — Point unique d'envoi de messages Telegram.

Tous les bots sport utilisent ce module pour envoyer des messages.
Seul shared/telegram_commands.py utilise le polling (réception des commandes).

Usage:
    from shared.telegram_hub import send_telegram, send_crash_alert
    send_telegram("🏒 <b>Pick NHL</b> : McDavid @ 2.40")
"""

import os
import logging
import traceback
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("TelegramHub")


def send_telegram(
    message: str,
    parse_mode: str = "HTML",
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> bool:
    """Envoie un message Telegram via HTTP POST direct.

    Args:
        message: Le message à envoyer (HTML ou texte brut).
        parse_mode: Mode de parsing ('HTML' ou 'Markdown').
        token: Token du bot (par défaut: variable d'env TELEGRAM_TOKEN).
        chat_id: ID du chat (par défaut: variable d'env TELEGRAM_CHAT_ID).

    Returns:
        True si le message a été envoyé, False sinon.
    """
    token = token or os.getenv("TELEGRAM_TOKEN")
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id or token == "TELEGRAM_BOT_TOKEN":
        logger.warning("[TelegramHub] Token ou Chat ID manquant — message ignoré.")
        return False

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("[TelegramHub] Message envoyé avec succès.")
        return True
    except Exception as e:
        logger.error(f"[TelegramHub] Erreur d'envoi : {e}")
        return False


def send_crash_alert(
    error: Exception,
    context: str = "Bot Principal",
    sport: str = "",
) -> bool:
    """Envoie une alerte crash d'urgence via Telegram.

    Args:
        error: L'exception qui a causé le crash.
        context: Description de l'endroit du crash.
        sport: Nom du sport (pour identifier le bot).

    Returns:
        True si l'alerte a été envoyée, False sinon.
    """
    tb = traceback.format_exc()
    tb_short = tb[-500:] if len(tb) > 500 else tb
    sport_tag = f"[{sport.upper()}] " if sport else ""

    message = (
        f"🚨 <b>{sport_tag}CRASH — {context}</b>\n\n"
        f"<b>Erreur:</b> {type(error).__name__}: {error}\n\n"
        f"<pre>{tb_short}</pre>"
    )

    # POST direct sans retry pour maximiser la chance de livraison
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return False

    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        logger.info("🚨 Alerte crash envoyée sur Telegram.")
        return True
    except Exception as e:
        logger.error(f"Impossible d'envoyer l'alerte crash Telegram : {e}")
        return False
