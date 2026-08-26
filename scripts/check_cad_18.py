#!/usr/bin/env python3
import sys
import json
from pathlib import Path
sys.path.insert(0, "/opt/emalo-repondeur-worker")
import extraire_informations as extraction
cadenciers = extraction.charger_cadencier()

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

for audio, r18 in p18_rows.items():
    r16 = p16_rows.get(audio, {})
    rcorpus = corpus_audios.get(audio, {})
    client_code = str(r18.get("client_code") or "").upper()
    cad_articles = {str(a.get("code_article") or "").strip().lstrip("0") for a in cadenciers.get(client_code, [])}

    codes_16 = {str(l.get("code")).strip().lstrip("0") for l in r16.get("lines", [])}
    truth_lines = rcorpus.get("truth_lines", [])
    truth_codes = {str(l.get("code_article") or l.get("code")).strip().lstrip("0"): l for l in truth_lines}

    for l in r18.get("lines", []):
        code_18 = str(l.get("code")).strip()
        code_norm = code_18.lstrip("0")
        if code_norm not in codes_16:
            is_tp = code_norm in truth_codes
            dans_cad = code_norm in cad_articles
            status = "TP" if is_tp else "FP"
            print(f"[{status}] Client={client_code:15} InCad={dans_cad:5} | Code={code_18} {l.get('label')[:35]} | src='{l.get('source_text')}'")
