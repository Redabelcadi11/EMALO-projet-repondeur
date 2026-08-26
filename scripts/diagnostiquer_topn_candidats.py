#!/usr/bin/env python3
"""
Diagnostic Top-N de la chaine de reconnaissance produit - EVALUATEUR
UNIQUEMENT, apres gel des predictions.

Ce script ne modifie, ne regenere et ne relance AUCUNE prediction. Il lit
uniquement :
- des artefacts de prediction deja figes (Exp21 et/ou Exp25) ;
- le corpus prive de verite ERP (jamais transmis au predicteur ni a Llama).

Il mesure, cote evaluateur seulement :
- le rappel candidat Top-1/3/5/10, en deux variantes :
  * end-to-end : sur les 359 lignes de verite du split development ;
  * conditionnel : restreint aux lignes de verite dont la commande audio a
    reellement genere au moins un segment produit avec des candidats
    (exclut les commandes ou aucun segment n'a ete cree du tout - la
    denominateur ne peut donc pas etre gonfle artificiellement par ces
    echecs de segmentation) ;
- pour chaque ligne de verite manquante au niveau CODE (le code n'apparait
  dans aucune ligne predite finale, independamment de la quantite/unite -
  objectif explicite de cette phase : precision/rappel PRODUIT), une
  categorie de cause exclusive :
    1. aucun_segment_produit_cree : la commande entiere n'a genere aucun
       segment avec candidats (echec de segmentation/ASR en amont) ;
    2. segment_cree_absent_top10 : un segment existe pour cette commande,
       mais le bon code n'apparait dans aucun pool de candidats a un rang
       <= 10 (echec de recherche/generation de candidats) ;
    3. present_top10_absent_top5 : le bon code est present a un rang 6-10
       dans au moins un pool de candidats (echec de reordonnancement) ;
    4. present_top5_mauvais_top1 : le bon code est present a un rang 1-5
       dans au moins un pool de candidats, mais n'a pas ete retenu dans la
       selection finale (echec de scoring/selection final, le candidat
       correct etait pourtant disponible pres du sommet).
- separement, le nombre de lignes predites en trop (faux segment / faux
  produit surnumeraire) au niveau code : predicted_codes - truth_codes.

Le rang d'un code pour une commande est le meilleur rang (le plus bas)
auquel ce code apparait dans N'IMPORTE LEQUEL des pools de candidats de
cette commande (reutilise _candidate_rank, deja utilise par
evaluer_predictions_sans_fuite.py, pour rester coherent avec le reste du
projet). Aucune tentative n'est faite pour aligner un segment specifique a
une ligne de verite specifique : aucune information de ce type n'existe
dans le pipeline (le rapprochement final se fait par multiset de codes, pas
par alignement ligne-a-ligne), donc le rang "au niveau commande" est le
choix le plus honnete et le moins arbitraire disponible.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation_metrics import (  # noqa: E402
    canonical_lines,
    code_counter,
    canonical_code,
    normalize_text,
    _candidate_rank,
)
from rapidfuzz import fuzz  # noqa: E402

RANK_THRESHOLDS = (1, 3, 5, 10)
SEUIL_SEGMENT_PERTINENT = 40  # chevauchement lexical libelle-vs-segment, diagnostic uniquement


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def diagnostiquer(predictions_path: Path, truth_rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    predictions = load_json(predictions_path)
    pred_by_audio = {str(row.get("audio") or ""): row for row in predictions.get("rows", [])}

    total_truth_lines = 0
    hits_end_to_end = {n: 0 for n in RANK_THRESHOLDS}
    conditional_denominator = 0
    hits_conditional = {n: 0 for n in RANK_THRESHOLDS}

    cat_counts: Counter[str] = Counter()
    cat_examples: dict[str, list[dict[str, Any]]] = {
        "aucun_segment_produit_cree": [],
        "omission_segmentation_probable": [],
        "recherche_candidats_insuffisante": [],
        "present_top10_absent_top5": [],
        "present_top5_mauvais_top1": [],
    }
    extra_count = 0
    extra_examples: list[dict[str, Any]] = []
    audios_zero_segment = 0

    for truth_row in truth_rows:
        audio = str(truth_row.get("audio") or "")
        truth_lines = canonical_lines(truth_row.get("truth_lines") or [])
        truth_codes = code_counter(truth_lines)
        if not truth_codes:
            continue
        label_by_code = {l["code"]: l.get("label") or "" for l in truth_lines}

        pred_row = pred_by_audio.get(audio)
        diag = (pred_row or {}).get("diagnostics") or {}
        products = diag.get("products") or []
        has_any_candidats = any(p.get("candidats") for p in products if p.get("selection"))
        if not has_any_candidats:
            audios_zero_segment += 1
        segment_textes_norm = [
            normalize_text(p.get("texte_source") or "") for p in products if p.get("selection")
        ]

        predicted_lines = canonical_lines((pred_row or {}).get("lines") or [])
        predicted_codes = code_counter(predicted_lines)

        for code, truth_count in truth_codes.items():
            rank = _candidate_rank(diag, code) if pred_row else None
            for _ in range(truth_count):
                total_truth_lines += 1
                for n in RANK_THRESHOLDS:
                    if rank is not None and rank <= n:
                        hits_end_to_end[n] += 1
                if has_any_candidats:
                    conditional_denominator += 1
                    for n in RANK_THRESHOLDS:
                        if rank is not None and rank <= n:
                            hits_conditional[n] += 1

        missing_codes = truth_codes - predicted_codes
        for code, miss_count in missing_codes.items():
            rank = _candidate_rank(diag, code) if pred_row else None
            label_norm = normalize_text(label_by_code.get(code, ""))
            best_overlap = (
                max((fuzz.token_set_ratio(label_norm, s) for s in segment_textes_norm), default=0)
                if label_norm and segment_textes_norm
                else 0
            )
            for _ in range(miss_count):
                if not has_any_candidats:
                    cat = "aucun_segment_produit_cree"
                elif rank is None or rank > 10:
                    # Aucune information d'alignement segment<->ligne de verite n'existe
                    # dans le pipeline : on approxime avec le chevauchement lexical
                    # (diagnostic uniquement) entre le libelle officiel de la ligne
                    # manquante et TOUS les segments de la commande. En dessous du
                    # seuil, aucun segment ne ressemble a ce produit : l'omission est
                    # plus probablement une segmentation/ASR manquee pour CETTE ligne
                    # precise (d'autres lignes de la meme commande ont pu, elles, etre
                    # correctement segmentees) qu'un echec de recherche catalogue.
                    cat = (
                        "recherche_candidats_insuffisante"
                        if best_overlap >= SEUIL_SEGMENT_PERTINENT
                        else "omission_segmentation_probable"
                    )
                elif rank > 5:
                    cat = "present_top10_absent_top5"
                else:
                    cat = "present_top5_mauvais_top1"
                cat_counts[cat] += 1
                if len(cat_examples[cat]) < 8:
                    cat_examples[cat].append(
                        {
                            "audio": audio,
                            "code": code,
                            "label": label_by_code.get(code, ""),
                            "best_rank": rank,
                            "best_segment_overlap": best_overlap,
                        }
                    )

        extra_codes = predicted_codes - truth_codes
        for code, extra_n in extra_codes.items():
            extra_count += extra_n
            if len(extra_examples) < 8:
                extra_examples.append({"audio": audio, "code": code, "count": extra_n})

    def recall_table(hits: dict[int, int], denom: int) -> dict[str, Any]:
        return {
            f"top_{n}": {
                "hits": hits[n],
                "total": denom,
                "recall": round(hits[n] / denom, 4) if denom else None,
            }
            for n in RANK_THRESHOLDS
        }

    return {
        "label": label,
        "predictions_file": str(predictions_path),
        "truth_lines_total": total_truth_lines,
        "audios_with_zero_segment": audios_zero_segment,
        "end_to_end_candidate_recall": recall_table(hits_end_to_end, total_truth_lines),
        "conditional_candidate_recall": recall_table(hits_conditional, conditional_denominator),
        "missing_code_level_causes": {
            "counts": dict(cat_counts),
            "total_missing_code_level": sum(cat_counts.values()),
            "examples": cat_examples,
        },
        "extra_false_positive_codes": {
            "count": extra_count,
            "examples": extra_examples,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--splits", default="development")
    parser.add_argument(
        "--predictions",
        action="append",
        nargs=2,
        metavar=("LABEL", "PATH"),
        required=True,
        help="Peut etre repete : --predictions exp21 chemin.json --predictions exp25 chemin2.json",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    corpus = load_json(args.corpus)
    selected_splits = {s.strip() for s in args.splits.split(",") if s.strip()}
    truth_rows = [
        row
        for row in corpus.get("rows") or []
        if not selected_splits or str(row.get("split") or "unspecified") in selected_splits
    ]

    resultats = []
    for label, path_str in args.predictions:
        resultats.append(diagnostiquer(Path(path_str), truth_rows, label))

    sortie = {
        "schema": "emalo-topn-diagnostic/v1",
        "truth_rows_considered": len(truth_rows),
        "selected_splits": sorted(selected_splits) if selected_splits else ["all"],
        "resultats": resultats,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False, indent=2)

    print(json.dumps(sortie, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
