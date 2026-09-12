import os, glob, re  
for f in glob.glob('nhl/**/*.py', recursive=True):  
    with open(f, 'r', encoding='utf-8') as file: content = file.read()  
    content = re.sub(r'from core\.', 'from nhl.core.', content)  
    content = re.sub(r'from core import', 'from nhl.core import', content)  
    with open(f, 'w', encoding='utf-8') as file: file.write(content)  
