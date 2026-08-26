#!/usr/bin/env python3
import argparse
import json
import os
import re
import unicodedata
from rapidfuzz import fuzz

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--llama", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.base, "r", encoding="utf-8") as f:
        base_data = json.load(f)
    
    with open(args.llama, "r", encoding="utf-8") as f:
        llama_data = json.load(f)
    
    llama_by_audio = {str(row.get("audio")): row for row in llama_data.get("rows", [])}
    
    for row in base_data.get("rows", []):
        audio = str(row.get("audio"))
        llama_row = llama_by_audio.get(audio)
        if not llama_row:
            continue
        
        llama_lines = llama_row.get("lines", [])
        diagnostics = row.get("diagnostics", {})
        products_det = diagnostics.get("products", [])
        lignes_finales = []
        
        for prod in products_det:
            selection = prod.get("selection")
            if not selection:
                continue
                
            code_det = selection.get("code_article")
            src_det = normalize_text(prod.get("texte_source") or "")
            est_fiable = prod.get("produit_fiable", False)
            
            ligne_conservee = {
                "code": code_det,
                "quantity": prod.get("quantite_resolue"),
                "unit": prod.get("unite_resolue"),
                "label": selection.get("libelle_article"),
                "source_text": prod.get("texte_source"),
                "origine": "deterministe_fiable" if est_fiable else "deterministe_ambigu"
            }
            
            if est_fiable:
                lignes_finales.append(ligne_conservee)
            else:
                meilleure_ligne_llama = None
                meilleur_score = 0
                for ll_line in llama_lines:
                    ll_src = normalize_text(ll_line.get("source_text", ""))
                    score = fuzz.token_set_ratio(src_det, ll_src)
                    if score >= 60 and score > meilleur_score:
                        meilleur_score = score
                        meilleure_ligne_llama = ll_line
                
                if meilleure_ligne_llama:
                    ligne_conservee = {
                        "code": meilleure_ligne_llama.get("code"),
                        "quantity": prod.get("quantite_resolue"),
                        "unit": prod.get("unite_resolue"),
                        "label": meilleure_ligne_llama.get("label", ""),
                        "source_text": meilleure_ligne_llama.get("source_text"),
                        "origine": "llama_reranking"
                    }
                    meilleure_ligne_llama["_used"] = True
                    
                lignes_finales.append(ligne_conservee)
                
        for ll_line in llama_lines:
            if ll_line.get("_used"):
                continue
                
            code = ll_line.get("code")
            label_norm = normalize_text(ll_line.get("label", ""))
            src_text_norm = normalize_text(ll_line.get("source_text", ""))
            transcription_norm = normalize_text(row.get("transcription", ""))
            
            # Anti-doublon : vérifier si ce texte source a déjà été traité
            est_doublon = False
            for prod in products_det:
                det_src = normalize_text(prod.get("texte_source") or "")
                if det_src and src_text_norm and fuzz.token_set_ratio(src_text_norm, det_src) >= 80:
                    est_doublon = True
                    break
            
            if est_doublon:
                continue
            
            fuzzy_src = fuzz.token_set_ratio(src_text_norm, label_norm) if src_text_norm else 0
            fuzzy_trans = fuzz.token_set_ratio(transcription_norm, label_norm)
            max_fuzzy = max(fuzzy_src, fuzzy_trans)
            
            if max_fuzzy < 65:
                continue
            
            lignes_finales.append({
                "code": code,
                "quantity": ll_line.get("quantity"),
                "unit": ll_line.get("unit"),
                "label": ll_line.get("label", ""),
                "source_text": ll_line.get("source_text", ""),
                "origine": "llama_additif_filtre"
            })
            
        row["lines"] = lignes_finales
        
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(base_data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()