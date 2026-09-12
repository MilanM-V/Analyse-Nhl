"""
core/formatter.py — Formatage des messages Telegram et construction des combinés.

Extrait de bot_logic.py pour réutilisation et tests indépendants.
"""
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

import nhl.core.loaders as loaders
from nhl.core.database import insert_parlay

from nhl.config.settings import cfg

logger = logging.getLogger("NHL.Formatter")


def find_cross_duo(list1: List[Dict], list2: List[Dict]) -> Optional[Tuple[Dict, Dict]]:
    """Trouve une paire de picks venant de matchs différents.

    Args:
        list1: Premier pool de picks triés par EV.
        list2: Second pool de picks triés par EV.

    Returns:
        Tuple de deux picks de matchs différents, ou None.
    """
    for p1 in list1:
        g1 = {p1['Equipe'], p1.get('Adversaire', '')}
        for p2 in list2:
            if p1['Joueur'] == p2['Joueur']:
                continue
            g2 = {p2['Equipe'], p2.get('Adversaire', '')}
            if not g1.intersection(g2):
                return (p1, p2)
    return None


def get_best_per_match(picks_list: List[Dict]) -> List[Dict]:
    """Retourne le meilleur pick par match (meilleur EV).

    Args:
        picks_list: Liste de picks avec 'Cote', 'Proba', 'Equipe', 'Adversaire'.

    Returns:
        Liste du meilleur pick de chaque match.
    """
    best: Dict[str, Dict] = {}
    for p in picks_list:
        if p.get('Cote') and p['Cote'] > 1.05:
            m_key = f"{p['Equipe']}-{p.get('Adversaire', '')}"
            if m_key not in best or (p.get('Proba', 0) * p['Cote']) > (best[m_key].get('Proba', 0) * best[m_key].get('Cote', 1)):
                best[m_key] = p
    return list(best.values())


def format_telegram_v18(
    buts: List[Dict[str, Any]],
    assists: List[Dict[str, Any]],
    points: List[Dict[str, Any]],
    wave_label: str,
    wave_ids: List[str],
    compos_en_memoire: Dict[str, Dict[str, Any]],
) -> str:
    """Formate le message Telegram V18.3 complet (singles + combinés).

    Args:
        buts: Picks buteurs filtrés et enrichis.
        assists: Picks passeurs filtrés et enrichis.
        points: Picks pointeurs filtrés et enrichis.
        wave_label: Label de la vague (horaire).
        wave_ids: IDs des matchs de la vague.
        compos_en_memoire: Compos en mémoire du bot.

    Returns:
        Message HTML formaté pour Telegram.
    """
    if cfg.api.mode == "playoff":
        msg = f"<b>\U0001f3c6 NHL PLAYOFF V18.3 \u2014 VAGUE {wave_label}</b>\n\n"
    else:
        msg = f"<b>\U0001f3d2 NHL V18.3 \u2014 VAGUE {wave_label}</b>\n\n"

    for mid in wave_ids:
        data = compos_en_memoire.get(mid)
        if not data:
            continue

        m = data["match_info"]
        t1_full = loaders.REVERSE_TEAM_MAPPING.get(m['home'], m['home'])
        t2_full = loaders.REVERSE_TEAM_MAPPING.get(m['away'], m['away'])

        h_abbr = loaders.TEAM_MAPPING.get(m['home'], m['home'])
        a_abbr = loaders.TEAM_MAPPING.get(m['away'], m['away'])

        msg += f"<b>Match {t1_full} vs {t2_full} :</b>\n"

        for emoji, label, picks_list in [
            ("\U0001f525", "Buteurs", buts), ("\U0001f170\ufe0f", "Passeurs", assists),
            ("\U0001f3c6", "Pointeurs", points)
        ]:
            m_picks = [r for r in picks_list if r['Equipe'] in (h_abbr, a_abbr)]
            m_picks.sort(key=lambda x: (x.get('Proba', 0) * (x.get('Cote') or 0)) - 1.0, reverse=True)
            if m_picks:
                msg += f"  {emoji} <i>{label} :</i>\n"
                for r in m_picks:
                    home_icon = '\U0001f3e0' if r['IsHome'] else '\u2708\ufe0f'
                    cote_str = f" @{r['Cote']:.2f} chez {r.get('Bookmaker', 'Inconnu')} | Edge: {((r.get('Proba', 0) * (r.get('Cote', 1) or 1)) - 1)*100:.1f}% | Mise: {r.get('Mise', '1 U')}" if r.get('Cote') else ""
                    msg += f"  \u2022 {home_icon} <b>{r['Joueur']}</b>{cote_str}\n"

        m_all = [r for picks_list in [buts, assists, points]
                 for r in picks_list if r['Equipe'] in (h_abbr, a_abbr)]
        if not m_all:
            msg += "  <i>\u26a0\ufe0f Aucun pick sur ce match.</i>\n"
        msg += "\n"

    # --- COMBINÉS INTELLIGENTS (V18.3) ---
    msg += _build_parlays_section(buts, assists, points, wave_label)

    return msg


def _build_parlays_section(
    buts: List[Dict], assists: List[Dict], points: List[Dict], wave_label: str
) -> str:
    """Construit la section combinés du message Telegram et insère en DB.

    Utilise parlay_engine pour générer :
    1. INTRA-MATCH Synergique (Passeur + Buteur PP1).
    2. INTER-MATCH Sécurisé (Double Passeurs sur matchs distincts).
    """
    from nhl.core.parlay_engine import generate_correlated_parlays, generate_dual_assist_parlays

    msg = ""
    today_str = datetime.now().strftime("%Y-%m-%d")

    def _add_combo(p1_name: str, p1_cote: float, p2_name: str, p2_cote: float, 
                   label: str, emoji: str, type_combo: str, mise: float, cote_combo: float, ev: float) -> str:
        s = f"<b>{emoji} {label} :</b>\n"
        s += f"  • {p1_name} @{p1_cote:.2f}\n"
        s += f"  • {p2_name} @{p2_cote:.2f}\n"
        s += f"  => <b>Cote Combo : @{cote_combo:.2f}</b> | EV: +{ev*100:.1f}% | Mise: {mise} U\n\n"
        insert_parlay({
            "date": today_str, "vague": wave_label, "type_combo": type_combo,
            "leg1_joueur": p1_name, "leg2_joueur": p2_name,
            "leg3_joueur": None,
            "cote_totale": cote_combo, "mise": mise
        })
        return s

    parlays_added = 0

    all_parlays = []

    # 1. INTRA-MATCH : Synergie Passeur + Buteur (Winamax MyMatch)
    sg_parlays = generate_correlated_parlays(buts, assists, min_combined_ev=0.15)
    for p in sg_parlays:
        p['_label'] = f"WINAMAX MYMATCH — Synergie {p['equipe']} ({p['note']})"
        p['_emoji'] = "🔥"
        all_parlays.append(p)

    # 2. INTER-MATCH : Double Passeurs (Winamax Combiné Sécurisé)
    cross_parlays = generate_dual_assist_parlays(assists, min_combined_ev=0.15)
    for p in cross_parlays:
        p['_label'] = "WINAMAX COMBINÉ — Double Passeurs Élite"
        p['_emoji'] = "🅰️"
        all_parlays.append(p)

    all_parlays.sort(key=lambda x: x['ev'], reverse=True)

    if all_parlays:
        best_p = all_parlays[0]
        msg += _add_combo(
            best_p["leg1_joueur"], best_p["leg1_cote"], best_p["leg2_joueur"], best_p["leg2_cote"],
            best_p['_label'], best_p['_emoji'], best_p["type"], best_p["mise"], best_p["cote_totale"], best_p["ev"]
        )
        parlays_added += 1

    if parlays_added == 0:
        msg += "  <i>Aucun combiné EV+ possible pour cette vague.</i>\n"

    return msg
