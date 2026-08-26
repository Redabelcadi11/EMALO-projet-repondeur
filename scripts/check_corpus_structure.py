#!/usr/bin/env python3
import json

corpus_path = "/opt/emalo-autotune/private/corpus-temporal-2026-08-12-13-v2.json"
corpus_data = json.load(open(corpus_path))
print("Corpus keys:", list(corpus_data.keys()))
if "rows" in corpus_data:
    print("Rows count:", len(corpus_data["rows"]))
    print("Row 0 keys:", list(corpus_data["rows"][0].keys()))
    print("Row 0 lines:", corpus_data["rows"][0].get("lines", [])[:2])
