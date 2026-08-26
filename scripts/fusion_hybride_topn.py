#!/usr/bin/env python3
import argparse
import json
import logging
import sys
from pathlib import Path

import urllib.request
import urllib.parse
import urllib.error

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"

def call_ollama(prompt: str) -> str:
    payload = {
        "model": "llama3.1:70b",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "seed": 0
        }
    }
    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response).get("response", "")

def build_prompt(transcription: str, texte_source: str, candidats: list) -> str:
    prompt = f"""Tu es un expert métier pour un fournisseur alimentaire (EMALO).
Un client a passé une commande vocale. Le système a isolé un extrait de la transcription qui correspond à un produit, mais hésite entre plusieurs candidats de son catalogue.

TRANSCRIPTION COMPLÈTE DU CLIENT :
"{transcription}"

EXTRAIT SPÉCIFIQUE À ANALYSER :
"{texte_source}"

CANDIDATS POSSIBLES DU CATALOGUE :
"""
    for i, c in enumerate(candidats, start=1):
        prompt += f"{i}. Code: {c.get('code_article')} | Libellé: {c.get('libelle_article')}\n"
        
    prompt += """
TA MISSION :
Analyse le contexte de la transcription et l'extrait spécifique, puis choisis LE MEILLEUR candidat parmi la liste.
Si l'extrait correspond de manière évidente à l'un des candidats, renvoie UNIQUEMENT le Code du produit sous ce format exact :
CODE: <code_article>

Si aucun candidat ne correspond du tout à l'extrait (c'est-à-dire si le système s'est trompé en isolant cet extrait, ou que le client parle d'autre chose), renvoie exactement :
CODE: AUCUN
"""
    return prompt

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.predictions, "r", encoding="utf-8") as f:
        base_data = json.load(f)

    for row in base_data.get("rows", []):
        transcription = row.get("transcription", "")
        diagnostics = row.get("diagnostics", {})
        products_det = diagnostics.get("products", [])
        
        final_lines = []
        for index, prod in enumerate(products_det, start=1):
            selection = prod.get("selection")
            if not selection:
                continue
            
            code_det = selection.get("code_article")
            est_fiable = bool(prod.get("produit_fiable", False))
            
            ligne = {
                "code": code_det,
                "quantity": prod.get("quantite_resolue"),
                "unit": prod.get("unite_resolue"),
                "label": selection.get("libelle_article"),
                "source_text": prod.get("texte_source"),
                "origine": "deterministe_fiable" if est_fiable else "deterministe_ambigu"
            }
            
            if est_fiable:
                final_lines.append(ligne)
            else:
                candidats = prod.get("candidats", [])
                if not candidats:
                    final_lines.append(ligne)
                    continue
                
                # Limit to top 10 candidates
                top_candidats = candidats[:10]
                prompt = build_prompt(transcription, prod.get("texte_source", ""), top_candidats)
                
                try:
                    response_text = call_ollama(prompt)
                    
                    chosen_code = None
                    for line in response_text.split("\n"):
                        if line.startswith("CODE:"):
                            chosen_code = line.split("CODE:")[1].strip()
                            break
                            
                    if chosen_code and chosen_code != "AUCUN":
                        for c in top_candidats:
                            if c.get("code_article") == chosen_code:
                                ligne["code"] = c.get("code_article")
                                ligne["label"] = c.get("libelle_article")
                                ligne["origine"] = "llama_topn"
                                break
                    elif chosen_code == "AUCUN":
                        ligne["origine"] = "llama_rejected"
                        continue # Skip appending this line
                        
                except Exception as e:
                    print(f"Erreur appel Llama: {e}")
                    
                final_lines.append(ligne)
                
        row["lines"] = final_lines
        
        reliable = bool(final_lines) and all(
            (line.get("origine") == "deterministe_fiable" or line.get("origine") == "llama_topn")
            for line in final_lines
        )
        row["status"] = "VALIDEE" if reliable and bool(row.get("client_code")) and bool(row.get("delivery_date")) else "PROBLEMATIQUE"

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(base_data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()