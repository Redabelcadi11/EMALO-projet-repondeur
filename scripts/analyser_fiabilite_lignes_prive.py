#!/usr/bin/env python3
"""Calibre en lecture seule les signaux de fiabilité des lignes prédites.

La vérité n'est ouverte qu'après gel d'un fichier public de prédictions. Le
script n'appelle aucun prédicteur/modèle et ne crée aucun artefact réutilisable
par le moteur.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable


def _number(value: Any) -> float | str | None:
    if value is None:
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return str(value)


def _key(line: dict[str, Any]) -> tuple[str, float | str | None, str]:
    return (
        str(line.get("code") or line.get("code_article") or ""),
        _number(line.get("quantity", line.get("quantite"))),
        str(line.get("unit") or line.get("unite") or "").upper(),
    )


def _score_bin(score: float) -> str:
    lower = int(score // 10) * 10
    if lower < 30:
        return "<30"
    if lower >= 80:
        return ">=80"
    return f"{lower}-{lower + 9}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--score", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    args = parser.parse_args()

    score_payload = json.loads(args.score.read_text(encoding="utf-8"))
    prediction_payload = json.loads(args.predictions.read_text(encoding="utf-8"))
    scored_by_audio = {
        str(row.get("audio") or ""): row
        for row in score_payload.get("results") or []
    }

    rows: list[dict[str, Any]] = []
    total_truth_lines = 0
    for public_row in prediction_payload.get("rows") or []:
        audio = str(public_row.get("audio") or "")
        scored = scored_by_audio[audio]
        truth = list(scored.get("truth") or [])
        total_truth_lines += len(truth)
        truth_exact = Counter(map(_key, truth))
        truth_codes = Counter(str(line.get("code") or "") for line in truth)
        products_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for product in public_row.get("diagnostics", {}).get("products") or []:
            selection = product.get("selection") or {}
            code = str(selection.get("code_article") or "")
            if code:
                products_by_code[code].append(product)

        enriched_lines: list[dict[str, Any]] = []
        remaining_exact = truth_exact.copy()
        remaining_codes = truth_codes.copy()
        for line in public_row.get("lines") or []:
            code = str(line.get("code") or "")
            candidates = products_by_code.get(code) or [{}]
            product = max(
                candidates,
                key=lambda item: (
                    bool(item.get("produit_fiable")),
                    not bool(item.get("ambigu")),
                    float((item.get("selection") or {}).get("score_global") or 0),
                ),
            )
            selection = product.get("selection") or {}
            line_key = _key(line)
            exact = remaining_exact[line_key] > 0
            if exact:
                remaining_exact[line_key] -= 1
            code_correct = remaining_codes[code] > 0
            if code_correct:
                remaining_codes[code] -= 1
            enriched_lines.append(
                {
                    "line": line,
                    "exact": exact,
                    "code_correct": code_correct,
                    "reliable": bool(product.get("produit_fiable")),
                    "ambiguous": bool(product.get("ambigu")),
                    "score_global": float(selection.get("score_global") or 0),
                    "score_text": float(selection.get("score_texte") or 0),
                    "client_history": bool(
                        selection.get("dans_cadencier_client")
                    ),
                    "selection_rule": str(
                        selection.get("regle_selection") or "?"
                    ),
                }
            )
        rows.append(
            {
                "audio": audio,
                "truth": truth,
                "lines": enriched_lines,
            }
        )

    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        for item in row["lines"]:
            keys = (
                f"reliable={item['reliable']}",
                f"ambiguous={item['ambiguous']}",
                f"score={_score_bin(item['score_global'])}",
                f"history={item['client_history']}",
                f"rule={item['selection_rule']}",
            )
            for group in keys:
                grouped[group]["predicted"] += 1
                grouped[group]["exact"] += int(item["exact"])
                grouped[group]["code_correct"] += int(item["code_correct"])

    def evaluate_filter(
        name: str,
        keep: Callable[[dict[str, Any]], bool],
    ) -> dict[str, Any]:
        predicted = exact = code_correct = exact_orders = 0
        for row in rows:
            kept = [item for item in row["lines"] if keep(item)]
            predicted += len(kept)
            exact += sum(bool(item["exact"]) for item in kept)
            code_correct += sum(bool(item["code_correct"]) for item in kept)
            exact_orders += int(
                Counter(_key(item["line"]) for item in kept)
                == Counter(map(_key, row["truth"]))
            )
        return {
            "filter": name,
            "predicted_lines": predicted,
            "exact_line_precision": round(exact / predicted, 6)
            if predicted else 0.0,
            "exact_line_recall": round(exact / total_truth_lines, 6)
            if total_truth_lines else 0.0,
            "code_precision": round(code_correct / predicted, 6)
            if predicted else 0.0,
            "exact_orders": exact_orders,
        }

    filters = [evaluate_filter("all", lambda item: True)]
    filters.append(
        evaluate_filter("reliable_only", lambda item: item["reliable"])
    )
    for threshold in range(30, 81, 5):
        filters.append(
            evaluate_filter(
                f"reliable_or_score>={threshold}",
                lambda item, threshold=threshold: (
                    item["reliable"]
                    or item["score_global"] >= threshold
                ),
            )
        )
        filters.append(
            evaluate_filter(
                f"drop_ambiguous_below_{threshold}",
                lambda item, threshold=threshold: not (
                    item["ambiguous"]
                    and item["score_global"] < threshold
                ),
            )
        )

    group_output: list[dict[str, Any]] = []
    for group, values in grouped.items():
        predicted = values["predicted"]
        group_output.append(
            {
                "group": group,
                **dict(values),
                "exact_precision": round(values["exact"] / predicted, 6),
                "code_precision": round(
                    values["code_correct"] / predicted, 6
                ),
            }
        )
    group_output.sort(key=lambda item: item["group"])
    print(
        json.dumps(
            {
                "truth_lines": total_truth_lines,
                "groups": group_output,
                "filters": filters,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
