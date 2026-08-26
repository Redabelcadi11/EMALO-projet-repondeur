#!/usr/bin/env python3
"""
Analyse détaillée des 58 lignes ajoutées par Exp 17b par rapport à Exp 16b.
Compare chaque ligne ajoutée à truth_lines du corpus de dév pour catégoriser :
- VRAI POSITIF (ligne manquante récupérée)
- FAUX POSITIF (hallucination / mauvais produit / doublon sémantique)
Et extrait les caractéristiques distinctives généralisables.
"""

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def _normaliser_texte(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = texte.lower()
    texte = re.sub(r"[^\w\s]", " ", texte)
    return re.sub(r"\s+", " ", texte).strip()

def main():
    p16_path = Path("/opt/emalo-repondeur-worker/evaluation/predictions/development-exp16b-clean-quantities.json")
    p17_path = Path("/opt/emalo-repondeur-worker/evaluation/predictions/development-exp17b-track-f-selective-hybrid.json")
    corpus_path = Path("/opt/emalo-autotune/private/corpus-temporal-2026-08-12-13-v2.json")
    ref_path = Path("/opt/emalo-repondeur-worker/config/references-articles-controle.json")

    p16_data = json.load(open(p16_path, encoding="utf-8"))
    p17_data = json.load(open(p17_path, encoding="utf-8"))
    corpus_data = json.load(open(corpus_path, encoding="utf-8"))
    ref_data = json.load(open(ref_path, encoding="utf-8")).get("references", {})

    dev_rows = [r for r in corpus_data.get("rows", []) if r.get("split") == "development"]
    corpus_audios = {r["audio"]: r for r in dev_rows}
    p16_rows = {r["audio"]: r for r in p16_data.get("rows", [])}
    p17_rows = {r["audio"]: r for r in p17_data.get("rows", [])}

    lignes_correctes = []
    lignes_fausses = []

    for audio, r17 in p17_rows.items():
        r16 = p16_rows.get(audio, {})
        rcorpus = corpus_audios.get(audio, {})

        codes_16 = {str(l.get("code")).strip().lstrip("0") for l in r16.get("lines", [])}
        lignes_17 = r17.get("lines", [])
        truth_lines = rcorpus.get("truth_lines", [])
        truth_codes = {str(l.get("code_article") or l.get("code")).strip().lstrip("0"): l for l in truth_lines}

        tpath = Path(f"/opt/emalo-repondeur-worker/resultats/transcriptions/{Path(audio).stem}__transcription.json")
        transcription_raw = ""
        if tpath.is_file():
            tdata = json.load(open(tpath, encoding="utf-8"))
            transcription_raw = tdata.get("texte") or tdata.get("transcription") or ""
        transcription_norm = _normaliser_texte(transcription_raw)

        for l in lignes_17:
            code_17 = str(l.get("code")).strip()
            code_norm = code_17.lstrip("0")

            # Est-ce une ligne ajoutée par 17b ?
            if code_norm not in codes_16:
                est_correcte = code_norm in truth_codes
                truth_match = truth_codes.get(code_norm)

                info = {
                    "audio": audio,
                    "client": r17.get("client_code"),
                    "code": code_17,
                    "code_norm": code_norm,
                    "label": l.get("label"),
                    "quantity": l.get("quantity"),
                    "unit": l.get("unit"),
                    "source_text": l.get("source_text"),
                    "est_correcte": est_correcte,
                    "truth_match": truth_match,
                    "transcription": transcription_raw,
                }

                if est_correcte:
                    lignes_correctes.append(info)
                else:
                    lignes_fausses.append(info)

    print(f"Total lignes ajoutées par Exp 17b : {len(lignes_correctes) + len(lignes_fausses)}")
    print(f"  VRAIS POSITIFS (lignes correctes récupérées) : {len(lignes_correctes)}")
    print(f"  FAUX POSITIFS (lignes erronées / parasites) : {len(lignes_fausses)}")
    print("=" * 80)

    print("\n--- 1. LIGNES CORRECTES RÉCUPÉRÉES PAR EXP 17b ---")
    for i, c in enumerate(lignes_correctes):
        tm = c['truth_match']
        qte_truth = tm.get('quantite') or tm.get('quantity')
        unit_truth = tm.get('unite') or tm.get('unit')
        print(f"[{i+1}] Audio: {c['audio']} (Client: {c['client']})")
        print(f"    Prédit : {c['code']} | {c['label']} | qte={c['quantity']} {c['unit']}")
        print(f"    Vérité : {tm.get('code_article')} | {tm.get('libelle_article')} | qte={qte_truth} {unit_truth}")
        print(f"    Source text Llama : '{c['source_text']}'")
        print("-" * 50)

    print("\n--- 2. ÉCHANTILLON DE FAUX POSITIFS (LIGNES ERRONÉES) ---")
    for i, f in enumerate(lignes_fausses[:20]):
        print(f"[{i+1}] Audio: {f['audio']} (Client: {f['client']})")
        print(f"    Prédit erroné : {f['code']} | {f['label']} | qte={f['quantity']} {f['unit']}")
        print(f"    Source text Llama : '{f['source_text']}'")
        print(f"    Extrait transcription : '{f['transcription'][:140]}...'")
        print("-" * 50)

if __name__ == "__main__":
    main()
