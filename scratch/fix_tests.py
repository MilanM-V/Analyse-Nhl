import os, glob

for f in glob.glob('nhl/tests/*.py'):
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Fix import path
    content = content.replace('sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))', 
                              'sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))')
    
    # Fix assertions in test_bot_logic
    if 'test_bot_logic.py' in f:
        content = content.replace('assert NhlBot.CATEGORY_CAPS["BUTEUR"] == 3.0', 'assert NhlBot.CATEGORY_CAPS["BUTEUR"] == 1.5')
        content = content.replace('BUTEUR plafonné à 3.0 U.', 'BUTEUR plafonné à 1.5 U.')
        content = content.replace('assert units <= 3.0, f"BUTEUR ne doit JAMAIS dépasser 3.0 U, got {units}"', 'assert units <= 1.5, f"BUTEUR ne doit JAMAIS dépasser 1.5 U, got {units}"')
    
    with open(f, 'w', encoding='utf-8') as file:
        file.write(content)
