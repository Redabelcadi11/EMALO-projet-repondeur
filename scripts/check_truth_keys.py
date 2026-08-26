#!/usr/bin/env python3
import json

corpus_path = "/opt/emalo-autotune/private/corpus-temporal-2026-08-12-13-v2.json"
corpus_data = json.load(open(corpus_path))
dev = corpus_data.get("development", [])
row0 = dev[0]
print("Row 0 keys:", list(row0.keys()))
print("Row 0 lines sample:", row0.get("lignes", row0.get("lines", []))[:3])
