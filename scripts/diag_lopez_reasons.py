#!/usr/bin/env python3
import sys
import json
from pathlib import Path
sys.path.insert(0, "/opt/emalo-repondeur-worker")

pred_path = Path("/opt/emalo-repondeur-worker/evaluation/predictions/development-exp16b-clean-quantities.json")
pred_data = json.load(open(pred_path, encoding="utf-8"))

for r in pred_data.get("rows", []):
    if "12-42-47" in r.get("audio", ""):
        print("Audio:", r.get("audio"))
        print("Status:", r.get("status"))
        print("Error:", r.get("error"))
        print("Diagnostics keys:", list(r.get("diagnostics", {}).keys()))
        print("Lines count:", len(r.get("lines", [])))
        for l in r.get("lines", []):
            print("  Line:", l)
        print("Problem reasons:", r.get("diagnostics", {}).get("problem_reasons"))
        print("Mentions in diagnostics:")
        for m in r.get("diagnostics", {}).get("mentions", []):
            print("  m:", m)
