import re

file_path = 'nhl/core/formatter.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace format_telegram_v18
new_format = '''def format_telegram_v18(
    buts: List[Dict[str, Any]],
    assists: List[Dict[str, Any]],
    points: List[Dict[str, Any]],
    wave_label: str,
    wave_ids: List[str],
    compos_en_memoire: Dict[str, Dict[str, Any]],
) -> str:
    \"\"\"Formate le message Telegram complet (singles + combinés).\"\"\"
    if cfg.api.mode == "playoff":
        msg = f"<b>🏆 NHL PLAYOFF V19 (ML) — VAGUE {wave_label}</b>\\n\\n"
    else:
        msg = f"<b>🏒 NHL V19 (ML) — VAGUE {wave_label}</b>\\n\\n"

    for mid in wave_ids:
        data = compos_en_memoire.get(mid)
        if not data:
            continue

        m = data["match_info"]
        t1_full = loaders.REVERSE_TEAM_MAPPING.get(m['home'], m['home'])
        t2_full = loaders.REVERSE_TEAM_MAPPING.get(m['away'], m['away'])

        h_abbr = loaders.TEAM_MAPPING.get(m['home'], m['home'])
        a_abbr = loaders.TEAM_MAPPING.get(m['away'], m['away'])

        msg += f"<b>Match {t1_full} vs {t2_full} :</b>\\n"

        for emoji, label, picks_list in [
            ("🔥", "Buteurs (XGBoost)", buts), 
            ("🅰️", "Passeurs (RegLog)", assists)
        ]:
            m_picks = [r for r in picks_list if r['Equipe'] in (h_abbr, a_abbr)]
            m_picks.sort(key=lambda x: (x.get('Proba', 0) * (x.get('Cote') or 0)) - 1.0, reverse=True)
            if m_picks:
                msg += f"  {emoji} <i>{label} :</i>\\n"
                for r in m_picks:
                    home_icon = '🏠' if r['IsHome'] else '✈️'
                    cote_str = f" @{r['Cote']:.2f} chez {r.get('Bookmaker', 'Inconnu')} | Proba IA: {r.get('Proba', 0)*100:.1f}% | Edge: {((r.get('Proba', 0) * (r.get('Cote', 1) or 1)) - 1)*100:.1f}% | Mise: {r.get('Mise', '1 U')}" if r.get('Cote') else ""
                    msg += f"  • {home_icon} <b>{r['Joueur']}</b>{cote_str}\\n"

        m_all = [r for picks_list in [buts, assists]
                 for r in picks_list if r['Equipe'] in (h_abbr, a_abbr)]
        if not m_all:
            msg += "  <i>⚠️ Aucun value bet IA sur ce match.</i>\\n"
        msg += "\\n"

    # --- COMBINÉS INTELLIGENTS (V19) ---
    msg += _build_parlays_section(buts, assists, points, wave_label)

    return msg
'''
content = re.sub(r'def format_telegram_v18\(.*?return msg\n', new_format, content, flags=re.DOTALL)

# Replace _build_parlays_section
new_parlay = '''def _build_parlays_section(
    buts: List[Dict], assists: List[Dict], points: List[Dict], wave_label: str
) -> str:
    \"\"\"Construit la section combinés du message Telegram et insère en DB.\"\"\"
    msg = ""
    today_str = datetime.now().strftime("%Y-%m-%d")

    best_ast = get_best_per_match(assists)
    # Tri par Edge décroissant
    best_ast.sort(key=lambda x: -((x.get('Proba', 0) * x.get('Cote', 1)) - 1.0))

    def _add_combo(p1: Dict, p2: Dict, label: str, emoji: str, type_combo: str, mise: float) -> str:
        cote_combo = round(p1['Cote'] * p2['Cote'], 2)
        s = f"<b>{emoji} {label} :</b>\\n"
        s += f"  • {p1['Joueur']} @{p1['Cote']} (Proba {p1.get('Proba',0)*100:.1f}%)\\n"
        s += f"  • {p2['Joueur']} @{p2['Cote']} (Proba {p2.get('Proba',0)*100:.1f}%)\\n"
        s += f"  => <b>Cote Combo : @{cote_combo}</b> | Mise: {mise} U\\n\\n"
        insert_parlay({
            "date": today_str, "vague": wave_label, "type_combo": type_combo,
            "leg1_joueur": p1['Joueur'], "leg2_joueur": p2['Joueur'],
            "leg3_joueur": None,
            "cote_totale": cote_combo, "mise": mise
        })
        return s

    parlays_added = 0
    used_players = set()
    
    msg += "<b>💰 COMBINÉS IA RECOMMANDÉS :</b>\\n"

    # On essaie de créer jusqu'à 3 combinés "Double Passeurs" (les plus rentables)
    for i, a1 in enumerate(best_ast):
        if parlays_added >= 3:
            break
        if a1['Joueur'] in used_players:
            continue
            
        # Trouver un partenaire dans un autre match
        g1 = {a1['Equipe'], a1.get('Adversaire', '')}
        for j in range(i + 1, len(best_ast)):
            a2 = best_ast[j]
            if a2['Joueur'] in used_players:
                continue
                
            g2 = {a2['Equipe'], a2.get('Adversaire', '')}
            if not g1.intersection(g2):
                msg += _add_combo(a1, a2, f"Double Passeurs IA #{parlays_added+1}", "🅰️", "INTER_DOUBLE_AST", 0.5)
                used_players.add(a1['Joueur'])
                used_players.add(a2['Joueur'])
                parlays_added += 1
                break

    if parlays_added == 0:
        msg += "  <i>Aucun combiné EV+ possible (pas assez de matchs ou passeurs).</i>\\n"

    return msg
'''
content = re.sub(r'def _build_parlays_section\(.*?return msg\n', new_parlay, content, flags=re.DOTALL)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Formatter patched.")
