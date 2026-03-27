import os
import sys

# Move to root to import core modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from core.database import insert_pick, insert_player, init_db

def _clean_float(val):
    if pd.isna(val) or str(val).strip() == '':
        return 0.0
    if isinstance(val, str):
        val = val.replace(',', '.')
    try:
        return float(val)
    except:
        return 0.0

def _clean_bool(val):
    if pd.isna(val): return False
    return str(val).lower() in ['true', '1', 'oui', 'yes']

def _clean_int_nullable(val):
    if pd.isna(val) or str(val).strip() == '':
        return None
    try:
        return int(float(str(val).replace(',', '.')))
    except:
        return None

def migrate_csv(file_path, is_pick=True):
    if not os.path.exists(file_path):
        print(f"Skipping {file_path} - introuvable.")
        return

    print(f"Migration de {file_path} vers SQLite...")
    df = pd.read_csv(file_path, delimiter=',')
    
    # Check if comma or semicolon (sometimes Excel saves as semicolon)
    if len(df.columns) == 1:
        df = pd.read_csv(file_path, delimiter=';')

    for index, row in df.iterrows():
        try:
            # Shared parsing logic
            data = {
                'date': str(row.get('date', '')),
                'vague': str(row.get('vague', '')),
                'joueur': str(row.get('joueur', '')),
                'equipe': str(row.get('equipe', '')),
                'adversaire': str(row.get('adversaire', '')),
                'score': _clean_float(row.get('score', 0)),
                'pp1': _clean_bool(row.get('pp1', False)),
                'backup': _clean_bool(row.get('backup', False)),
                'b2b': _clean_bool(row.get('b2b', False)),
                'ixg': _clean_float(row.get('ixg', 0)),
                'hdcf': _clean_float(row.get('hdcf', 0)),
                'sog': _clean_float(row.get('sog', 0)),
                'atoi': _clean_float(row.get('atoi', 0)),
                'l10_g': _clean_float(row.get('l10_g', 0)),
                'season_g': _clean_float(row.get('season_g', 0)),
                'pdo': _clean_float(row.get('pdo', 100)),
                'ga_g': _clean_float(row.get('ga_g', 0)),
                'cf_pct': _clean_float(row.get('cf_pct', 50)),
                'hdca_g': _clean_float(row.get('hdca_g', 0)),
                'pk_pct': _clean_float(row.get('pk_pct', 80)),
                'rebounds': _clean_float(row.get('rebounds', 0)),
                'rush': _clean_float(row.get('rush', 0)),
                'but': _clean_int_nullable(row.get('but', None))
            }
            if is_pick:
                data['verdict'] = str(row.get('verdict', ''))
                insert_pick(data)
            else:
                data['picked'] = _clean_bool(row.get('picked', False))
                insert_player(data)

        except Exception as e:
            print(f"Erreur ligne {index}: {e}")
            
    print(f"Migration finale : {len(df)} lignes de {file_path}")

if __name__ == '__main__':
    init_db()
    migrate_csv('./stats/picks_log.csv', is_pick=True)
    migrate_csv('./stats/players_log.csv', is_pick=False)
    print("Migration terminée avec succès vers bot_database.db !")
