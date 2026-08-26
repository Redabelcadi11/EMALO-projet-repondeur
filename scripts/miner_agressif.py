import json
import csv
import pathlib
import re
from datetime import date, timedelta
from collections import defaultdict

WORKER_DIR = pathlib.Path('/opt/emalo-repondeur-worker')
EXTRACTIONS_DIR = WORKER_DIR / 'resultats' / 'extractions'
REPLAY_DIR = WORKER_DIR / 'resultats' / 'copilote-replay'
CONFIG_DIR = WORKER_DIR / 'config'

def miner_profils():
    # 1. Load phone mappings
    phones = {}
    try:
        raw_phones = json.loads((CONFIG_DIR / 'telephones-clients.json').read_text(encoding='utf-8'))
        for client_code, phone_list in raw_phones.items():
            if isinstance(phone_list, list):
                for ph in phone_list:
                    normalized = ph.replace(' ', '').replace('+33', '0').strip()
                    phones[normalized] = client_code
            else:
                # old format
                normalized = str(raw_phones.get('telephone', '')).replace(' ', '').replace('+33', '0').strip()
                phones[normalized] = raw_phones.get('client_code')
    except Exception as e:
        print("Erreur chargement telephones:", e)
        return

    # 2. Load ES truth
    truth = {}
    for csv_path in list(REPLAY_DIR.glob('commandes_ES_*.csv')) + list(REPLAY_DIR.glob('historique_es_pretest_*.csv')):
        try:
            with open(csv_path, encoding='utf-8') as f:
                for row in csv.DictReader(f, delimiter=';'):
                    cl = row.get('client_code', '').strip()
                    od = str(row.get('order_date', '')).strip()[:10]
                    co = row.get('article_code', '').strip()
                    dg = row.get('designation', '').strip()
                    if cl and od and co:
                        truth.setdefault((cl, od), {})[co] = dg
        except:
            pass

    # 3. Analyze matches vs mismatches
    substitutions_candidates = defaultdict(lambda: defaultdict(int))
    ghosts = defaultdict(lambda: defaultdict(int))
    total_orders_per_client = defaultdict(int)

    jsons = list(EXTRACTIONS_DIR.glob('*.json'))
    for f in jsons:
        m = re.match(r'(\d{4}-\d{2}-\d{2})_\d{2}-\d{2}-\d{2}_De-(\d+)', f.name)
        if not m: continue
        audio_date, phone = m.group(1), m.group(2)
        client = phones.get(phone, '')
        if not client: continue
        
        try:
            d = date.fromisoformat(audio_date)
            es = {}
            # fuzzy date match
            for delta in [0, 1, -1, 2]:
                k = (client, (d + timedelta(days=delta)).isoformat())
                if k in truth:
                    es.update(truth[k])
            
            if not es:
                continue

            total_orders_per_client[client] += 1
            data = json.loads(f.read_text(encoding='utf-8'))
            
            ia_codes = set()
            for p in data.get('produits', []):
                for c in p.get('candidats', []):
                    if c.get('score_global', 0) >= 55 or c.get('llm_arbitrage'):
                        ia_codes.add(c.get('code_article', ''))

            # Analyze False Positives vs Missed (for substitutions)
            fp = ia_codes - set(es.keys())
            missed = set(es.keys()) - ia_codes
            
            # If 1 FP and 1 Missed, strong substitution candidate
            if len(fp) == 1 and len(missed) == 1:
                fp_code = list(fp)[0]
                miss_code = list(missed)[0]
                substitutions_candidates[client][(fp_code, miss_code)] += 1
            
            # Analyze ghosts
            for m_code in missed:
                ghosts[client][m_code] += 1

        except Exception as e:
            pass

    # 4. Generate Aggressive Rules
    agressif = {
        "substitutions": {},
        "ajouts_fantomes": {}
    }

    # Substitutions rule: if substituted >= 2 times
    for client, subs in substitutions_candidates.items():
        client_subs = {}
        for (fp_code, miss_code), count in subs.items():
            if count >= 2:
                client_subs[fp_code] = miss_code
        if client_subs:
            agressif["substitutions"][client] = client_subs

    # Ghosts rule: if ghost present in > 60% of all client's orders, and minimum 3 times
    for client, missed_items in ghosts.items():
        client_ghosts = []
        tot = total_orders_per_client[client]
        for m_code, count in missed_items.items():
            if count >= 3 and count / tot >= 0.6:
                client_ghosts.append(m_code)
        if client_ghosts:
            agressif["ajouts_fantomes"][client] = client_ghosts

    print(json.dumps(agressif, indent=2))
    
    # Save to config
    config_path = CONFIG_DIR / 'profils-clients-agressifs.json'
    config_path.write_text(json.dumps(agressif, indent=4), encoding='utf-8')
    print(f"\nRègles agressives sauvegardées dans {config_path.name}")

if __name__ == '__main__':
    miner_profils()
