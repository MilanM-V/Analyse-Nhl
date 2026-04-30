import pytest
import sqlite3
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import init_db, insert_pick, get_roi_stats, get_connection


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Crée une base de données SQLite temporaire pour les tests."""
    db_path = str(tmp_path / "test_bot.db")
    monkeypatch.setattr("core.database.DB_PATH", db_path)
    init_db()
    return db_path


class TestROIStatsWithCotes:
    """Vérifie que get_roi_stats utilise les cotes réelles."""

    def test_roi_with_real_cotes(self, test_db):
        """Win @3.0 + Loss → profit = (3.0-1) - 1 = +1.0 U."""
        conn = get_connection()
        insert_pick("picks", {
            "date": "2026-04-01", "vague": "01:00", "joueur": "McDavid",
            "equipe": "EDM", "adversaire": "CGY", "score": 11.0,
            "verdict": "ELITE", "but": 1, "cote": 3.0
        }, conn)
        insert_pick("picks", {
            "date": "2026-04-01", "vague": "01:00", "joueur": "Draisaitl",
            "equipe": "EDM", "adversaire": "CGY", "score": 10.0,
            "verdict": "ELITE", "but": 0, "cote": 2.5
        }, conn)
        conn.commit()
        conn.close()

        result = get_roi_stats("picks", "but")
        assert "+1.0 U" in result, f"Profit devrait être +1.0 U, got: {result}"

    def test_roi_missing_cotes_uses_mean(self, test_db):
        """Picks sans cote → utilise la moyenne des autres."""
        conn = get_connection()
        insert_pick("picks", {
            "date": "2026-04-01", "vague": "01:00", "joueur": "McDavid",
            "equipe": "EDM", "adversaire": "CGY", "score": 11.0,
            "verdict": "ELITE", "but": 1, "cote": 3.0
        }, conn)
        insert_pick("picks", {
            "date": "2026-04-01", "vague": "01:00", "joueur": "Hughes",
            "equipe": "NJD", "adversaire": "NYR", "score": 9.0,
            "verdict": "SAFE", "but": 1, "cote": None
        }, conn)
        conn.commit()
        conn.close()

        result = get_roi_stats("picks", "but")
        # Doit contenir "Cote moy" pour confirmer le fallback
        assert "Cote moy" in result

    def test_roi_no_data(self, test_db):
        """Pas de données → message explicite."""
        result = get_roi_stats("picks", "but")
        assert "Pas assez" in result

    def test_roi_shows_roi_percentage(self, test_db):
        """Le message doit contenir le ROI en pourcentage."""
        conn = get_connection()
        insert_pick("picks", {
            "date": "2026-04-01", "vague": "01:00", "joueur": "Test",
            "equipe": "EDM", "adversaire": "CGY", "score": 10.0,
            "verdict": "ELITE", "but": 1, "cote": 2.0
        }, conn)
        conn.commit()
        conn.close()

        result = get_roi_stats("picks", "but")
        assert "ROI" in result


class TestInsertPick:
    """Vérifie l'insertion et la lecture de picks."""

    def test_insert_and_read(self, test_db):
        """Insère un pick et vérifie qu'il est récupérable."""
        insert_pick("picks", {
            "date": "2026-04-01", "joueur": "Ovechkin",
            "equipe": "WSH", "score": 10.0, "verdict": "SAFE", "but": 1
        })
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT joueur FROM picks WHERE joueur = 'Ovechkin'")
        row = c.fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "Ovechkin"
