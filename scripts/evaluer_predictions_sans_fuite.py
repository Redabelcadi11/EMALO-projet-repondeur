#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation_metrics import evaluate_rows


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Objet JSON attendu: {path}")
    return value


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare hors du predicteur les sorties a la verite ERP."
    )
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--splits", default="")
    args = parser.parse_args()

    corpus = _read_json(args.corpus)
    predictions = _read_json(args.predictions)
    if predictions.get("schema") != "emalo-evaluation-predictions/v1":
        raise ValueError("Schema de predictions invalide.")
    if predictions.get("truth_received_by_predictor") is not False:
        raise RuntimeError("Le predicteur ne certifie pas l'absence de verite cible.")
    selected_splits = {
        item.strip() for item in args.splits.split(",") if item.strip()
    }
    truth_rows = [
        row
        for row in corpus.get("rows") or []
        if not selected_splits
        or str(row.get("split") or "unspecified") in selected_splits
    ]
    results, metrics, by_split = evaluate_rows(
        truth_rows, list(predictions.get("rows") or [])
    )
    production = {
        "metric": "automation_order_accuracy",
        "target": 0.90,
        "minimum_audios": 20,
        "audios": metrics["audios"],
        "value": metrics["automation_order_accuracy"],
        "achieved": bool(
            metrics["audios"] >= 20
            and metrics["automation_order_accuracy"] >= 0.90
        ),
    }
    report = {
        "schema": "emalo-evaluation-report/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus_method": corpus.get("method") or "",
        "matching_uses_program_product_predictions": corpus.get(
            "matching_uses_program_product_predictions"
        ),
        "truth_received_by_predictor": False,
        "prediction_application_fingerprint": predictions.get(
            "application_fingerprint"
        ),
        "selected_splits": sorted(selected_splits) if selected_splits else ["all"],
        "metrics": metrics,
        "metrics_by_split": by_split,
        "production_gate": production,
        "results": results,
    }
    _atomic_json(args.output, report)
    print(
        json.dumps(
            {
                "metrics": metrics,
                "metrics_by_split": by_split,
                "production_gate": production,
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
