import json, csv, pathlib, re
from datetime import date, timedelta

EXTRACTIONS = pathlib.Path('resultats/extractions')
REPLAY = pathlib.Path('resultats/copilote-replay')
PHONES_CONFIG = pathlib.Path('config/telephones-clients.json')

import sys
sys.path.insert(0, str(pathlib.Path('.').resolve()))
from src.runtime_paths import bootstrap_runtime_environment
bootstrap_runtime_environment()
from src.clients import charger_telephones_clients

# Load phone -> client using project's helper
# Returns {client_code: [normalized_phones]}
phones = {}  # phone -> client_code
raw_phones = charger_telephones_clients(PHONES_CONFIG)
for client_code, phone_list in raw_phones.items():
    for ph in phone_list:
        phones[ph.strip()] = client_code

# Load ES truth
truth = {}
for csv_path in list(REPLAY.glob('commandes_ES_*.csv')) + list(REPLAY.glob('historique_es_pretest_*.csv')):
    with open(csv_path, encoding='utf-8') as f:
        for row in csv.DictReader(f, delimiter=';'):
            cl = row.get('client_code','').strip()
            od = str(row.get('order_date','')).strip()[:10]
            co = row.get('article_code','').strip()
            dg = row.get('designation','').strip()
            if cl and od and co:
                truth.setdefault((cl, od), {})[co] = dg

print(f"ES truth: {sum(len(v) for v in truth.values())} articles pour {len(truth)} commandes")
print(f"Phones: {len(phones)} clients")

bon, mauvais = [], []
for f in EXTRACTIONS.glob('*.json'):
    m = re.match(r'(\d{4}-\d{2}-\d{2})_\d{2}-\d{2}-\d{2}_De-(\d+)', f.name)
    if not m:
        continue
    audio_date, phone = m.group(1), m.group(2)
    client = phones.get(phone, '')
    if not client:
        continue
    d = date.fromisoformat(audio_date)
    es = {}
    for delta in [0, 1, -1, 2]:
        es.update(truth.get((client, (d+timedelta(days=delta)).isoformat()), {}))
    if not es:
        continue
    data = json.loads(f.read_text(encoding='utf-8'))
    for p in data.get('produits', []):
        for c in p.get('candidats', []):
            if not c.get('llm_arbitrage'):
                continue
            code = c.get('code_article','')
            libelle = c.get('libelle', c.get('libelle_normalise',''))
            texte = p.get('texte_source','')
            if code in es:
                bon.append({'dit': texte, 'code': code, 'libelle': libelle, 'es': es[code]})
            else:
                mauvais.append({'dit': texte, 'code': code, 'libelle': libelle, 'es_sample': list(es.values())[:3]})

total = len(bon) + len(mauvais)
print(f"\n=== VERIFICATION LLM vs COMMANDES REELLES ===")
print(f"Resolutions LLM verifiables: {total}")
print(f"CORRECT : {len(bon)}")
print(f"INCORRECT: {len(mauvais)}")
print(f"PRECISION LLM: {round(100*len(bon)/total) if total else 0}%")
print()
for e in bon:
    print(f'  Client dit  : "{e["dit"]}"')
    print(f'  LLM trouve  : [{e["code"]}] {e["libelle"]}')
    print(f'  ES confirme : {e["es"]}')
    print()
if mauvais:
    print("--- ERREURS LLM ---")
    for e in mauvais:
        print(f'  Client dit  : "{e["dit"]}"')
        print(f'  LLM trouve  : [{e["code"]}] {e["libelle"]}')
        print(f'  ES avait    : {e["es_sample"]}')
        print()
