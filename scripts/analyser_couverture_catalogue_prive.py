#!/usr/bin/env python3
"""Mesure après prédiction la couverture de la vérité par les données autorisées.

Le client utilisé est celui prédit publiquement, jamais le client cible. Aucune
référence cible n'est transmise à un prédicteur ou à un modèle.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.arbitrer_predictions_llama_local import _load_resources
from src.llama_product_resolver import build_authorized_catalogue


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("score", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.score.read_text(encoding="utf-8"))
    cadencier, global_catalogue, references = _load_resources()
    aggregate: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    clients_cache: dict[str, dict[str, dict[str, Any]]] = {}

    for row in payload.get("results") or []:
        predicted_client = str(row.get("predicted_client") or "")
        catalogue = clients_cache.get(predicted_client)
        if catalogue is None:
            catalogue = build_authorized_catalogue(
                global_catalogue,
                cadencier.get(predicted_client, []),
                references,
            )
            clients_cache[predicted_client] = catalogue

        aggregate["audios"] += 1
        all_available = True
        all_in_history = True
        missing_keys = {
            (
                str(line.get("code") or ""),
                line.get("quantity"),
                str(line.get("unit") or ""),
            )
            for line in row.get("missing") or []
        }
        for truth_line in row.get("truth") or []:
            code = str(truth_line.get("code") or "")
            entry = catalogue.get(code)
            available = entry is not None
            in_history = bool((entry or {}).get("in_client_history"))
            aggregate["truth_lines"] += 1
            aggregate["truth_available"] += int(available)
            aggregate["truth_in_client_history"] += int(in_history)
            all_available &= available
            all_in_history &= in_history
            if available:
                sources[str(entry.get("source") or "?")] += 1

            key = (
                code,
                truth_line.get("quantity"),
                str(truth_line.get("unit") or ""),
            )
            if key in missing_keys:
                aggregate["missing_lines"] += 1
                aggregate["missing_available"] += int(available)
                aggregate["missing_in_client_history"] += int(in_history)

        aggregate["orders_all_truth_available"] += int(all_available)
        aggregate["orders_all_truth_in_client_history"] += int(all_in_history)

    for numerator, denominator, key in (
        ("truth_available", "truth_lines", "truth_available_rate"),
        (
            "truth_in_client_history",
            "truth_lines",
            "truth_in_client_history_rate",
        ),
        ("missing_available", "missing_lines", "missing_available_rate"),
        (
            "missing_in_client_history",
            "missing_lines",
            "missing_in_client_history_rate",
        ),
    ):
        aggregate[key] = round(
            aggregate[numerator] / aggregate[denominator],
            6,
        ) if aggregate[denominator] else 0.0

    print(
        json.dumps(
            {
                "aggregate": dict(aggregate),
                "truth_entry_sources": dict(sources.most_common()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
