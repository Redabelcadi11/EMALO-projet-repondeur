from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/emalo-autotune/bin")
from emalo_autotune import _load_runtime  # noqa: E402
from emalo_eval_runner_semantic import aggregate, evaluate_audio  # noqa: E402


def main() -> int:
    root = Path("/opt/emalo-autotune")
    dataset = json.loads((root / "private" / "corpus-semantic-high-v1.json").read_text(encoding="utf-8"))
    rows = {str(row["audio"]): row for row in (dataset.get("rows") or [])}
    audios = [
        str(row["audio"])
        for row in (dataset.get("rows") or [])
        if row.get("split") == "validation"
    ]

    print(f"audios_validation100={len(audios)}", flush=True)

    extraction, _ = _load_runtime()
    results = []
    for index, audio in enumerate(audios, start=1):
        started = time.time()
        result = evaluate_audio(extraction, rows[audio])
        results.append(result)
        elapsed = time.time() - started
        print(f"DONE {index}/{len(audios)} in {elapsed:.2f}s :: {audio}", flush=True)

    metrics = aggregate(results)
    passed = bool(
        int(metrics.get("audios", 0)) >= 100
        and float(metrics.get("product_recall", 0)) >= 0.90
        and float(metrics.get("product_precision", 0)) >= 0.90
        and float(metrics.get("exact_recall", 0)) >= 0.90
        and float(metrics.get("client_accuracy", 0)) >= 0.90
        and float(metrics.get("order_accuracy", 0)) >= 0.90
    )

    print(json.dumps({"metrics": metrics, "passed90": passed}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
