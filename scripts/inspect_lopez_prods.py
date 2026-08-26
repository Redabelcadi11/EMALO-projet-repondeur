#!/usr/bin/env python3
import sys
import json
from pathlib import Path
sys.path.insert(0, "/opt/emalo-repondeur-worker")

import extraire_informations as extraction

tpath = Path("/opt/emalo-repondeur-worker/resultats/transcriptions/2026-08-12_12-42-47_De-0559268233__transcription.json")
tdata = json.load(open(tpath))
texte = tdata.get("texte") or tdata.get("transcription")
mentions = extraction.extraire_mentions_produits(texte)
cadencier = extraction.charger_cadencier()
catalogue_global = extraction.construire_catalogue_global(cadencier)
synonymes_produits = extraction.charger_synonymes_produits(extraction.CHEMIN_SYNONYMES_PRODUITS)

client = "LOPEZSJL"
prods = extraction.chercher_produits(
    mentions=mentions,
    produits_client=cadencier.get(client, []),
    catalogue_global=catalogue_global,
    synonymes_produits=synonymes_produits
)

print(f"Total mentions: {len(mentions)}")
print(f"Total prods: {len(prods)}")
for i, p in enumerate(prods):
    print(f"Prod {i+1}:")
    print(f"  texte: '{p.get('texte_source')}'")
    print(f"  quantite: {p.get('quantite')}")
    print(f"  ambigu: {p.get('ambigu')}")
    print(f"  fiable: {p.get('produit_fiable')}")
    print(f"  raisons_ambiguite: {p.get('raisons_ambiguite')}")
    print(f"  selection: {p.get('selection', {}).get('code_article')} | {p.get('selection', {}).get('libelle_article')}")
