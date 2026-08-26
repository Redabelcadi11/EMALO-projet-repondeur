import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import extraire_informations as ext

clients = ext.charger_clients()
cad = ext.charger_cadencier()
target_codes = {'royalbtz', 'royaltybtz', 'barcru', 'casajuanpedro', 'biarritzsolbab', 'saintjea'}
for c in clients:
    code = str(c.get('code_client', '')).lower()
    if code in target_codes or any(t in code for t in target_codes):
        print(f"Code: {c['code_client']}, Nom: {c.get('nom_client')}, Ville: {c.get('ville')}, Tel: {c.get('telephones')}, Cad len: {len(cad.get(c['code_client'], []))}")
