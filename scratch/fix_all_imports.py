import os, glob, re  
for f in glob.glob('nhl/**/*.py', recursive=True):  
    with open(f, 'r', encoding='utf-8') as file: content = file.read()  
    content = re.sub(r'from config\.', 'from nhl.config.', content)  
    content = re.sub(r'from config import', 'from nhl.config import', content)  
    content = re.sub(r'from data\.', 'from nhl.data.', content)  
    content = re.sub(r'from data import', 'from nhl.data import', content)  
    content = re.sub(r'from models\.', 'from nhl.models.', content)  
    content = re.sub(r'from models import', 'from nhl.models import', content)  
    content = re.sub(r'from stats\.', 'from nhl.stats.', content)  
    content = re.sub(r'from stats import', 'from nhl.stats import', content)  
    with open(f, 'w', encoding='utf-8') as file: file.write(content)  
