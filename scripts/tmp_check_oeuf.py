import sys, os, json
sys.path.insert(0, '.')
os.environ.setdefault('PYTHONDONTWRITEBYTECODE', '1')
from pathlib import Path
from src.runtime_paths import bootstrap_runtime_environment
bootstrap_runtime_environment()
from extraire_informations import charger_cadencier

cadencier = charger_cadencier()
for client_code, produits in cadencier.items():
    for p in produits:
        code = str(p.get('code_article','')).upper()
        lib = str(p.get('libelle_article',''))
        if '00406100' in code or ('oeuf' in lib.lower() and 'arradoy' in lib.lower()):
            print(f"Client: {client_code} | code: {code} | lib: {lib}")
            syns = p.get('synonymes', [])
            print(f"  Synonymes: {syns}")
            print(f"  Quantite habituelle: {p.get('quantite_habituelle')}")
            print()
