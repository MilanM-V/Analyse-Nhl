"""
Shim de compatibilité — Délègue directement à data/fetcher.py
Fichier réduit de 710 lignes à 5 lignes suite au refactoring (Audit).
"""
import sys

from data.fetcher import update_all_stats_sync

if __name__ == "__main__":
    update_all_stats_sync()
