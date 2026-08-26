from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, "/opt/emalo-autotune/bin")

from emalo_autotune import _load_runtime  # noqa: E402
from emalo_eval_runner_semantic import aggregate, evaluate_audio  # noqa: E402
from emalo_semantic_matcher import (  # noqa: E402
    permitted_order_dates,
    semantic_score,
    transcription_for,
)

TARGET_COUNT = 53


def _norm_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for line in lines:
        code = str(line.get("code") or line.get("code_article") or "").strip()
        if not code:
            continue
        normalized.append(
            {
                "code": code,
                "quantity": line.get("quantity", line.get("quantite")),
                "unit": str(line.get("unit") or line.get("unite") or "").strip(),
                "label": str(line.get("label") or line.get("libelle") or "").strip(),
            }
        )
    return normalized


def main() -> int:
    root = Path("/opt/emalo-autotune")
    private = root / "private"
    state_dir = root / "state"

    audio_inventory = json.loads((private / "audio_inventory.json").read_text(encoding="utf-8"))
    orders_inventory = json.loads((private / "orders_inventory.json").read_text(encoding="utf-8"))
    decisions_payload = json.loads((private / "semantic-qwen-decisions.json").read_text(encoding="utf-8"))
    corpus_semantic = json.loads((private / "corpus-semantic-high-v1.json").read_text(encoding="utf-8"))
    corpus_current = json.loads((private / "corpus.json").read_text(encoding="utf-8"))

    used_audios = {
        str(row.get("audio") or "")
        for row in (corpus_semantic.get("rows") or []) + (corpus_current.get("rows") or [])
        if str(row.get("audio") or "")
    }

    audio_rows = list(audio_inventory.get("rows") or [])
    audio_rows.sort(key=lambda row: str(row.get("datetime") or row.get("audio") or ""), reverse=True)

    unseen_rows = [row for row in audio_rows if str(row.get("audio") or "") not in used_audios]
    selected = unseen_rows[:TARGET_COUNT]
    if len(selected) < TARGET_COUNT:
        raise RuntimeError(f"Cannot find {TARGET_COUNT} unseen audios, found={len(selected)}")

    orders = list(orders_inventory.get("rows") or [])
    order_by_number = {
        str(order.get("order_number") or ""): order
        for order in orders
        if str(order.get("order_number") or "")
    }

    decisions_rows = decisions_payload.get("rows") if isinstance(decisions_payload, dict) else decisions_payload
    decision_by_audio = {
        str(row.get("audio") or ""): row
        for row in (decisions_rows or [])
        if str(row.get("audio") or "")
    }

    eval_rows: list[dict[str, Any]] = []
    pairing_debug: list[dict[str, Any]] = []

    for row in selected:
        audio = str(row.get("audio") or "")
        audio_day = str(row.get("date") or "")
        decision = decision_by_audio.get(audio) or {}
        decided_order = str(decision.get("order_number") or "").strip()

        chosen_order: dict[str, Any] | None = None
        pairing_source = ""
        pairing_confidence = None

        if decided_order and decided_order != "NONE":
            chosen_order = order_by_number.get(decided_order)
            if chosen_order and _norm_lines(list(chosen_order.get("lines") or [])):
                pairing_source = "semantic_qwen_decision"
                try:
                    pairing_confidence = float(decision.get("confidence"))
                except (TypeError, ValueError):
                    pairing_confidence = None

        if chosen_order is None:
            transcription = transcription_for(audio)
            allowed_dates = permitted_order_dates(audio_day) if audio_day else set()
            candidates = [
                order
                for order in orders
                if str(order.get("order_date") or "") in allowed_dates
            ]
            scored: list[tuple[float, dict[str, Any]]] = []
            for candidate in candidates:
                lines = list(candidate.get("lines") or [])
                if not _norm_lines(lines):
                    continue
                score = semantic_score(candidate, transcription) if transcription else 0.0
                scored.append((float(score), candidate))
            if scored:
                scored.sort(key=lambda item: item[0], reverse=True)
                pairing_confidence = scored[0][0]
                chosen_order = scored[0][1]
                pairing_source = "fallback_semantic_top1"

        if chosen_order is None:
            pairing_debug.append(
                {
                    "audio": audio,
                    "status": "unpaired",
                    "decision_order": decided_order,
                }
            )
            continue

        truth_lines = _norm_lines(list(chosen_order.get("lines") or []))
        if not truth_lines:
            pairing_debug.append(
                {
                    "audio": audio,
                    "status": "empty_truth_lines",
                    "order_number": str(chosen_order.get("order_number") or ""),
                }
            )
            continue

        eval_rows.append(
            {
                "audio": audio,
                "split": "validation",
                "truth_order_number": str(chosen_order.get("order_number") or ""),
                "truth_client": str(chosen_order.get("client_code") or ""),
                "truth_delivery_date": str(chosen_order.get("delivery_date") or ""),
                "truth_lines": truth_lines,
                "source": "nextcloud_unseen53_no_leak",
                "pairing_confidence": pairing_confidence,
                "pairing_source": pairing_source,
            }
        )
        pairing_debug.append(
            {
                "audio": audio,
                "status": "paired",
                "order_number": str(chosen_order.get("order_number") or ""),
                "pairing_source": pairing_source,
                "pairing_confidence": pairing_confidence,
            }
        )

    if len(eval_rows) < TARGET_COUNT:
        raise RuntimeError(f"Pairing incomplete: {len(eval_rows)}/{TARGET_COUNT}")

    extraction, _ = _load_runtime()
    results = []
    for index, eval_row in enumerate(eval_rows, start=1):
        started = time.time()
        result = evaluate_audio(extraction, eval_row)
        results.append(result)
        elapsed = time.time() - started
        print(f"DONE {index}/{TARGET_COUNT} in {elapsed:.2f}s :: {eval_row['audio']}", flush=True)

    metrics = aggregate(results)
    passed90 = bool(
        int(metrics.get("audios", 0)) >= TARGET_COUNT
        and float(metrics.get("product_recall", 0)) >= 0.90
        and float(metrics.get("product_precision", 0)) >= 0.90
        and float(metrics.get("exact_recall", 0)) >= 0.90
        and float(metrics.get("client_accuracy", 0)) >= 0.90
        and float(metrics.get("order_accuracy", 0)) >= 0.90
    )

    report = {
        "generated_at": time.time(),
        "target_count": TARGET_COUNT,
        "no_truth_injection": True,
        "selection_policy": "latest unseen audios excluding current corpora",
        "selection_count": len(eval_rows),
        "metrics": metrics,
        "passed90": passed90,
        "pairings": pairing_debug,
    }

    output = state_dir / "UNSEEN53_NOLEAK_EVAL.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"metrics": metrics, "passed90": passed90, "report": str(output)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
