#!/usr/bin/env python3
"""Diagnostic agrégé d'un score privé, sans produire de nouvelle prédiction.

Ce script doit être exécuté uniquement après gel des prédictions. Il ne charge
aucun composant de prédiction, n'appelle aucun modèle et n'écrit aucun fichier.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _number(value: Any) -> float | str | None:
    if value is None:
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return str(value)


def _line_key(line: dict[str, Any]) -> tuple[str, float | str | None, str]:
    return (
        str(line.get("code") or ""),
        _number(line.get("quantity")),
        str(line.get("unit") or "").upper(),
    )


def _code_counter(lines: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(line.get("code") or "") for line in lines)


def _rank_bucket(rank: Any) -> str:
    if rank is None:
        return "absent"
    try:
        numeric = int(rank)
    except (TypeError, ValueError):
        return str(rank)
    if numeric == 1:
        return "1"
    if numeric <= 3:
        return "2-3"
    if numeric <= 5:
        return "4-5"
    if numeric <= 10:
        return "6-10"
    return ">10"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("score", type=Path)
    parser.add_argument("--near-limit", type=int, default=4)
    args = parser.parse_args()

    payload = json.loads(args.score.read_text(encoding="utf-8"))
    rows = list(payload.get("results") or [])
    aggregate: Counter[str] = Counter()
    rank_buckets: Counter[str] = Counter()
    causes: Counter[str] = Counter()
    near_orders: list[dict[str, Any]] = []
    error_distance: Counter[int] = Counter()
    quantity_patterns: Counter[str] = Counter()
    quantity_mismatch_details: list[dict[str, Any]] = []

    for row in rows:
        truth = list(row.get("truth") or [])
        predicted = list(row.get("predicted") or [])
        missing = list(row.get("missing") or [])
        extra = list(row.get("extra") or [])
        truth_codes = _code_counter(truth)
        predicted_codes = _code_counter(predicted)
        exact_code_overlap = sum((truth_codes & predicted_codes).values())

        aggregate["audios"] += 1
        aggregate["truth_lines"] += len(truth)
        aggregate["predicted_lines"] += len(predicted)
        aggregate["exact_reference_occurrences"] += exact_code_overlap
        aggregate["orders_exact_reference_multiset"] += int(
            truth_codes == predicted_codes
        )
        aggregate["orders_exact_reference_set"] += int(
            set(truth_codes) == set(predicted_codes)
        )
        aggregate["orders_exact_lines"] += int(
            Counter(map(_line_key, truth)) == Counter(map(_line_key, predicted))
        )

        missing_codes = _code_counter(missing)
        extra_codes = _code_counter(extra)
        same_code_mismatches = sum((missing_codes & extra_codes).values())
        aggregate["missing_lines"] += len(missing)
        aggregate["extra_lines"] += len(extra)
        aggregate["same_code_quantity_or_unit_mismatches"] += same_code_mismatches
        aggregate["missing_reference_occurrences"] += (
            len(missing) - same_code_mismatches
        )
        aggregate["extra_reference_occurrences"] += (
            len(extra) - same_code_mismatches
        )

        for code in sorted(set(missing_codes) & set(extra_codes)):
            missing_same = [
                line for line in missing
                if str(line.get("code") or "") == code
            ]
            extra_same = [
                line for line in extra
                if str(line.get("code") or "") == code
            ]
            for expected, observed in zip(missing_same, extra_same):
                expected_quantity = _number(expected.get("quantity"))
                observed_quantity = _number(observed.get("quantity"))
                expected_unit = str(expected.get("unit") or "").upper()
                observed_unit = str(observed.get("unit") or "").upper()
                ratio: float | None = None
                if (
                    isinstance(expected_quantity, float)
                    and isinstance(observed_quantity, float)
                    and observed_quantity
                ):
                    ratio = round(expected_quantity / observed_quantity, 4)
                pattern = (
                    f"{observed_quantity}{observed_unit}"
                    f"->{expected_quantity}{expected_unit}"
                    f"|ratio={ratio}"
                )
                quantity_patterns[pattern] += 1
                quantity_mismatch_details.append(
                    {
                        "audio": row.get("audio"),
                        "code": code,
                        "observed_quantity": observed_quantity,
                        "observed_unit": observed_unit,
                        "expected_quantity": expected_quantity,
                        "expected_unit": expected_unit,
                        "ratio_expected_over_observed": ratio,
                    }
                )

        ranks = row.get("expected_candidate_ranks") or {}
        for line in missing:
            code = str(line.get("code") or "")
            rank_buckets[_rank_bucket(ranks.get(code))] += 1

        for cause in row.get("causes") or []:
            causes[str(cause)] += 1

        distance = len(missing) + len(extra)
        error_distance[distance] += 1
        if 0 < distance <= args.near_limit:
            near_orders.append(
                {
                    "audio": row.get("audio"),
                    "truth_lines": len(truth),
                    "predicted_lines": len(predicted),
                    "missing": len(missing),
                    "extra": len(extra),
                    "same_code_quantity_or_unit": same_code_mismatches,
                    "causes": list(row.get("causes") or []),
                }
            )

    truth_lines = aggregate["truth_lines"]
    aggregate["reference_occurrence_recall"] = round(
        aggregate["exact_reference_occurrences"] / truth_lines, 6
    ) if truth_lines else 0.0
    aggregate["quantity_or_unit_error_share_of_missing"] = round(
        aggregate["same_code_quantity_or_unit_mismatches"]
        / aggregate["missing_lines"],
        6,
    ) if aggregate["missing_lines"] else 0.0

    output = {
        "score_file": args.score.name,
        "aggregate": dict(aggregate),
        "candidate_rank_for_missing_lines": dict(
            sorted(rank_buckets.items())
        ),
        "causes_by_audio": dict(causes.most_common()),
        "quantity_mismatch_patterns": dict(quantity_patterns.most_common()),
        "quantity_mismatch_details": quantity_mismatch_details,
        "order_error_distance": {
            str(key): value for key, value in sorted(error_distance.items())
        },
        "near_orders": sorted(
            near_orders,
            key=lambda item: (
                item["missing"] + item["extra"],
                str(item["audio"]),
            ),
        ),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
