#!/usr/bin/env python3
import json
from pathlib import Path

tpath = Path("/opt/emalo-repondeur-worker/resultats/transcriptions/2026-08-13_02-20-48_De-0663651399__transcription.json")
data = json.load(open(tpath))
print("Texte:", data.get("texte"))
