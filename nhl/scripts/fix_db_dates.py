import sqlite3
import os

DB_PATH = "bot_database.db"

def fix_dates():
    if not os.path.exists(DB_PATH):
        print(f"Erreur : base de données {DB_PATH} introuvable.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Corriger les dates du 29/03 en 28/03 (Session NHL d'hier soir)
        print("Mise à jour des dates de '2026-03-29' vers '2026-03-28'...")
        
        cursor.execute("UPDATE picks SET date = '2026-03-28' WHERE date = '2026-03-29'")
        picks_count = cursor.rowcount
        
        cursor.execute("UPDATE players SET date = '2026-03-28' WHERE date = '2026-03-29'")
        players_count = cursor.rowcount
        
        conn.commit()
        print(f"Correction terminée : {picks_count} picks et {players_count} players mis à jour.")
        
    except Exception as e:
        conn.rollback()
        print(f"Erreur lors de la correction : {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    fix_dates()
