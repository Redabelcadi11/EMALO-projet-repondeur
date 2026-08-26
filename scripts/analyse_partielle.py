import json
import pathlib

extractions_dir = pathlib.Path('/opt/emalo-repondeur-worker/resultats/extractions')
jsons = sorted(extractions_dir.glob('*.json'), key=lambda f: f.stat().st_mtime)

total_mentions = 0
confiant = 0
avec_llm_confiant = 0
avec_llm_total = 0
llm_fichiers = 0

for f in jsons:
    try:
        data = json.loads(f.read_text())
        fichier_a_llm = False
        for p in data.get('produits', []):
            candidats = p.get('candidats', [])
            if not candidats:
                continue
            total_mentions += 1
            best_score = max(c.get('score_global', 0) for c in candidats)
            has_llm = any(c.get('llm_arbitrage') for c in candidats)
            if has_llm:
                avec_llm_total += 1
                fichier_a_llm = True
            if best_score >= 55:
                confiant += 1
                if has_llm:
                    avec_llm_confiant += 1
        if fichier_a_llm:
            llm_fichiers += 1
    except Exception as e:
        pass

pct = round(100*confiant/total_mentions) if total_mentions else 0
print(f"Fichiers analyses: {len(jsons)}")
print(f"Mentions produits: {total_mentions}")
print(f"Score confiant >= 55: {confiant} / {total_mentions} ({pct}%)")
print(f"Arbitres par LLM (total): {avec_llm_total}")
print(f"Arbitres LLM qui ont rendu le score confiant: {avec_llm_confiant}")
print(f"Fichiers avec au moins 1 appel LLM: {llm_fichiers}")
