#!/usr/bin/env python3
import sys
import json
import re
import unicodedata
from pathlib import Path
sys.path.insert(0, "/opt/emalo-repondeur-worker")
from rapidfuzz import fuzz

def _normaliser_texte(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = texte.lower()
    texte = re.sub(r"[^\w\s]", " ", texte)
    return re.sub(r"\s+", " ", texte).strip()

p16_path = Path("/opt/emalo-repondeur-worker/evaluation/predictions/development-exp16b-clean-quantities.json")
p17_path = Path("/opt/emalo-repondeur-worker/evaluation/predictions/development-exp17b-track-f-selective-hybrid.json")
corpus_path = Path("/opt/emalo-autotune/private/corpus-temporal-2026-08-12-13-v2.json")
ref_path = Path("/opt/emalo-repondeur-worker/config/references-articles-controle.json")

import extraire_informations as extraction
cadenciers = extraction.charger_cadencier()

p16_data = json.load(open(p16_path, encoding="utf-8"))
p17_data = json.load(open(p17_path, encoding="utf-8"))
corpus_data = json.load(open(corpus_path, encoding="utf-8"))
ref_data = json.load(open(ref_path, encoding="utf-8")).get("references", {})

dev_rows = [r for r in corpus_data.get("rows", []) if r.get("split") == "development"]
corpus_audios = {r["audio"]: r for r in dev_rows}
p16_rows = {r["audio"]: r for r in p16_data.get("rows", [])}
p17_rows = {r["audio"]: r for r in p17_data.get("rows", [])}

tp_list = []
fp_list = []

for audio, r17 in p17_rows.items():
    r16 = p16_rows.get(audio, {})
    rcorpus = corpus_audios.get(audio, {})
    client_code = str(r17.get("client_code") or "").upper()
    cad_articles = {str(a.get("code_article") or "").strip().lstrip("0") for a in cadenciers.get(client_code, [])}

    codes_16 = {str(l.get("code")).strip().lstrip("0") for l in r16.get("lines", [])}
    truth_lines = rcorpus.get("truth_lines", [])
    truth_codes = {str(l.get("code_article") or l.get("code")).strip().lstrip("0"): l for l in truth_lines}

    tpath = Path(f"/opt/emalo-repondeur-worker/resultats/transcriptions/{Path(audio).stem}__transcription.json")
    transcription_raw = ""
    if tpath.is_file():
        tdata = json.load(open(tpath, encoding="utf-8"))
        transcription_raw = tdata.get("texte") or tdata.get("transcription") or ""
    transcription_norm = _normaliser_texte(transcription_raw)

    # Positions des mentions déterministes déjà couvertes
    det_source_texts = [_normaliser_texte(l.get("source_text", "")) for l in r16.get("lines", [])]

    for l in r17.get("lines", []):
        code_17 = str(l.get("code")).strip()
        code_norm = code_17.lstrip("0")

        if code_norm not in codes_16:
            est_tp = code_norm in truth_codes
            dans_cad = code_norm in cad_articles
            src_text = _normaliser_texte(l.get("source_text", ""))
            label_norm = _normaliser_texte(l.get("label", ""))

            # Calcul du chevauchement avec une ligne déterministe existante
            chevauche_det = any(src_text in det_src or det_src in src_text for det_src in det_source_texts if len(det_src) > 5)

            # Calcul de fuzzy match
            ratio = fuzz.partial_ratio(label_norm, transcription_norm)
            token_set_ratio = fuzz.token_set_ratio(label_norm, src_text)

            record = {
                "audio": audio,
                "client": client_code,
                "code": code_17,
                "label": l.get("label"),
                "dans_cad": dans_cad,
                "src_len": len(src_text),
                "chevauche_det": chevauche_det,
                "ratio": ratio,
                "token_set_ratio": token_set_ratio,
                "source_text": l.get("source_text"),
                "quantity": l.get("quantity"),
            }

            if est_tp:
                tp_list.append(record)
            else:
                fp_list.append(record)

print(f"=== STATISTIQUES COMPARATIVES ===")
print(f"Nombre de TP : {len(tp_list)} | Nombre de FP : {len(fp_list)}")

print("\n1. Appartenance au Cadencier Client :")
tp_cad = sum(1 for x in tp_list if x["dans_cad"])
fp_cad = sum(1 for x in fp_list if x["dans_cad"])
print(f"  TP dans cadencier : {tp_cad}/{len(tp_list)} ({tp_cad/len(tp_list)*100:.1f}%)")
print(f"  FP dans cadencier : {fp_cad}/{len(fp_list)} ({fp_cad/len(fp_list)*100:.1f}%)")

print("\n2. Chevauchement avec texte source déjà extrait par déterministe :")
tp_chev = sum(1 for x in tp_list if x["chevauche_det"])
fp_chev = sum(1 for x in fp_list if x["chevauche_det"])
print(f"  TP chevauchant une mention déterministe existante (doublon) : {tp_chev}/{len(tp_list)} ({tp_chev/len(tp_list)*100:.1f}%)")
print(f"  FP chevauchant une mention déterministe existante (doublon) : {fp_chev}/{len(fp_list)} ({fp_chev/len(fp_list)*100:.1f}%)")

print("\n3. Token Set Ratio moyen entre label officiel et source_text Llama :")
avg_tp_tsr = sum(x["token_set_ratio"] for x in tp_list) / len(tp_list)
avg_fp_tsr = sum(x["token_set_ratio"] for x in fp_list) / len(fp_list)
print(f"  TP Token Set Ratio moyen : {avg_tp_tsr:.1f}")
print(f"  FP Token Set Ratio moyen : {avg_fp_tsr:.1f}")

print("\n4. Détail des 33 Faux Positifs :")
for i, fp in enumerate(fp_list):
    print(f"  FP [{i+1}] Client={fp['client']} Cad={fp['dans_cad']} ChevaucheDet={fp['chevauche_det']} TSR={fp['token_set_ratio']} | Code={fp['code']} Label={fp['label'][:35]} | Src='{fp['source_text']}'")
