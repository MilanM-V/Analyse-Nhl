"""
vps/backup_manager.py — Gestionnaire de sauvegardes des bases de données.

Ce script crée une archive ZIP contenant les bases de données importantes
(NHL, MLB, Portfolio) et l'envoie par email via les identifiants du `.env`.
"""

import os
import zipfile
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("BackupManager")

load_dotenv()

# Liste des fichiers à sauvegarder (chemins relatifs par rapport à la racine du projet)
FILES_TO_BACKUP = [
    "nhl/data/bot_database.db",
    "mlb/data/dataset_strikeouts.csv",
    "shared/data/portfolio.db",
    "portfolio.db" # Au cas où il serait à la racine
]

def create_backup_zip() -> str:
    """Crée une archive ZIP avec les bases de données."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    zip_filename = f"backup_betengine_{date_str}.zip"
    
    logger.info(f"Création de l'archive {zip_filename}...")
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        added_files = 0
        for file_path in FILES_TO_BACKUP:
            if os.path.exists(file_path):
                # On ne garde que le nom du fichier dans l'archive pour que ce soit propre
                arcname = os.path.basename(file_path)
                zipf.write(file_path, arcname=arcname)
                logger.info(f" -> Ajouté : {file_path}")
                added_files += 1
            else:
                logger.warning(f"Fichier introuvable, ignoré : {file_path}")
                
    if added_files == 0:
        logger.error("Aucun fichier à sauvegarder !")
        os.remove(zip_filename)
        return ""
        
    return zip_filename

def send_backup_by_email(zip_filepath: str) -> bool:
    """Envoie l'archive par email."""
    if not zip_filepath or not os.path.exists(zip_filepath):
        return False
        
    sender = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASS")
    receiver = os.getenv("EMAIL_RECEIVER", sender) # Par défaut s'envoie à soi-même
    
    if not sender or not password:
        logger.error("Identifiants EMAIL_USER ou EMAIL_PASS manquants dans le .env !")
        return False
        
    logger.info("Envoi de l'archive par email...")
    
    try:
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = receiver
        msg['Subject'] = f"🛡️ Backup BetEngine - {datetime.now().strftime('%Y-%m-%d')}"
        
        body = "Bonjour,\n\nVoici la sauvegarde automatique quotidienne de vos bases de données NHL, MLB et Portfolio.\n\nCordialement,\nBetEngine VPS"
        msg.attach(MIMEText(body, 'plain'))
        
        # Attachement du fichier ZIP
        with open(zip_filepath, "rb") as attachment:
            part = MIMEBase("application", "zip")
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename= {os.path.basename(zip_filepath)}")
            msg.attach(part)
            
        # Connexion SMTP (Gmail par défaut)
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=20)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        
        logger.info("✅ Backup envoyé avec succès par email !")
        return True
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'envoi de l'email : {e}")
        return False

def run_backup():
    """Exécute la routine de backup complète."""
    logger.info("=== Début de la routine de Backup ===")
    
    zip_path = create_backup_zip()
    
    if zip_path:
        success = send_backup_by_email(zip_path)
        
        # Nettoyage
        try:
            os.remove(zip_path)
            logger.info(f"Archive locale {zip_path} supprimée.")
        except Exception as e:
            logger.warning(f"Impossible de supprimer l'archive locale : {e}")
            
    logger.info("=== Fin de la routine de Backup ===")

if __name__ == "__main__":
    # Permet de tester le script manuellement
    run_backup()
