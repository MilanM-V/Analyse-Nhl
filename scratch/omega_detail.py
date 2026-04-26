"""Quick detailed analysis of the omega simulation results."""
import json
import os

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "omega_results.json"), 'r', encoding='utf-8') as f:
    data = json.load(f)

main = data['main']
test = data['test']

print("=" * 70)
print("DETAILED BREAKDOWN")
print("=" * 70)

print("\n--- MAIN (V9) ---")
print(f"  Picks: {main['total_picks']}, Won: {main['total_won']}")
print(f"  Total Mise: {main['total_mise']} U")
print(f"  Profit: {main['profit_u']} U, ROI: {main['roi_pct']}%")
print(f"  Winrate: {main['winrate']}%, Avg Cote: {main['avg_cote']}")
print(f"  Max Drawdown: {main['max_drawdown']} U")
print(f"  Max Win Streak: {main['max_win_streak']}, Max Loss Streak: {main['max_loss_streak']}")
print(f"  Sharpe (Daily): {main['sharpe_daily']}")

print("\n  Categories:")
for cat, m in main['categories'].items():
    print(f"    {cat}: {m['picks']} picks, WR {m['winrate']}%, Gain {m['gain']} U, ROI {m['roi']}%, Avg Cote {m['avg_cote']}")

print("\n--- TEST (V22 OMEGA) ---")
print(f"  Picks: {test['total_picks']}, Won: {test['total_won']}")
print(f"  Total Mise: {test['total_mise']} U")
print(f"  Profit: {test['profit_u']} U, ROI: {test['roi_pct']}%")
print(f"  Winrate: {test['winrate']}%, Avg Cote: {test['avg_cote']}")
print(f"  Max Drawdown: {test['max_drawdown']} U")
print(f"  Max Win Streak: {test['max_win_streak']}, Max Loss Streak: {test['max_loss_streak']}")
print(f"  Sharpe (Daily): {test['sharpe_daily']}")

print("\n  Categories:")
for cat, m in test['categories'].items():
    print(f"    {cat}: {m['picks']} picks, WR {m['winrate']}%, Gain {m['gain']} U, ROI {m['roi']}%, Avg Cote {m['avg_cote']}")

print("\n  Mode Split:")
for mode, m in test.get('mode_split', {}).items():
    print(f"    {mode}: {m['picks']} picks, WR {m['winrate']}%, Gain {m['gain']} U, ROI {m['roi']}%")

# Compare daily
print("\n--- DAILY COMPARISON ---")
print(f"{'Date':<12} | {'V9 Gain':>8} | {'V9 Cumul':>8} | {'V22 Gain':>8} | {'V22 Cumul':>8} | {'Winner':>8}")
print("-" * 70)
all_dates = sorted(set(list(main['daily'].keys()) + list(test['daily'].keys())))
for d in all_dates:
    m = main['daily'].get(d, {})
    t = test['daily'].get(d, {})
    mg = m.get('gain', 0)
    mc = m.get('cumul', 0)
    tg = t.get('gain', 0)
    tc = t.get('cumul', 0)
    winner = "V9" if mg > tg else ("V22" if tg > mg else "TIE")
    print(f"{d:<12} | {mg:>+8.1f} | {mc:>+8.1f} | {tg:>+8.1f} | {tc:>+8.1f} | {winner:>8}")

# Check V22 test results detail
print("\n--- V22 SAMPLE PICKS ---")
test_results = data['test_results']
for r in test_results[:20]:
    print(f"  {r['date']} {r['joueur']:<25} {r['categorie']:<10} cote={r['cote']:<5} mise={r['mise']:<4} gain={r['gain']:>+6.1f} {'WIN' if r['won'] else 'LOSS'}")
