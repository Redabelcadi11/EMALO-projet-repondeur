#!/usr/bin/env python3
import sys
import json
from pathlib import Path
sys.path.insert(0, "/opt/emalo-repondeur-worker")

score_path = Path("/opt/emalo-autotune/private/development-exp20-ultimate-hybrid-score.json")
score_data = json.load(open(score_path, encoding="utf-8"))

for r in score_data.get("results", []):
    if "quantite" in r.get("causes", []):
        audio = r.get("audio")
        client = r.get("predicted_client")
        print(f"Audio: {audio} | Client: {client}")
        # print transcription
        tpath = Path(f"/opt/emalo-repondeur-worker/resultats/transcriptions/{Path(audio).stem}__transcription.json")
        if tpath.is_file():
            print("  Transcription:", json.load(open(tpath)).get("texte"))
        truth_lines = {t["code"]: t for t in r.get("truth", [])}
        pred_lines = {p["code"]: p for p in r.get("predicted", [])}
        for code in set(truth_lines) & set(pred_lines):
            t = truth_lines[code]
            p = pred_lines[code]
            if t["quantity"] != p["quantity"]:
                print(f"  Code: {code} ({t.get('label')})")
                print(f"    Truth: {t['quantity']} {t['unit']}")
                print(f"    Pred : {p['quantity']} {p['unit']}")
        print("=" * 60)
