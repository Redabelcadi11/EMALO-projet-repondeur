#!/usr/bin/env python3
import sys
import json
from pathlib import Path
sys.path.insert(0, "/opt/emalo-repondeur-worker")

score_path = Path("/opt/emalo-autotune/private/development-exp16b-clean-quantities-score.json")
score_data = json.load(open(score_path, encoding="utf-8"))

for r in score_data.get("results", []):
    if r.get("content_exact"):
        print("Audio:", r.get("audio"))
        print("  Client:", r.get("predicted_client"))
        print("  Content exact:", r.get("content_exact"))
        print("  Date correct:", r.get("date_correct"))
        print("  Accepted (VALIDEE):", r.get("accepted"))
        print("  Causes:", r.get("causes"))
        print("  Predicted lines count:", len(r.get("predicted", [])))
        print("-" * 50)
