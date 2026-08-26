#!/usr/bin/env python3
import re
import sys
from pathlib import Path
sys.path.insert(0, "/opt/emalo-repondeur-worker")

with open("/opt/emalo-repondeur-worker/src/produits.py", encoding="utf-8") as f:
    lines = f.readlines()

for i, l in enumerate(lines):
    if "conditionnement_multiple" in l and "ambigu" in l:
        print(f"Line {i+1}: {l.strip()}")
    if "quantite_absente_a_resoudre" in l:
        print(f"Line {i+1}: {l.strip()}")
