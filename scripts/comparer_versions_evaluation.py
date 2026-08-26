#!/usr/bin/env python3
"""Compare deux rapports produits par le scoreur prive.

Cet outil appartient au processus de score, jamais au processus de prediction.
Il explique les lignes ajoutees/retirees et indique si le changement est un
gain ou une regression par rapport a la verite du lot de developpement.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def _quantity(value: Any) -> str:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value or "")
    return format(decimal.normalize(), "f")


def _line_key(line: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(line.get("code") or "").upper(),
        _quantity(line.get("quantity")),
        str(line.get("unit") or "").upper(),
    )


def _details_source(result: dict[str, Any], key: tuple[str, str, str]) -> dict[str, Any]:
    for product in (result.get("diagnostics") or {}).get("products") or []:
        selection = product.get("selection") or {}
        product_key = (
            str(selection.get("code_article") or "").upper(),
            _quantity(product.get("quantite_resolue")),
            str(product.get("unite_resolue") or "").upper(),
        )
        if product_key == key:
            return {
                "source": str(product.get("texte_source") or ""),
                "product_text": str(product.get("produit_normalise") or ""),
                "spoken_quantity": product.get("quantite_principale"),
                "text_score": selection.get("score_texte"),
                "in_client_schedule": bool(selection.get("dans_cadencier_client")),
                "selection_rule": selection.get("regle_selection"),
            }
    return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    args = parser.parse_args()
    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    before_by_audio = {row["audio"]: row for row in before.get("results", [])}
    after_by_audio = {row["audio"]: row for row in after.get("results", [])}
    if set(before_by_audio) != set(after_by_audio):
        raise ValueError("Les deux rapports ne couvrent pas les memes audios.")

    changes: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for audio in sorted(before_by_audio):
        old = before_by_audio[audio]
        new = after_by_audio[audio]
        truth = Counter(_line_key(line) for line in new.get("truth", []))
        old_lines = Counter(_line_key(line) for line in old.get("predicted", []))
        new_lines = Counter(_line_key(line) for line in new.get("predicted", []))
        for direction, delta, source_result in (
            ("removed", old_lines - new_lines, old),
            ("added", new_lines - old_lines, new),
        ):
            for key, occurrences in delta.items():
                exact_truth = truth[key] > 0
                category = (
                    "regression" if direction == "removed" and exact_truth
                    else "gain" if direction == "removed"
                    else "gain" if exact_truth
                    else "regression"
                )
                counts[f"{direction}_{category}"] += occurrences
                changes.append({
                    "audio": audio,
                    "direction": direction,
                    "effect": category,
                    "occurrences": occurrences,
                    "line": {"code": key[0], "quantity": key[1], "unit": key[2]},
                    **_details_source(source_result, key),
                })
    print(json.dumps({"counts": counts, "changes": changes}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
