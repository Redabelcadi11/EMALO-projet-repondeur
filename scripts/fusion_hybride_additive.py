#!/usr/bin/env python3
"""
Fusion Hybride Additive Sélective et Anti-Doublons (Expérience 18 / Piste F3)
Conserve 100% de la base déterministe (Exp 16b) sans jamais remplacer ni écraser les lignes existantes.
Intègre uniquement les candidats Llama validés pour les lignes manquantes :
1. Anti-doublon : rejet strict si le texte source ou le produit chevauche une mention déterministe existante.
2. Incompatibilités sémantiques : passage obligatoire par _exclusions_produit pour rejeter les mauvaises variantes (sucre/glace, jambon blanc/serrano, beurre/fromage blanc).
3. Priorité au cadencier client : seuils plus stricts sur les articles hors cadencier.
"""

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any
from rapidfuzz import fuzz

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import extraire_informations as extraction
from src.produits import _incompatibilites_semantiques, _tokens_produit


def _normaliser_texte(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = texte.lower()
    texte = re.sub(r"[^\w\s]", " ", texte)
    return re.sub(r"\s+", " ", texte).strip()


def charger_referentiel(racine: Path) -> dict[str, dict[str, Any]]:
    ref_path = racine / "config" / "references-articles-controle.json"
    if not ref_path.is_file():
        return {}
    raw = json.load(open(ref_path, encoding="utf-8"))
    refs = raw.get("references", raw)
    index: dict[str, dict[str, Any]] = {}
    for code, info in refs.items():
        code_str = str(code).strip()
        index[code_str] = info
        index[code_str.lstrip("0")] = info
        index[code_str.zfill(8)] = info
    return index


def charger_unites_officielles(racine: Path) -> dict[str, str]:
    unites_path = racine / "config" / "unites-articles.csv"
    unites: dict[str, str] = {}
    if unites_path.is_file():
        with open(unites_path, encoding="utf-8", newline="") as f:
            reader = csv.reader(f, delimiter=";")
            for row in reader:
                if len(row) >= 2:
                    code = row[0].strip().strip('"')
                    unit = row[1].strip().strip('"')
                    unites[code] = unit
                    unites[code.lstrip("0")] = unit
                    unites[code.zfill(8)] = unit
    return unites


def valider_candidat_llama(
    candidat: dict[str, Any],
    transcription_norm: str,
    dans_cadencier: bool,
    lignes_det_existantes: list[dict[str, Any]],
    referentiel: dict[str, dict[str, Any]],
    unites_officielles: dict[str, str],
) -> dict[str, Any] | None:
    code = str(candidat.get("code") or "").strip()
    if not code:
        return None

    article_info = referentiel.get(code) or referentiel.get(code.lstrip("0")) or referentiel.get(code.zfill(8))
    if not article_info:
        return None

    try:
        quantite = float(candidat.get("quantity") or 0)
    except (ValueError, TypeError):
        return None

    if quantite <= 0 or quantite > 150:
        return None

    label_officiel = article_info.get("label") or candidat.get("label") or ""
    unite_officielle = (
        unites_officielles.get(code)
        or unites_officielles.get(code.lstrip("0"))
        or article_info.get("order_unit")
        or candidat.get("unit")
        or "PI"
    )

    src_text_raw = str(candidat.get("source_text") or "")
    src_text_norm = _normaliser_texte(src_text_raw)
    label_norm = _normaliser_texte(label_officiel)

    # 1. Anti-doublon strict avec mentions déterministes existantes
    for l_det in lignes_det_existantes:
        det_src = _normaliser_texte(str(l_det.get("source_text") or ""))
        det_lbl = _normaliser_texte(str(l_det.get("label") or ""))

        # Si le texte source Llama chevauche le texte source déterministe
        if det_src and src_text_norm and len(det_src) >= 5 and len(src_text_norm) >= 5:
            if src_text_norm in det_src or det_src in src_text_norm:
                return None
            if fuzz.token_set_ratio(src_text_norm, det_src) >= 80:
                return None

        # Si même famille produit très spécifique déjà extraite pour une clause similaire
        tokens_candidat = set(_tokens_produit(label_norm))
        tokens_det = set(_tokens_produit(det_lbl))
        familles_communes = tokens_candidat & tokens_det
        familles_specifiques = familles_communes - {"blanc", "rouge", "bio", "vert", "noir", "uht", "frais", "1k", "5k", "10k"}
        if len(familles_specifiques) >= 2 and fuzz.token_set_ratio(src_text_norm, det_src) >= 60:
            return None

    # 2. Incompatibilités sémantiques métier
    raisons_incompatibilite = _incompatibilites_semantiques(src_text_norm, label_norm)
    if raisons_incompatibilite:
        return None

    # 3. Filtre sélectif généralisable : chevauchement sémantique
    # On calcule la correspondance floue entre le libellé officiel et la transcription / source_text
    fuzzy_src = 0
    if src_text_norm:
        fuzzy_src = fuzz.token_set_ratio(src_text_norm, label_norm)
    fuzzy_trans = fuzz.token_set_ratio(transcription_norm, label_norm)

    max_fuzzy = max(fuzzy_src, fuzzy_trans)

    if dans_cadencier:
        # Dans le cadencier : on tolère un chevauchement moyen (>= 50)
        if max_fuzzy < 50:
            return None
    else:
        # Hors cadencier : on exige un chevauchement très fort (>= 75)
        # et une quantité raisonnable
        if max_fuzzy < 75:
            return None
        if quantite > 30:
            return None

    return {
        "code": code,
        "quantity": quantite,
        "unit": unite_officielle,
        "label": label_officiel,
        "source_text": candidat.get("source_text") or "",
        "origine": "hybride_llama_additif_filtre",
    }


def fusionner_predictions(
    det_predictions: dict[str, Any],
    llama_predictions: dict[str, Any],
    transcriptions_dir: Path,
    cadencier_clients: dict[str, list[dict[str, Any]]],
    referentiel: dict[str, dict[str, Any]],
    unites_officielles: dict[str, str],
    limite_audios: int | None = None,
) -> dict[str, Any]:
    det_rows = det_predictions.get("rows", [])
    llama_rows_by_audio = {r["audio"]: r for r in llama_predictions.get("rows", [])}

    if limite_audios:
        det_rows = det_rows[:limite_audios]

    nouvelles_lignes_ajoutees = 0
    lignes_protegees_total = 0
    fusion_rows = []

    for det_row in det_rows:
        audio = det_row["audio"]
        client_code = str(det_row.get("client_code") or "").strip().upper()
        cadencier_client = cadencier_clients.get(client_code, [])
        codes_cadencier = {str(a.get("code_article") or "").strip().lstrip("0") for a in cadencier_client}

        lignes_det = list(det_row.get("lines", []))
        lignes_protegees_total += len(lignes_det)
        codes_existants = {str(l.get("code") or "").strip() for l in lignes_det}
        codes_existants.update({str(l.get("code") or "").strip().lstrip("0") for l in lignes_det})

        # Charger la transcription textuelle
        tpath = transcriptions_dir / f"{Path(audio).stem}__transcription.json"
        transcription_texte = ""
        if tpath.is_file():
            try:
                tdata = json.load(open(tpath, encoding="utf-8"))
                transcription_texte = tdata.get("texte") or tdata.get("transcription") or ""
            except Exception:
                transcription_texte = ""
        if not transcription_texte:
            transcription_texte = det_row.get("transcription") or ""

        transcription_norm = _normaliser_texte(transcription_texte)
        llama_row = llama_rows_by_audio.get(audio, {})

        lignes_finales = list(lignes_det)

        for candidat in llama_row.get("lines", []):
            code_candidat = str(candidat.get("code") or "").strip()
            code_norm = code_candidat.lstrip("0")
            if not code_candidat or code_candidat in codes_existants or code_norm in codes_existants:
                continue

            dans_cad = code_norm in codes_cadencier
            candidat_valide = valider_candidat_llama(
                candidat, transcription_norm, dans_cad, lignes_det, referentiel, unites_officielles
            )
            if candidat_valide:
                lignes_finales.append(candidat_valide)
                codes_existants.add(code_candidat)
                codes_existants.add(code_norm)
                nouvelles_lignes_ajoutees += 1

        nouvelle_row = dict(det_row)
        nouvelle_row["lines"] = lignes_finales
        fusion_rows.append(nouvelle_row)

    print(f"Fusion terminée : {len(fusion_rows)} audios traités.")
    print(f"  Lignes déterministes protégées : {lignes_protegees_total}")
    print(f"  Nouvelles lignes Llama additives acceptées : {nouvelles_lignes_ajoutees}")

    sortie = dict(det_predictions)
    sortie["prediction_mode"] = "hybrid_additive_anti_doublon_exp18"
    sortie["row_count"] = len(fusion_rows)
    sortie["rows"] = fusion_rows
    return sortie


def main() -> int:
    parser = argparse.ArgumentParser(description="Fusion hybride additive sélective et anti-doublons.")
    parser.add_argument("--base", type=Path, required=True, help="Fichier de prédictions déterministes (Exp 16b)")
    parser.add_argument("--llama", type=Path, required=True, help="Fichier de prédictions Llama (Exp 14b)")
    parser.add_argument("--transcriptions", type=Path, default=Path("resultats/transcriptions"), help="Dossier des transcriptions")
    parser.add_argument("--output", type=Path, required=True, help="Fichier de sortie des prédictions fusionnées")
    parser.add_argument("--smoke", action="store_true", help="Mode smoke test sur 3 audios")
    args = parser.parse_args()

    racine = PROJECT_ROOT
    referentiel = charger_referentiel(racine)
    unites = charger_unites_officielles(racine)
    cadencier_clients = extraction.charger_cadencier()

    det_data = json.load(open(args.base, encoding="utf-8"))
    llama_data = json.load(open(args.llama, encoding="utf-8"))

    limite = 3 if args.smoke else None
    fusion_data = fusionner_predictions(
        det_data, llama_data, args.transcriptions, cadencier_clients, referentiel, unites, limite_audios=limite
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(fusion_data, f, ensure_ascii=False, indent=2)
    print(f"Prédictions sauvegardées dans : {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
