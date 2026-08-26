import json
import pathlib

extractions_dir = pathlib.Path('/opt/emalo-repondeur-worker/resultats/extractions')
jsons = sorted(extractions_dir.glob('*.json'), key=lambda f: f.stat().st_mtime, reverse=True)

exemples = []

for f in jsons[:50]:  # Only look at recent files
    try:
        data = json.loads(f.read_text())
        for p in data.get('produits', []):
            candidats = p.get('candidats', [])
            for c in candidats:
                if c.get('llm_arbitrage'):
                    exemples.append({
                        'audio': f.name.replace('__extraction.json', ''),
                        'texte_client': p.get('texte_source', p.get('texte_produit', '')),
                        'produit_normalise': p.get('produit_normalise', ''),
                        'libelle_trouve': c.get('libelle', c.get('libelle_normalise', '')),
                        'code': c.get('code_article', ''),
                        'score': round(c.get('score_global', 0), 1),
                    })
    except:
        pass

for e in exemples:
    print(f"Audio   : {e['audio']}")
    print(f"Client a dit : \"{e['texte_client']}\"")
    print(f"Produit normalise : \"{e['produit_normalise']}\"")
    print(f"LLM a trouve : [{e['code']}] {e['libelle_trouve']} (score={e['score']})")
    print("---")
