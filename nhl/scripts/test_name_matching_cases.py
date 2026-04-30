from core.updater import match_player_name

def test_matching():
    test_cases = [
        ("Alexis Lafrenière", "A. Lafreniere", True),
        ("Alexis Lafrenière", "Alexis Lafreniere", True),
        ("Alex Ovechkin", "Alexander Ovechkin", True),
        ("Mitch Marner", "M. Marner", True),
        ("Mitch Marner", "Mitchell Marner", True),
        ("Tim Stützle", "T. Stutzle", True),
        ("Nico Hischier", "N. Hischier", True),
        ("Nico Hischier", "Nico Hisciser", False), # Typo trop importante si pas de fuzzy
        ("Andrei Svechnikov", "A. Svechnikov", True),
        ("Evgeny Svechnikov", "A. Svechnikov", False),
    ]

    print(f"{'DB Name':<20} | {'API Name':<20} | {'Expected':<8} | {'Result':<8}")
    print("-" * 65)
    
    passed = 0
    for db, api, expected in test_cases:
        result = match_player_name(db, api)
        status = "PASS" if result == expected else "FAIL"
        if status == "PASS": passed += 1
        print(f"{db:<20} | {api:<20} | {str(expected):<8} | {str(result):<8} | {status}")

    print("-" * 65)
    print(f"Passed {passed}/{len(test_cases)} tests.")

if __name__ == "__main__":
    test_matching()
