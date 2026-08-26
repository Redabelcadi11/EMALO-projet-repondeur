#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, "/opt/emalo-repondeur-worker")

import extraire_informations as extraction

tpath = Path("/opt/emalo-repondeur-worker/resultats/transcriptions/2026-08-12_12-42-47_De-0559268233__transcription.json")
texte = extraction.lire_transcription(tpath)
mentions = extraction.extraire_mentions_produits(texte)
cadencier = extraction.charger_cadencier()
catalogue_global = extraction.construire_catalogue_global(cadencier)
synonymes = extraction.charger_synonymes_produits(extraction.CHEMIN_SYNONYMES_PRODUITS)

prods = extraction.chercher_produits(
    mentions=mentions,
    produits_client=cadencier.get("LOPEZSJL", []),
    catalogue_global=catalogue_global,
    synonymes_produits=synonymes
)

p5 = prods[4]
print("Mention 5:", p5.get("texte_source"))
print("Selection:", p5.get("selection"))
print("Fiable:", p5.get("produit_fiable"))
print("Ambigu:", p5.get("ambigu"))
print("Raisons ambiguite:", p5.get("raisons_ambiguite"))
print("Candidats top 3:")
for c in p5.get("candidats", [])[:3]:
    print(f"  {c.get('code_article')} | {c.get('libelle_article')} | score_glob={c.get('score_global')} | score_sel={c.get('score_selection')} | dans_cad={c.get('dans_cadencier_client')}")
