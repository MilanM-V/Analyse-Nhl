"""Diagnostic script: analyze missing odds patterns in the database."""
import sqlite3
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = "./bot_database.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    for table, label in [("picks", "BUTS"), ("picks_assists", "ASSISTS"), ("picks_points", "POINTS")]:
        c.execute(f"SELECT COUNT(*) as total, SUM(CASE WHEN cote IS NULL THEN 1 ELSE 0 END) as sans_cote FROM {table}")
        total, sans_cote = c.fetchone()
        sans_cote = sans_cote or 0
        pct = (100 * sans_cote / total) if total > 0 else 0
        print(f"\n{'='*50}")
        print(f"TABLE: {table} ({label})")
        print(f"Total: {total} | Sans cote: {sans_cote} ({pct:.1f}%)")
        print(f"{'='*50}")

        # Joueurs sans cote
        c.execute(f"""
            SELECT joueur, COUNT(*) as nb_total, 
                   SUM(CASE WHEN cote IS NULL THEN 1 ELSE 0 END) as nb_sans_cote 
            FROM {table} 
            GROUP BY joueur 
            HAVING nb_sans_cote > 0 
            ORDER BY nb_sans_cote DESC
            LIMIT 30
        """)
        rows = c.fetchall()
        if rows:
            print(f"\nJoueurs avec cotes manquantes:")
            for joueur, nb, sans in rows:
                print(f"  {joueur:30s} : {sans}/{nb} manquantes")
        else:
            print("  Aucun joueur sans cote.")

    # Analyse des noms de joueurs problématiques
    print(f"\n{'='*50}")
    print("ANALYSE DES PATTERNS DE NOMS PROBLEMATIQUES")
    print(f"{'='*50}")

    c.execute("""
        SELECT DISTINCT joueur FROM picks WHERE cote IS NULL
        UNION
        SELECT DISTINCT joueur FROM picks_assists WHERE cote IS NULL
        UNION
        SELECT DISTINCT joueur FROM picks_points WHERE cote IS NULL
    """)
    joueurs_sans_cote = [r[0] for r in c.fetchall()]

    # Check for patterns: accents, special chars, suffixes, etc.
    for j in sorted(joueurs_sans_cote):
        issues = []
        if any(ord(ch) > 127 for ch in j):
            issues.append("ACCENT/UNICODE")
        if "." in j:
            issues.append("POINT")
        if "'" in j:
            issues.append("APOSTROPHE")
        if "-" in j:
            issues.append("TIRET")
        parts = j.split()
        if len(parts) >= 3:
            issues.append("NOM_COMPOSE")
        if any(s in j for s in ["Jr", "Jr.", "II", "III", "IV"]):
            issues.append("SUFFIXE")
        tags = " | ".join(issues) if issues else "STANDARD"
        print(f"  {j:30s} -> [{tags}]")

    # Compare: joueurs AVEC cote vs SANS cote
    print(f"\n{'='*50}")
    print("JOUEURS TOUJOURS AVEC COTE (pour comparaison)")
    print(f"{'='*50}")
    c.execute("""
        SELECT DISTINCT joueur FROM picks WHERE cote IS NOT NULL
        EXCEPT
        SELECT DISTINCT joueur FROM picks WHERE cote IS NULL
    """)
    joueurs_avec = [r[0] for r in c.fetchall()]
    for j in sorted(joueurs_avec)[:20]:
        print(f"  {j}")
    print(f"  ... ({len(joueurs_avec)} joueurs au total)")

    # Analyse par date : évolution du taux de cotes manquantes
    print(f"\n{'='*50}")
    print("EVOLUTION PAR DATE (picks - Buts)")
    print(f"{'='*50}")
    c.execute("""
        SELECT date, COUNT(*) as total, 
               SUM(CASE WHEN cote IS NULL THEN 1 ELSE 0 END) as sans_cote 
        FROM picks 
        GROUP BY date 
        ORDER BY date DESC
        LIMIT 20
    """)
    for date, total, sans in c.fetchall():
        sans = sans or 0
        pct = (100 * sans / total) if total > 0 else 0
        bar = "#" * int(pct / 5)
        print(f"  {date} : {sans}/{total} ({pct:.0f}%) {bar}")

    # Test de slug conversion pour les joueurs problématiques
    print(f"\n{'='*50}")
    print("TEST SLUG CONVERSION (pour URL BettingPros)")
    print(f"{'='*50}")

    import unicodedata
    def normalize_name_for_url(name):
        if not name: return ""
        normalized = unicodedata.normalize('NFD', name)
        str_no_accents = "".join(c for c in normalized if not unicodedata.combining(c))
        str_no_accents = str_no_accents.lower().replace(".", "").replace("'", "")
        return str_no_accents.strip().replace(" ", "-")

    for j in sorted(joueurs_sans_cote):
        slug = normalize_name_for_url(j)
        url = f"https://www.bettingpros.com/nhl/odds/player-props/{slug}/"
        print(f"  {j:30s} -> {slug:30s}")

    conn.close()

if __name__ == "__main__":
    main()
