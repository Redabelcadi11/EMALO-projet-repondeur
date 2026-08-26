from __future__ import annotations

import re
import unicodedata
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


UNIT_ALIASES = {
    "BARQUETTE": "BARQ",
    "BARQUETTES": "BARQ",
    "BIDON": "BID",
    "BIDONS": "BID",
    "BOI": "BOITE",
    "BOX": "BOITE",
    "CARTON": "CAR",
    "CARTONS": "CAR",
    "COLIS": "COL",
    "PIECE": "PI",
    "PIECES": "PI",
    "PCE": "PI",
    "POCH": "POC",
    "POCHE": "POC",
    "POCHES": "POC",
    "SACHET": "SACH",
    "SACHETS": "SACH",
    "UNITE": "PI",
    "UNITES": "PI",
}


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text.strip().casefold())


def canonical_quantity(value: Any) -> str:
    raw = str(value if value is not None else "").strip().replace(",", ".")
    if not raw:
        return ""
    try:
        number = Decimal(raw)
    except InvalidOperation:
        return normalize_text(raw)
    normalized = format(number.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return "0" if normalized in {"", "-0"} else normalized


def canonical_unit(value: Any) -> str:
    unit = normalize_text(value).upper()
    return UNIT_ALIASES.get(unit, unit)


def canonical_code(value: Any) -> str:
    return str(value or "").strip().upper()


def canonical_line(line: dict[str, Any]) -> dict[str, str]:
    return {
        "code": canonical_code(
            line.get("code")
            or line.get("code_article")
            or line.get("article_code")
        ),
        "quantity": canonical_quantity(
            line.get("quantity")
            if line.get("quantity") is not None
            else line.get("quantite")
        ),
        "unit": canonical_unit(line.get("unit") or line.get("unite")),
        "label": str(
            line.get("label")
            or line.get("designation")
            or line.get("libelle_article")
            or ""
        ),
    }


def canonical_lines(lines: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for line in lines:
        canonical = canonical_line(line)
        if canonical["code"]:
            result.append(canonical)
    return result


def line_counter(lines: Iterable[dict[str, str]]) -> Counter[tuple[str, str, str]]:
    return Counter(
        (line["code"], line["quantity"], line["unit"])
        for line in lines
        if line["code"]
    )


def code_counter(lines: Iterable[dict[str, str]]) -> Counter[str]:
    return Counter(line["code"] for line in lines if line["code"])


def overlap(left: Counter[Any], right: Counter[Any]) -> int:
    return sum((left & right).values())


def _expanded(counter: Counter[tuple[str, str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for (code, quantity, unit), count in sorted(counter.items()):
        rows.extend(
            {"code": code, "quantity": quantity, "unit": unit}
            for _ in range(count)
        )
    return rows


def _candidate_rank(diagnostics: dict[str, Any], expected_code: str) -> int | None:
    best: int | None = None
    for product in diagnostics.get("products") or []:
        for rank, candidate in enumerate(product.get("candidats") or [], start=1):
            if canonical_code(candidate.get("code_article")) != expected_code:
                continue
            best = rank if best is None else min(best, rank)
    return best


def compare_order(
    truth_row: dict[str, Any],
    prediction_row: dict[str, Any] | None,
) -> dict[str, Any]:
    prediction = prediction_row or {}
    truth_lines = canonical_lines(truth_row.get("truth_lines") or [])
    predicted_lines = canonical_lines(prediction.get("lines") or [])
    truth_exact = line_counter(truth_lines)
    predicted_exact = line_counter(predicted_lines)
    truth_codes = code_counter(truth_lines)
    predicted_codes = code_counter(predicted_lines)
    exact_matches = overlap(truth_exact, predicted_exact)
    code_matches = overlap(truth_codes, predicted_codes)
    missing = truth_exact - predicted_exact
    extra = predicted_exact - truth_exact

    truth_client = normalize_text(truth_row.get("truth_client"))
    predicted_client = normalize_text(prediction.get("client_code"))
    client_correct = bool(truth_client and truth_client == predicted_client)
    truth_date = str(truth_row.get("truth_delivery_date") or "")[:10]
    predicted_date = str(prediction.get("delivery_date") or "")[:10]
    date_required = bool(truth_date)
    date_correct = (not date_required) or truth_date == predicted_date
    lines_exact = bool(truth_lines) and truth_exact == predicted_exact
    content_exact = client_correct and lines_exact
    accepted = str(prediction.get("status") or "").upper() == "VALIDEE"
    automation_exact = content_exact and date_correct and accepted

    causes: set[str] = set()
    if not prediction_row or prediction.get("error"):
        causes.add("prediction_absente_ou_erreur")
    if not predicted_client:
        causes.add("client_non_reconnu")
    elif not client_correct:
        causes.add("mauvais_client")
    if date_required and not date_correct:
        causes.add("date_livraison")

    missing_codes = truth_codes - predicted_codes
    extra_codes = predicted_codes - truth_codes
    diagnostics = prediction.get("diagnostics") or {}
    if missing_codes:
        ranks = [
            _candidate_rank(diagnostics, code)
            for code in missing_codes
            for _ in range(missing_codes[code])
        ]
        if any(rank is not None for rank in ranks):
            causes.add("classement_produit")
        elif len(diagnostics.get("products") or []) < len(truth_lines):
            causes.add("segmentation_ou_asr")
        else:
            causes.add("recherche_candidat")
    if extra_codes:
        causes.add("faux_produit")

    for code in set(truth_codes) & set(predicted_codes):
        truth_for_code = [line for line in truth_lines if line["code"] == code]
        pred_for_code = [line for line in predicted_lines if line["code"] == code]
        if line_counter(truth_for_code) == line_counter(pred_for_code):
            continue
        if Counter(line["quantity"] for line in truth_for_code) != Counter(
            line["quantity"] for line in pred_for_code
        ):
            causes.add("quantite")
        if Counter(line["unit"] for line in truth_for_code) != Counter(
            line["unit"] for line in pred_for_code
        ):
            causes.add("unite_conditionnement")
    if content_exact and not accepted:
        causes.add("rejet_interne_d_une_commande_correcte")

    return {
        "audio": str(truth_row.get("audio") or ""),
        "split": str(truth_row.get("split") or "unspecified"),
        "truth_order_number": str(truth_row.get("truth_order_number") or ""),
        "pairing_confidence": truth_row.get("pairing_confidence") or {},
        "truth_client": truth_client,
        "predicted_client": predicted_client,
        "client_correct": client_correct,
        "truth_delivery_date": truth_date,
        "predicted_delivery_date": predicted_date,
        "date_correct": date_correct,
        "truth": truth_lines,
        "predicted": predicted_lines,
        "truth_count": len(truth_lines),
        "predicted_count": len(predicted_lines),
        "code_matches": code_matches,
        "exact_matches": exact_matches,
        "lines_exact": lines_exact,
        "content_exact": content_exact,
        "accepted": accepted,
        "automation_exact": automation_exact,
        "missing": _expanded(missing),
        "extra": _expanded(extra),
        "expected_candidate_ranks": {
            code: _candidate_rank(diagnostics, code) for code in sorted(missing_codes)
        },
        "causes": sorted(causes),
        "prediction_error": str(prediction.get("error") or ""),
        "transcription": str(prediction.get("transcription") or ""),
        "diagnostics": diagnostics,
    }


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in results if row["truth_count"] > 0]
    truth_lines = sum(row["truth_count"] for row in eligible)
    predicted_lines = sum(row["predicted_count"] for row in eligible)
    code_matches = sum(row["code_matches"] for row in eligible)
    exact_matches = sum(row["exact_matches"] for row in eligible)
    total = len(eligible)

    def ratio(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator else 0.0

    cause_counts = Counter(
        cause for row in eligible for cause in row.get("causes") or []
    )
    return {
        "audios": total,
        "excluded_without_truth_lines": len(results) - total,
        "truth_lines": truth_lines,
        "predicted_lines": predicted_lines,
        "product_code_recall": ratio(code_matches, truth_lines),
        "product_code_precision": ratio(code_matches, predicted_lines),
        "exact_line_recall": ratio(exact_matches, truth_lines),
        "exact_line_precision": ratio(exact_matches, predicted_lines),
        "client_accuracy": ratio(sum(bool(row["client_correct"]) for row in eligible), total),
        "delivery_date_accuracy": ratio(sum(bool(row["date_correct"]) for row in eligible), total),
        "line_set_accuracy": ratio(sum(bool(row["lines_exact"]) for row in eligible), total),
        "order_content_accuracy": ratio(sum(bool(row["content_exact"]) for row in eligible), total),
        "automatic_acceptance_rate": ratio(sum(bool(row["accepted"]) for row in eligible), total),
        "automation_order_accuracy": ratio(sum(bool(row["automation_exact"]) for row in eligible), total),
        "perfect_content_orders": sum(bool(row["content_exact"]) for row in eligible),
        "perfect_automatic_orders": sum(bool(row["automation_exact"]) for row in eligible),
        "cause_counts": dict(cause_counts.most_common()),
    }


def evaluate_rows(
    truth_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, dict[str, Any]]]:
    predictions = {str(row.get("audio") or ""): row for row in prediction_rows}
    results = [
        compare_order(row, predictions.get(str(row.get("audio") or "")))
        for row in truth_rows
    ]
    metrics = aggregate(results)
    by_split = {
        split: aggregate([row for row in results if row["split"] == split])
        for split in sorted({row["split"] for row in results})
    }
    return results, metrics, by_split
