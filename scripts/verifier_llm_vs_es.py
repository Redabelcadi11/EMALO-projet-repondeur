"""
Compare LLM-resolved products against real ES orders.
"""
import json
import pathlib
import sys
import csv
import re
from datetime import datetime

WORKER_DIR = pathlib.Path('/opt/emalo-repondeur-worker')
EXTRACTIONS_DIR = WORKER_DIR / 'resultats' / 'extractions'
REPLAY_DIR = WORKER_DIR / 'resultats' / 'copilote-replay'

# Load all ES truth
def load_all_truth():
    truth_by_client_date = {}
    for csv_path in list(REPLAY_DIR.glob('commandes_ES_*.csv')) + list(REPLAY_DIR.glob('historique_es_pretest_*.csv')):
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=';')
                for row in reader:
                    client = row.get('client_code', '').strip()
                    order_date = row.get('order_date', '').strip()[:10]
                    code = row.get('article_code', '').strip()
                    desig = row.get('designation', '').strip()
                    if client and order_date and code:
                        key = (client, order_date)
                        if key not in truth_by_client_date:
                            truth_by_client_date[key] = {}
                        truth_by_client_date[key][code] = desig
        except Exception as e:
            pass
    return truth_by_client_date

# Parse audio filename to get date and phone
def parse_audio(audio_name):
    m = re.match(r'(\d{4}-\d{2}-\d{2})_\d{2}-\d{2}-\d{2}_De-(\d+)', audio_name)
    if m:
        return m.group(1), m.group(2)
    return None, None

# Load phone -> client mapping
def load_phone_clients():
    phone_clients = {}
    config_path = WORKER_DIR / 'config' / 'telephones-clients.json'
    try:
        data = json.loads(config_path.read_text())
        for entry in data:
            phone = str(entry.get('telephone', '')).strip()
            code = str(entry.get('client_code', '')).strip()
            if phone and code:
                phone_clients[phone] = code
    except Exception as e:
        pass
    return phone_clients

truth = load_all_truth()
phone_clients = load_phone_clients()

print(f"ES truth loaded: {sum(len(v) for v in truth.values())} articles")
print(f"Phone clients: {len(phone_clients)}")

jsons = sorted(EXTRACTIONS_DIR.glob('*.json'), key=lambda f: f.stat().st_mtime, reverse=True)

bon = 0
mauvais = 0
inconnu = 0
exemples_bon = []
exemples_mauvais = []

for f in jsons[:50]:
    audio_name = f.name.replace('__extraction.json', '')
    audio_date, phone = parse_audio(audio_name)
    client_code = phone_clients.get(phone, '')
    
    if not client_code or not audio_date:
        continue
    
    # Try exact date and +1 day (order placed evening for next morning)
    from datetime import date, timedelta
    try:
        d = date.fromisoformat(audio_date)
    except:
        continue
    
    es_articles = {}
    for delta in [0, 1, -1]:
        key = (client_code, (d + timedelta(days=delta)).isoformat())
        if key in truth:
            es_articles.update(truth[key])
    
    if not es_articles:
        continue
    
    try:
        data = json.loads(f.read_text())
        for p in data.get('produits', []):
            for c in p.get('candidats', []):
                if not c.get('llm_arbitrage'):
                    continue
                code_llm = c.get('code_article', '')
                libelle_llm = c.get('libelle', c.get('libelle_normalise', ''))
                texte_client = p.get('texte_source', '')
                
                if code_llm in es_articles:
                    bon += 1
                    exemples_bon.append({
                        'dit': texte_client,
                        'trouve': libelle_llm,
                        'code': code_llm,
                        'es': es_articles[code_llm]
                    })
                else:
                    mauvais += 1
                    exemples_mauvais.append({
                        'dit': texte_client,
                        'trouve': libelle_llm,
                        'code': code_llm,
                        'es_articles': list(es_articles.values())[:3]
                    })
    except:
        pass

total = bon + mauvais
pct = round(100*bon/total) if total else 0
print(f"\n=== VERIFICATION LLM vs ES ===")
print(f"LLM resolutions verifiables: {total}")
print(f"CORRECT (code dans commande ES): {bon}")
print(f"INCORRECT: {mauvais}")
print(f"TAUX DE PRECISION LLM: {pct}%")

print(f"\n--- BONS exemples ---")
for e in exemples_bon[:5]:
    print(f"  Dit: \"{e['dit']}\"")
    print(f"  LLM -> [{e['code']}] {e['trouve']}")
    print(f"  ES  -> {e['es']}")
    print()

if exemples_mauvais:
    print(f"\n--- MAUVAIS exemples ---")
    for e in exemples_mauvais[:3]:
        print(f"  Dit: \"{e['dit']}\"")
        print(f"  LLM -> [{e['code']}] {e['trouve']}")
        print(f"  ES avait: {e['es_articles']}")
        print()
