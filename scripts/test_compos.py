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

    # --- Index des lignes pour la synergie ---
    lines_index = {}
    try:
        with open(fichier_compos, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith(('f1 ', 'f2 ')):
                    players_on_line = [p.strip() for p in line.split(':', 1)[1].split(',') if p.strip()]
                    for p in players_on_line:
                        lines_index.setdefault(p, set()).update(players_on_line)
    except Exception:
        pass

    # --- Passe 1 : scores bruts ---
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

        sog_score = predictor.calculate_sog_score(
            p_form, adv_stats, player in pp1_players, team in home_teams
        )

        if qs >= 0 or sog_score >= 0:
            hdcf = round(p_form.get('L10_iHDCF_G', 0), 2)
            pos = p_form.get('pos', ds.v5_data.get(player, {}).get('Position', ''))
            
            xgb_proba = predictor.evaluate_xgb_proba(
                ds.v5_data.get(player, {}), p_form, adv_stats,
                team in home_teams, team in b2b_teams, adv in b2b_teams, 
                player in pp1_players, qs
            )

            xgb_sog_proba = predictor.evaluate_sog_proba(
                p_form, adv_stats, player in pp1_players, team in home_teams, sog_score
            )
            
            results.append({
                "Joueur": player, "Equipe": team, "Adversaire": adv, "IsHome": team in home_teams,
                "Score": round(qs, 1), "hdcf": hdcf, 
                "Proba": xgb_proba, "Pos": pos,
                "SogScore": round(sog_score, 1), "ProbaSog": xgb_sog_proba,
                "Categorie": None, "PP1": "⭐" if player in pp1_players else ""
            })

    # --- Passe 2 : synergie + catégories V13.1 ---
    elite_players = {r["Joueur"] for r in results if r["Score"] >= 11.5 and r["Proba"] >= 0.50}
    
    for r in results:
        linemates = lines_index.get(r["Joueur"], set())
        has_elite_linemate = bool(linemates & elite_players - {r["Joueur"]})
        if has_elite_linemate:
            r["Score"] = round(r["Score"] + 0.3, 1)
            r["Synergie"] = True
        else:
            r["Synergie"] = False
        
        pos = r["Pos"]
        qs, proba = r["Score"], r["Proba"]
        sog_score, proba_sog = r["SogScore"], r["ProbaSog"]

        cat = None
        if pos in ('D', 'LD', 'RD'):
            if qs >= 9.5 and proba >= 0.35: cat = "DÉFENSEUR"
        else:
            if qs >= 11.5 and proba >= 0.50: cat = "ELITE"
            elif qs >= 10.5 and proba >= 0.55: cat = "SAFE"
        
        # Sur-couche SOG : si le joueur n'est ni Elite ni Safe mais a un fort SOG
        if not cat and sog_score >= 8.0 and proba_sog >= 0.55:
            cat = "TIREUR"
        
        r["Categorie"] = cat

    final_picks = [r for r in sorted(results, key=lambda x: x["Score"], reverse=True) if r["Categorie"]]
    
    print(f"\n--- NHL V13.1 PROD — {len(final_picks)} picks ---")
    for r in final_picks:
        side = "🏠" if r['IsHome'] else "✈️"
        # Display logic: icon + stats
        cat = r['Categorie']
        icon = "🚀" if cat == "ELITE" else ("🛡️" if cat == "DÉFENSEUR" else ("🎯" if cat == "TIREUR" else "✅"))
        syn = " 🔗" if r.get('Synergie') else ""
        
        stat_str = f"QS: {float(r['Score']):.1f} / P: {(r['Proba']*100):.1f}%"
        if cat == "TIREUR":
            stat_str = f"SOG: {float(r['SogScore']):.1f} / P: {(r['ProbaSog']*100):.1f}%"
            
        print(f"{side} {r['Equipe']} | {r['Joueur']} : {icon} {cat} ({stat_str}){syn} {r['PP1']}")
        
    if not final_picks:
        print("Aucun pick n'a passé les filtres calibrés.")

if __name__ == '__main__':
    main()
