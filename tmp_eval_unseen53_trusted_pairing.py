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
STRICT_TOP_MIN = 0.13
STRICT_MARGIN_MIN = 0.03


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


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_latest_unseen53(
    audio_inventory: dict[str, Any],
    corpus_semantic: dict[str, Any],
    corpus_current: dict[str, Any],
) -> list[dict[str, Any]]:
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
    return selected


def _candidate_orders_for_audio(
    all_orders: list[dict[str, Any]],
    audio_day: str,
    client_code: str,
) -> list[dict[str, Any]]:
    allowed_dates = permitted_order_dates(audio_day) if audio_day else set()
    candidates: list[dict[str, Any]] = []
    for order in all_orders:
        order_date = str(order.get("order_date") or "")
        if order_date not in allowed_dates:
            continue
        if client_code and str(order.get("client_code") or "").strip() != client_code:
            continue
        if not _norm_lines(list(order.get("lines") or [])):
            continue
        candidates.append(order)
    return candidates


def _pair_audio_strict(
    audio_row: dict[str, Any],
    all_orders: list[dict[str, Any]],
) -> dict[str, Any]:
    audio = str(audio_row.get("audio") or "")
    audio_day = str(audio_row.get("date") or "")
    client_code = str(audio_row.get("client_code") or "").strip()
    phone_unambiguous = bool(audio_row.get("phone_mapped_unambiguously"))

    if not client_code or not phone_unambiguous:
        return {
            "audio": audio,
            "status": "rejected",
            "reason": "client_unknown_or_ambiguous",
        }

    transcription = (transcription_for(audio) or "").strip()
    if not transcription:
        return {
            "audio": audio,
            "status": "rejected",
            "reason": "empty_transcription",
            "client_code": client_code,
        }

    candidates = _candidate_orders_for_audio(all_orders, audio_day, client_code)
    if not candidates:
        return {
            "audio": audio,
            "status": "rejected",
            "reason": "no_order_candidate_same_client_date",
            "client_code": client_code,
        }

    scored: list[tuple[float, dict[str, Any]]] = []
    for candidate in candidates:
        score = float(semantic_score(candidate, transcription))
        scored.append((score, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)

    top_score, top_order = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    margin = top_score - second_score if len(scored) > 1 else top_score

    accepted = (top_score >= STRICT_TOP_MIN) and (margin >= STRICT_MARGIN_MIN)
    if len(scored) == 1:
        accepted = top_score >= STRICT_TOP_MIN

    pairing_info = {
        "audio": audio,
        "client_code": client_code,
        "candidate_count": len(scored),
        "top_score": top_score,
        "second_score": second_score,
        "margin": margin,
        "selected_order_number": str(top_order.get("order_number") or ""),
        "selected_order_client": str(top_order.get("client_code") or ""),
    }

    if not accepted:
        pairing_info.update({"status": "rejected", "reason": "low_pairing_confidence"})
        return pairing_info

    pairing_info.update({"status": "accepted", "reason": "strict_client_date_semantic"})
    pairing_info["truth_row"] = {
        "audio": audio,
        "split": "validation",
        "truth_order_number": str(top_order.get("order_number") or ""),
        "truth_client": str(top_order.get("client_code") or ""),
        "truth_delivery_date": str(top_order.get("delivery_date") or ""),
        "truth_lines": _norm_lines(list(top_order.get("lines") or [])),
        "source": "trusted_pairing_client_date_semantic",
    }
    return pairing_info


def _evaluate_rows(extraction: Any, rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if not rows:
        return {
            "label": label,
            "audios": 0,
            "metrics": {},
            "duration_seconds": 0.0,
        }

    started = time.time()
    results = []
    for index, row in enumerate(rows, start=1):
        t0 = time.time()
        result = evaluate_audio(extraction, row)
        results.append(result)
        dt = time.time() - t0
        print(f"{label} DONE {index}/{len(rows)} in {dt:.2f}s :: {row['audio']}", flush=True)

    metrics = aggregate(results)
    return {
        "label": label,
        "audios": len(rows),
        "metrics": metrics,
        "duration_seconds": time.time() - started,
    }


def main() -> int:
    root = Path("/opt/emalo-autotune")
    private = root / "private"
    state_dir = root / "state"

    audio_inventory = _load_json(private / "audio_inventory.json")
    orders_inventory = _load_json(private / "orders_inventory.json")
    corpus_semantic = _load_json(private / "corpus-semantic-high-v1.json")
    corpus_current = _load_json(private / "corpus.json")

    selected = _build_latest_unseen53(audio_inventory, corpus_semantic, corpus_current)
    all_orders = list(orders_inventory.get("rows") or [])

    pairing_rows = [_pair_audio_strict(row, all_orders) for row in selected]

    accepted_rows = [row["truth_row"] for row in pairing_rows if row.get("status") == "accepted"]
    rejected_rows = [row for row in pairing_rows if row.get("status") != "accepted"]

    extraction, _ = _load_runtime()
    strict_eval = _evaluate_rows(extraction, accepted_rows, "STRICT")

    metrics = strict_eval.get("metrics") or {}
    passed90 = bool(
        int(metrics.get("audios", 0)) >= 1
        and float(metrics.get("product_recall", 0)) >= 0.90
        and float(metrics.get("product_precision", 0)) >= 0.90
        and float(metrics.get("exact_recall", 0)) >= 0.90
        and float(metrics.get("client_accuracy", 0)) >= 0.90
        and float(metrics.get("order_accuracy", 0)) >= 0.90
    )

    report = {
        "generated_at": time.time(),
        "no_truth_injection": True,
        "target_unseen_count": TARGET_COUNT,
        "pairing_policy": {
            "mode": "strict_client_date_semantic",
            "requires_known_client": True,
            "requires_phone_unambiguous": True,
            "top_score_min": STRICT_TOP_MIN,
            "margin_min": STRICT_MARGIN_MIN,
        },
        "pairing_summary": {
            "accepted": len(accepted_rows),
            "rejected": len(rejected_rows),
            "acceptance_rate": (len(accepted_rows) / TARGET_COUNT) if TARGET_COUNT else 0.0,
            "rejection_reasons": {
                reason: sum(1 for row in rejected_rows if row.get("reason") == reason)
                for reason in sorted({str(row.get("reason") or "") for row in rejected_rows})
            },
        },
        "strict_eval": strict_eval,
        "passed90": passed90,
        "pairings": pairing_rows,
    }

    output = state_dir / "UNSEEN53_TRUSTED_PAIRING_EVAL.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "accepted": len(accepted_rows),
                "rejected": len(rejected_rows),
                "metrics": metrics,
                "passed90": passed90,
                "report": str(output),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
