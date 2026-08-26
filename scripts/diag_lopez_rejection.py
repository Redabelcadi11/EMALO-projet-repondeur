#!/usr/bin/env python3
import sys
import json
from pathlib import Path
sys.path.insert(0, "/opt/emalo-repondeur-worker")

import extraire_informations as extraction

tpath = Path("/opt/emalo-repondeur-worker/resultats/transcriptions/2026-08-12_12-42-47_De-0559268233__transcription.json")
cmds = extraction.traiter_transcriptions([tpath])
cmd = cmds[0] if cmds else {}

print("Audio:", tpath.name)
print("Statut final:", cmd.get("statut"))
print("Raison statut:", cmd.get("raison_statut"))
print("Decision auto client:", cmd.get("decision_automatique_client"))
print("Lignes count:", len(cmd.get("lignes_produits", [])))
print("Mentions count:", len(cmd.get("mentions_analysees", [])))
for i, m in enumerate(cmd.get("mentions_analysees", [])):
    print(f"Mention {i+1}:")
    print(f"  texte: '{m.get('texte_source')}'")
    print(f"  produit: '{m.get('produit_normalise')}'")
    print(f"  quantite: {m.get('quantite')}")
    print(f"  ambigu: {m.get('ambigu')}")
    print(f"  raisons_ambiguite: {m.get('raisons_ambiguite')}")
    print(f"  selection: {bool(m.get('selection'))}")
