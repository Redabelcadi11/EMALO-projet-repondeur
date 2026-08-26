import json
import pathlib

f = pathlib.Path('/opt/emalo-repondeur-worker/resultats/extractions/2026-08-09_23-09-22_De-0680597446__extraction.json')
d = json.loads(f.read_text())
produits = d.get('produits', [])
if produits:
    print("Keys produit:", list(produits[0].keys()))
    print("Exemple mention:", produits[0].get('mention_originale', produits[0].get('clause', produits[0].get('texte',''))))
    print("Score max candidat:", max((c.get('score_global', 0) for c in produits[0].get('candidats', [])), default=0))
else:
    print("Pas de produits")
