import json
from pathlib import Path
from collections import defaultdict

import sys

score_path = Path("/opt/emalo-autotune/private/development-exp1-clients-synonyms-score.json")
if len(sys.argv) > 1:
    score_path = Path(sys.argv[1])
if not score_path.exists():
    score_path = Path("/opt/emalo-autotune/private/development-baseline-eval-score.json")
if not score_path.exists():
    score_path = Path("/opt/emalo-autotune/private/development-v3-postpackaging-score.json")

data = json.loads(score_path.read_text(encoding="utf-8"))
results = data.get("results", [])

print(f"Score file: {score_path.name}")
print(f"Total dev audios: {len(results)}")
print(f"Client exact: {sum(1 for r in results if r.get('client_correct'))}/{len(results)}")
print(f"Date exact: {sum(1 for r in results if r.get('date_correct'))}/{len(results)}")
print(f"Content exact: {sum(1 for r in results if r.get('content_exact'))}/{len(results)}")
print(f"Accepted auto: {sum(1 for r in results if r.get('accepted'))}/{len(results)}")
print(f"Strict automation: {sum(1 for r in results if r.get('automation_exact'))}/{len(results)}")

print("\n--- PERFECT CONTENT ORDERS REJECTION REASONS ---")
for r in results:
    if r.get('content_exact'):
        print(f"Audio: {r['audio']}")
        print(f"  client_correct={r.get('client_correct')} date_correct={r.get('date_correct')}")
        print(f"  accepted={r.get('accepted')} predicted_status={r.get('predicted_status')}")
        print(f"  causes={r.get('causes')}")
        print(f"  problem_reasons={r.get('diagnostics', {}).get('problem_reasons')}")
        print(f"  client_reasons={r.get('diagnostics', {}).get('client_reasons')}")
        for idx, p in enumerate(r.get('diagnostics', {}).get('products', []), start=1):
            sel = p.get('selection') or {}
            print(f"    Product {idx}: code={sel.get('code_article')} label={sel.get('libelle_article')} score_global={sel.get('score_global')} regle={sel.get('regle_selection')} cadencier={sel.get('dans_cadencier_client')} fiable={p.get('produit_fiable')} ambigu={p.get('ambigu')} raisons_ambiguite={p.get('raisons_ambiguite')}")
        print("-" * 60)


print("\n" + "="*80)
print("AUDIOS RANKED BY DIFFICULTY (number of missing + extra lines):")
ranked = sorted(results, key=lambda r: len(r.get('missing', [])) + len(r.get('extra', [])), reverse=False)

for r in ranked:
    miss_len = len(r.get('missing', []))
    extra_len = len(r.get('extra', []))
    truth_len = len(r.get('truth', []))
    pred_len = len(r.get('predicted', []))
    print(f"\nAudio: {r['audio']} | truth_lines={truth_len}, pred_lines={pred_len} | missing={miss_len}, extra={extra_len} | client_ok={r.get('client_correct')} | date_ok={r.get('date_correct')} | accepted={r.get('accepted')}")
    print(f"  Truth client: {r.get('truth_client')} | Pred client: {r.get('predicted_client')}")
    if not r.get('date_correct'):
        print(f"  DATE MISMATCH: truth={r.get('truth_delivery_date')} pred={r.get('predicted_delivery_date')}")
    print(f"  Causes: {r.get('causes')}")
    print(f"  Text: {r.get('transcription', '')}")
    if miss_len:
        print(f"  Missing lines:")
        for m in r.get('missing', []):
            rank = r.get('expected_candidate_ranks', {}).get(m['code'], 'N/A')
            print(f"    - code={m['code']} qte={m['quantity']} unit={m['unit']} (candidate rank={rank})")
    if extra_len:
        print(f"  Extra lines:")
        for e in r.get('extra', []):
            print(f"    - code={e['code']} qte={e['quantity']} unit={e['unit']}")
    print("  All truth:")
    for t in r.get('truth', []):
        print(f"    - code={t['code']} qte={t['quantity']} unit={t['unit']}")
    print("  All predicted:")
    for p in r.get('predicted', []):
        print(f"    - code={p['code']} qte={p['quantity']} unit={p['unit']}")
