#!/usr/bin/env python3
import sys
import json
from pathlib import Path
sys.path.insert(0, "/opt/emalo-repondeur-worker")

score_path = Path("/opt/emalo-autotune/private/development-exp20-ultimate-hybrid-score.json")
score_data = json.load(open(score_path, encoding="utf-8"))

results = score_data.get("results", [])

print("=== ANALYSE DES 16 ERREURS DE QUANTITÉ RESTANTES ===")
count_qte = 0
for r in results:
    if "quantite" in r.get("causes", []):
        count_qte += 1
        print(f"[{count_qte}] Audio: {r.get('audio')} | Client: {r.get('predicted_client')}")
        for t in r.get("truth", []):
            print(f"    Truth: {t.get('code')} | {t.get('quantity')} {t.get('unit')} | {t.get('label')}")
        for p in r.get("predicted", []):
            print(f"    Pred : {p.get('code')} | {p.get('quantity')} {p.get('unit')} | {p.get('label')}")
        print("-" * 50)

print(f"\n=== ANALYSE DES ERREURS DE CLASSEMENT PRODUIT (TOP 10) ===")
count_class = 0
for r in results:
    if "classement_produit" in r.get("causes", []):
        count_class += 1
        if count_class <= 10:
            print(f"[{count_class}] Audio: {r.get('audio')} | Client: {r.get('predicted_client')}")
            print(f"    Expected candidate ranks: {r.get('expected_candidate_ranks')}")
            for m in r.get("missing", []):
                print(f"    Missing: {m.get('code')} | qte={m.get('quantity')} {m.get('unit')}")
            print("-" * 50)
