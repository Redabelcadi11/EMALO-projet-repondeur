#!/usr/bin/env python3
import sys
import json
from pathlib import Path
sys.path.insert(0, "/opt/emalo-repondeur-worker")

p16_path = Path("/opt/emalo-repondeur-worker/evaluation/predictions/development-exp16b-clean-quantities.json")
p18_path = Path("/opt/emalo-repondeur-worker/evaluation/predictions/development-exp18-selective-hybrid-filter.json")
corpus_path = Path("/opt/emalo-autotune/private/corpus-temporal-2026-08-12-13-v2.json")

p16_data = json.load(open(p16_path, encoding="utf-8"))
p18_data = json.load(open(p18_path, encoding="utf-8"))
corpus_data = json.load(open(corpus_path, encoding="utf-8"))

dev_rows = [r for r in corpus_data.get("rows", []) if r.get("split") == "development"]
corpus_audios = {r["audio"]: r for r in dev_rows}
p16_rows = {r["audio"]: r for r in p16_data.get("rows", [])}
p18_rows = {r["audio"]: r for r in p18_data.get("rows", [])}

tp = []
fp = []

for audio, r18 in p18_rows.items():
    r16 = p16_rows.get(audio, {})
    rcorpus = corpus_audios.get(audio, {})
    codes_16 = {str(l.get("code")).strip().lstrip("0") for l in r16.get("lines", [])}
    truth_lines = rcorpus.get("truth_lines", [])
    truth_codes = {str(l.get("code_article") or l.get("code")).strip().lstrip("0"): l for l in truth_lines}

    for l in r18.get("lines", []):
        code_18 = str(l.get("code")).strip()
        code_norm = code_18.lstrip("0")
        if code_norm not in codes_16:
            is_tp = code_norm in truth_codes
            rec = {
                "audio": audio,
                "client": r18.get("client_code"),
                "code": code_18,
                "label": l.get("label"),
                "quantity": l.get("quantity"),
                "unit": l.get("unit"),
                "source_text": l.get("source_text"),
                "truth": truth_codes.get(code_norm)
            }
            if is_tp:
                tp.append(rec)
            else:
                fp.append(rec)

print(f"Total ajouts Exp 18 : {len(tp) + len(fp)}")
print(f"Vrais Positifs : {len(tp)} ({len(tp)/(len(tp)+len(fp))*100:.1f}%)")
print(f"Faux Positifs  : {len(fp)} ({len(fp)/(len(tp)+len(fp))*100:.1f}%)")

print("\n--- Vrais Positifs récupérés ---")
for x in tp:
    print(f"  [TP] Client={x['client']} | {x['code']} {x['label']} qte={x['quantity']} {x['unit']} | src='{x['source_text']}'")

print("\n--- Faux Positifs résiduels ---")
for x in fp:
    print(f"  [FP] Client={x['client']} | {x['code']} {x['label']} qte={x['quantity']} {x['unit']} | src='{x['source_text']}'")
