import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
import core.predictor_v12 as predictor
from core.datastore import DataStore

def main():
    print("Chargement des données via DataStore...")
    ds = DataStore()
    ds.force_refresh()
    
    fichier_compos = os.path.join(os.path.dirname(__file__), "temp_compos.txt")
    
    matches_soir, compos_brutes, goalies = predictor.parse_flashscore_file(
        fichier_compos, ds.known_players, ds.form_data
    )
    
    print(f"Matchs identifiés : {matches_soir}")
    
    compos_filtrees = [p for p in compos_brutes if p in ds.form_data]
    home_teams = [m[0] for m in matches_soir]
    opponents = {t1: t2 for t1, t2 in matches_soir}
    opponents.update({t2: t1 for t1, t2 in matches_soir})
    
    TODAY = datetime.now().strftime("%Y-%m-%d")
    b2b_teams = [t for t in predictor.get_b2b_teams('./stats/match.csv', TODAY) if t in opponents]
    pp1_players = predictor.get_auto_pp1_players(ds.form_data, ds.pp_stats, opponents.keys())

    results = []
    for player in compos_filtrees:
        p_form = ds.form_data[player]
        team = predictor.clean_team_name(p_form['Team'])
        if p_form['ATOI'] < 13.0 or team not in opponents: continue

        adv = opponents[team]
        adv_stats = ds.matchups.get(adv)
        is_backup = predictor.check_if_backup_goalie(goalies.get(adv, ""), ds.goalie_stats)

        qs = predictor.calculate_base_qs(
            ds.v5_data.get(player, {}), p_form, adv_stats,
            player in pp1_players, team in home_teams,
            False, is_backup, team in b2b_teams and adv not in b2b_teams
        )

        
        if qs >= 0:
            hdcf = round(p_form.get('L10_iHDCF_G', 0), 2)
            
            # Seuils calibrés sur 20 000 matchs (backtest V3)
            cat = None
            if qs >= 11.5: cat = "ELITE"   # 41.6% WR
            elif qs >= 10.5: cat = "SAFE"  # 35.1% WR
            
            results.append({
                "Joueur": player, "Equipe": team, "Adversaire": adv, "IsHome": team in home_teams,
                "Score": round(qs, 1), "hdcf": hdcf, "Categorie": cat, "PP1": "⭐" if player in pp1_players else ""
            })

    final_picks = [r for r in sorted(results, key=lambda x: x["Score"], reverse=True) if r["Categorie"]]
    
    print(f"\n--- NHL V12.9 CALIBRÉ — {len(final_picks)} picks ---")
    for r in final_picks:
        side = "🏠" if r['IsHome'] else "✈️"
        icon = "🚀" if r['Categorie'] == "ELITE" else "✅"
        print(f"{side} {r['Equipe']} | {r['Joueur']} : {icon} {r['Categorie']} (Score: {float(r['Score']):.1f} / HDCF: {float(r['hdcf']):.2f}) {r['PP1']}")
        
    if not final_picks:
        print("Aucun pick n'a passé les filtres calibrés.")

if __name__ == '__main__':
    main()
