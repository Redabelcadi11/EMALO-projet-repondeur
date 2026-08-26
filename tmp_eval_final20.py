from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/emalo-autotune/bin")
from emalo_autotune import _load_runtime, aggregate, evaluate_audio  # noqa: E402


def main() -> int:
    root = Path("/opt/emalo-autotune")
    dataset = json.loads((root / "private" / "corpus.json").read_text(encoding="utf-8"))
    rows = {str(row["audio"]): row for row in (dataset.get("rows") or [])}
    audios = [
        str(row["audio"])
        for row in (dataset.get("rows") or [])
        if row.get("split") == "final_test"
    ]

    print(f"audios_final20={len(audios)}", flush=True)

    extraction, _ = _load_runtime()
    results = []
    for index, audio in enumerate(audios, start=1):
        started = time.time()
        result = evaluate_audio(extraction, rows[audio])
        results.append(result)
        elapsed = time.time() - started
        print(f"DONE {index}/{len(audios)} in {elapsed:.2f}s :: {audio}", flush=True)

    metrics = aggregate(results)
    perfect_orders = sum(
        int(result.get("truth_count", 0))
        == int(result.get("predicted_count", 0))
        == int(result.get("exact_matches", 0))
        for result in results
    )
    metrics["perfect_orders"] = perfect_orders
    metrics["order_accuracy"] = round(perfect_orders / len(results), 4) if results else 0.0

    passed = bool(
        int(metrics.get("audios", 0)) >= 20
        and float(metrics.get("product_recall", 0)) >= 0.90
        and float(metrics.get("product_precision", 0)) >= 0.90
        and float(metrics.get("exact_recall", 0)) >= 0.90
        and float(metrics.get("order_accuracy", 0)) >= 0.90
    )

    print(json.dumps({"metrics": metrics, "passed90": passed}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
